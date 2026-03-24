# Feature-Based Classification Pipeline — Architecture Without the 196→PRISM Mapping

**Author:** Markus / Claude Code
**Date:** 2026-03-22
**Status:** Proposal — addresses how to use Payout_to_Features without the complete PRISM mapping column, and how to avoid making the 196-item list a bottleneck

---

## Core Principle

The 196-item list is **vocabulary, not a gate.**

The pipeline must classify a filing to one of ~9 PRISM models. The 196-item list enumerates known product variants with their feature vectors, but the PRISM models operate at a coarser level — each PRISM model corresponds to a cluster of those 196 types. The classifier does not need to identify which of the 196 a filing is; it needs to identify which cluster (= PRISM model) it belongs to. The 196-item list informs that classification without gating it.

A filing that exhibits no exact match in the 196-item list can still be confidently placed into a PRISM model if its feature vector falls within the right cluster region.

---

## Why This Works: The Cluster Structure

Analysing the 196 rows, four features do most of the discriminating work at the PRISM level:

```
PRODUCT_SUB_TYPE     (GROWTH / PROTECTION / YIELD)
DOWNSIDE_PROTECTION  (BUFFER / BARRIER / FLOOR / FULL / NONE)
HAS_COUPON           (True / False)
CALL_TYPE            (AUTO_CALLABLE / ISSUER_CALLABLE / AUTO_WITH_STEP / NONE)
```

These four dimensions partition the 196 types into approximately 10–12 stable natural clusters — one per PRISM model. The remaining 18 features add specificity *within* a PRISM cluster (e.g. distinguishing a memory yield note from a plain contingent yield note) but do not change the PRISM assignment.

**Example clusters observed in the data:**

| PRISM cluster (descriptive) | SUB_TYPE | DOWNSIDE | COUPON | COUNT |
|-----------------------------|----------|----------|--------|-------|
| Yield / barrier / autocall (contingent coupon) | YIELD | BARRIER | CONTINGENT+barrier | 13 |
| Yield / buffer / autocall (contingent coupon) | YIELD | BUFFER | CONTINGENT+barrier | 12 |
| Growth / buffer / no call | GROWTH | BUFFER | None/NONE | 26 |
| Growth / barrier / no call | GROWTH | BARRIER | None/NONE | 14 |
| Growth / buffer / autocall | GROWTH | BUFFER | None/NONE | 12 (callable) |
| Protection / floor / no coupon | PROTECTION | FLOOR | None/NONE | 28 |
| Protection / floor / fixed coupon | PROTECTION | FLOOR | FIXED | 6 |
| Protection / floor / contingent coupon | PROTECTION | FLOOR | CONTINGENT | 9 |

Each cluster is naturally bounded. A filing that is YIELD + BARRIER + CONTINGENT coupon with a coupon barrier falls into the same PRISM model regardless of whether it also has a step-down autocall trigger, a memory feature, or any other secondary characteristic.

---

## Proposed Pipeline Architecture

```
EDGAR filing (HTML/text)
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 1: FEATURE EXTRACTION                              │
 │                                                          │
 │ LLM extracts the 22 structured features from the filing: │
 │   - PRODUCT_SUB_TYPE    (GROWTH / PROTECTION / YIELD)    │
 │   - DOWNSIDE_PROTECTION_TYPE                             │
 │   - HAS_COUPON, COUPON_TYPE, HAS_COUPON_BARRIER          │
 │   - CALL_TYPE                                            │
 │   - HAS_COUPON_MEMORY, HAS_ABSOLUTE_RETURN, ...          │
 │   - WRAPPER_GROUP       (NOTE / CD)                      │
 │                                                          │
 │ Output: structured feature dict                          │
 │ This step is ALWAYS performed, for every filing.         │
 └─────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 2: PRISM MODEL MATCHING                            │
 │                                                          │
 │ Match the feature dict against PRISM model feature       │
 │ profiles (see Section below).                            │
 │                                                          │
 │ Each PRISM model has a profile of required, typical,     │
 │ and counter-indicated features. Score = feature overlap. │
 │                                                          │
 │ Output: ranked PRISM model candidates with scores        │
 │   → score ≥ 0.80: classified                            │
 │   → score 0.60–0.79: needs_classification_review        │
 │   → score < 0.60: needs_review                          │
 └─────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 3: 196-LIST ENRICHMENT (optional, non-gating)      │
 │                                                          │
 │ Fuzzy-match the extracted feature dict against the       │
 │ 196-item list (payout_features.json).                    │
 │                                                          │
 │ If a close match is found (distance ≤ 2 features):      │
 │   - Record the matched payout type name                  │
 │   - Use the name as a confidence booster in Stage 2      │
 │   - Surface the name in the UI for the reviewer          │
 │                                                          │
 │ If no close match is found:                              │
 │   - Classification proceeds from Stage 2 alone           │
 │   - Flag: "novel payout variant — not in reference list" │
 │   - This is informational, NOT a classification failure  │
 │                                                          │
 │ Output: optional matched payout type name + distance     │
 └─────────────────────────────────────────────────────────┘
        │
        ▼
 ┌─────────────────────────────────────────────────────────┐
 │ Stage 4: FIELD EXTRACTION                                │
 │ (already implemented)                                    │
 │                                                          │
 │ Use the assigned PRISM model schema to extract fields.   │
 └─────────────────────────────────────────────────────────┘
```

---

## PRISM Model Feature Profiles (no mapping column needed)

This is the key enabler. Instead of deriving PRISM profiles from the 196→PRISM mapping, the profiles are **written directly** against the 22 feature dimensions — using the schema's existing model knowledge plus the feature vocabulary from the xlsx. This is the same work as populating `classificationHints` (task A1), now expressed in structured feature terms.

**Format per PRISM model:**

```json
{
  "model_id": "yieldEnhancementAutocall",
  "required_features": {
    "HAS_COUPON": true,
    "HAS_COUPON_BARRIER": true,
    "CALL_TYPE": ["AUTO_CALLABLE", "AUTO_WITH_STEP"]
  },
  "typical_features": {
    "DOWNSIDE_PROTECTION_TYPE": ["BARRIER", "BUFFER"],
    "COUPON_TYPE": "CONTINGENT",
    "HAS_COUPON_MEMORY": true
  },
  "counter_features": {
    "DOWNSIDE_PROTECTION_TYPE": "FLOOR",
    "HAS_UPSIDE_PARTICIPATION": true,
    "HAS_COUPON": false
  }
}
```

**Required features** are definitional — if absent, this model cannot apply. Scoring starts at 1.0 and is penalised if required features don't match.

**Typical features** are characteristic but not definitional — they boost confidence when present.

**Counter-features** actively reduce the score when present — they indicate a different model.

This structure can be written for all 9 PRISM models in **~2 hours**, entirely from existing schema knowledge plus the feature vocabulary from the xlsx. It does not depend on the 196→PRISM mapping at all.

Once the 196→PRISM mapping column is complete, it serves as *validation* — the model profiles can be checked for consistency with the mapped clusters — but the pipeline runs without it.

---

## Handling Novel Payouts (Not on the 196-Item List)

The 196-item list encodes **known** product variants as of the file's creation date. New structured products will appear on EDGAR that combine features in ways not previously documented. The pipeline handles these in four ways:

### 1. Feature extraction is product-agnostic
The Stage 1 extraction asks about features, not about product identity. A novel product that has never been seen before still produces a feature vector. The LLM does not need to recognise the product to answer "does this pay a contingent coupon?".

### 2. PRISM matching operates on the cluster, not the variant
PRISM models are defined at the cluster level. A novel payout type that is YIELD + BARRIER + CONTINGENT coupon + COUPON_BARRIER matches the `yieldEnhancementAutocall` cluster regardless of secondary features. The cluster boundary is wide enough to accommodate variants.

### 3. Distance to nearest list entry is informational, not diagnostic
Stage 3 reports the nearest match in the 196-item list and the Hamming distance (number of mismatched features). A distance of 0–1 suggests the filing is a known variant. A distance of 3+ suggests it is genuinely novel. This information surfaces to the reviewer but does not block classification.

### 4. Novel variants are flagged for list addition
If Stage 3 finds no close match, the system records the feature vector and the PRISM model assignment. This creates a candidate row for the next update of Payout_to_Features.xlsx — the list grows organically from operational use without any manual triage. Over time the list converges toward completeness.

---

## Phased Implementation

### Phase 1 — Now (no mapping column needed)

**What to build:**
1. A JSON file `files/prism_model_profiles.json` containing the feature profiles for the 9 existing PRISM models (required, typical, counter-features per model). Effort: ~2 hours.
2. A Stage 1 prompt template in the classifier that extracts the 22 features from a filing in a structured JSON response.
3. A scoring function in `classifier.py` that computes match scores between an extracted feature dict and each model's profile.
4. Stage 3 as a lightweight lookup against `payout_features.json` (fuzzy match on feature dict, Hamming distance).

**What this achieves:**
Full classification pipeline based on document comprehension alone. CUSIP xlsx becomes redundant. 196-item list is consulted as optional enrichment.

### Phase 2 — When mapping column is available

**What to add:**
1. A `PRISM_MODEL_ID` column in Payout_to_Features.xlsx (and regenerate `payout_features.json`).
2. Use the mapped clusters to validate and refine the Phase 1 model profiles.
3. Stage 3 becomes more informative: a close match to a 196-item row now also confirms the PRISM model assignment.

**What this achieves:**
Profile validation, confidence calibration, and richer UI display (matched payout type name surfaces alongside PRISM model). No change to the pipeline structure — Phase 2 is an upgrade, not a redesign.

---

## Why the 196-Item List Cannot Become a Bottleneck

The bottleneck risk arises only if the pipeline **requires** an exact match to the list before proceeding. The architecture above eliminates this in three ways:

1. **Classification happens at PRISM level, not list level.** The list has 196 rows; PRISM has 9 models. The coarser level has far more tolerance for variation.

2. **No match is a valid outcome, not an error.** A filing that doesn't match any of the 196 types is classified by its PRISM profile score and flagged as a novel variant. It is not blocked.

3. **The list grows from use.** Novel variants flagged in Stage 3 are automatically candidates for list addition. The list expands toward the product universe over time without becoming a maintenance burden, because each new entry is derived from a real filing that was already successfully classified.

---

## Relationship to Existing Tasks

| Task | Impact |
|------|--------|
| A1 — classificationHints in schema | The PRISM model feature profiles (Phase 1) become the machine-readable equivalent of classificationHints. They can be embedded into the schema's `classificationHints.features` block directly. |
| A2 — two missing PRISM models | Add feature profiles for `yieldEnhancementAutocallBufferCoupon` and `participationBufferDigital` alongside their schema definitions. |
| B1 — three-state status | Stage 2 scoring maps directly: ≥0.80 → classified, 0.60–0.79 → needs_classification_review, <0.60 → needs_review. No additional logic needed. |
| C2 — demote CUSIP xlsx | Immediately achievable once Phase 1 is running. The feature-based pipeline does not reference the xlsx. |
| C3 — feature matrix per model | This document *is* C3. The PRISM model feature profiles described here are exactly what C3 calls for. |

---

*Next step: draft `files/prism_model_profiles.json` as Phase 1 foundation. Requires reviewing the 9 PRISM model schemas to assign required/typical/counter features from the 22-dimension vocabulary.*
