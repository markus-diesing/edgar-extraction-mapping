# Model Scaling Strategy — Beyond the CUSIP Mapping Excel

**Author:** Markus / Claude Code
**Date:** 2026-03-22
**Status:** Strategic proposal — open questions pending answer before implementation

---

## Background

The `CUSIP_PRISM_Mapping.xlsx` file was introduced at project start as *first guidance* for mapping EDGAR filings to PRISM payout models. It served two purposes:

1. **Classification shortcut** — "I've already seen this CUSIP, I know it's a Barrier Note, skip the classifier"
2. **Trust scaffold** — at project start the Claude classifier was unproven; a pre-mapped ground truth acted as a safety net

Both purposes assume a human maintains the file as the product universe grows. This does not scale as PRISM adds new models and new structured products appear in EDGAR.

**Goal:** The tool must be able to map any structured product payout it encounters to precisely one PRISM schema — including products and model types it has never seen before — without depending on externally maintained lookup files.

---

## The Root Problem

The classification knowledge currently lives outside the system (in the xlsx). The system needs to move from:

> *"Look up this CUSIP in a table someone maintained"*

to:

> *"Read this document and determine which PRISM model describes the product it contains"*

That is a shift from a **retrieval problem** to a **comprehension problem**.

The two-stage Claude classifier already solves the comprehension problem in principle. It fails when it lacks sufficient knowledge about what each model represents. The xlsx has been partially filling that gap by providing pre-classified examples. What is needed is a way to embed that knowledge permanently and scalably into the system itself.

**What the classifier currently receives about each model:**
- The model's JSON Schema (field names, types, enums) — structural only
- The model's identifier string, e.g. `yieldEnhancementAutocall` — a name, not a description

**What a human expert uses to classify the same document:**
- Knowledge of what autocall behaviour looks like in plain text
- Awareness of typical product titles ("Phoenix", "Stepdown", "Accelerated Return Note")
- Understanding of discriminating features (barrier vs. buffer, conditional coupon vs. fixed)
- Experience of which issuers use which structural vocabulary

The gap between those two is what needs closing.

---

## Proposed Approaches (Ranked by Sustainability)

### Option 1 — `classificationHints` Block in the Schema *(highest priority)*

Each model in `prism-v1.schema.json` receives a companion hints block:

```json
"classificationHints": {
  "description": "A structured product that pays a conditional coupon when the underlying closes above a coupon barrier on observation dates. The product autocalls (redeems early at par plus coupon) when the underlying closes above an autocall trigger. At maturity, capital is at risk if the final underlying level is below a capital barrier.",
  "title_keywords": ["Phoenix", "Contingent Income", "Barrier Note", "Memory Coupon"],
  "feature_indicators": ["coupon barrier", "observation date", "memory feature", "autocall trigger", "knock-in level"],
  "discriminating_fields": ["coupon.barrierLevel", "autocall.triggerLevel", "barrier.knockInLevel"],
  "counter_indicators": ["capital protection", "full participation", "leverage factor", "digital payment"]
}
```

**How it works:** The classifier prompt is built dynamically from the schema at runtime. When a new model is added to PRISM, the schema author also writes the hints block (≈15 minutes). No separate file. No separate process. The hints travel with the schema and are picked up automatically by the next `schema fetch → activate` cycle.

**Human effort per new model:** ~15 minutes, once, by someone who understands the product type.
**Sustainability:** High — schema is already the single source of truth for structure; it becomes the single source of truth for classification knowledge too.
**Implementation status:** Specified in `CLASSIFICATION_HINTS_SPEC.md`; not yet added to `prism-v1.schema.json`.

---

### Option 2 — Feature Matrix as Discriminating Logic

Define a boolean feature vector per model alongside the hints:

```json
"features": {
  "has_autocall": true,
  "has_conditional_coupon": true,
  "has_barrier": true,
  "capital_at_risk": true,
  "leverage": false,
  "capital_protection": false,
  "digital_payment": false,
  "participation": false
}
```

The classifier can then ask: (a) which features does this document exhibit? (b) which model has that exact feature combination?

**Advantage:** Precise for disambiguating similar models (e.g. autocall with coupon vs. autocall without coupon). New models add a row. No prose required for the matrix itself.
**Limitation:** Works better as a *second-stage* discriminator than a primary classifier — a filing doesn't always make features explicit; the LLM still needs to infer from natural language.
**Best used as:** A companion to Option 1, not a replacement.

---

### Option 3 — Few-Shot Product Examples Embedded in Schema

Each model carries 2–3 representative product title strings and issuer examples:

```json
"examples": [
  { "title": "Contingent Income Auto-Callable Securities due 2026", "issuer": "Barclays" },
  { "title": "Phoenix Notes with Memory Coupon linked to S&P 500", "issuer": "JPMorgan" },
  { "title": "Auto-Callable Contingent Interest Notes", "issuer": "Goldman Sachs" }
]
```

The classifier prompt includes these as labelled examples. One human who has seen real filings provides them once per model. Very effective because the vocabulary in the examples matches the vocabulary in new filings from the same issuer family.

**Advantage:** Leverages Claude's few-shot capability directly; very low engineering effort.
**Human effort:** ~10 minutes per model; requires someone who has seen real filings of that type.

---

### Option 4 — Demote CUSIP Mapping to Optional Enrichment

Rather than removing the xlsx, demote it: it remains as optional enrichment that *improves* confidence but is never required. If a CUSIP is found in the mapping, boost the Stage 1 score. If not found, the classifier proceeds on document evidence alone.

**Advantage:** Least disruptive; preserves historical value of existing mappings; backwards compatible.
**Limitation:** Does not solve the new-model discovery problem on its own.
**Role:** Transition step while Options 1–3 are implemented.

---

### Option 5 — Active Learning from Approved Extractions *(longer horizon)*

Once a filing has been classified, extracted, reviewed, and approved, it becomes a labelled example. The system builds its own classification ground truth from past work. New filings with similar cover-page patterns are matched against this growing example set.

**Advantage:** Fully self-sustaining at scale; the xlsx replacement emerges from the tool's own usage.
**Limitation:** Requires volume (≥50 approved filings per model type) before reliable; several months of operation at current throughput.
**Role:** Long-term layer; does not replace the schema-embedded hints in the near term.

---

## Recommended Direction

Layer the options as complementary capabilities:

| Phase | Action | What it replaces |
|-------|--------|-----------------|
| **Now** | Implement `classificationHints` + feature matrix in schema (Options 1+2) | Primary classification signal; renders xlsx unnecessary for known models |
| **Now** | Add few-shot examples to schema (Option 3) | Fills vocabulary gap for new models on first encounter |
| **Transition** | Demote xlsx to optional confidence booster (Option 4) | No hard dependency; xlsx contribution fades as schema hints mature |
| **Long-term** | Active learning from approved filings (Option 5) | Dynamic self-improvement; no human input required for seen product families |

---

## Open Questions (to be answered before implementation)

These questions determine the shape of the implementation:

**Q1 — Who authors new model schemas, and does documentation come with them?**
When the PRISM team adds a model, do they provide a description, term sheet, or naming conventions alongside the JSON schema? If yes, that documentation is the raw material for classificationHints and the human effort per new model is close to zero.

**Q2 — Is any initial human annotation acceptable per new model?**
There is a meaningful difference between "someone spends 15 minutes writing hints when model X is added" and "the system must handle model X with no human involvement at all". The first is achievable immediately. The second requires active learning and months of data accumulation.

**Q3 — What is the expected frequency of new PRISM models?**
Monthly? Quarterly? Annually? This affects whether the one-time-per-model annotation effort is negligible or burdensome.

**Q4 — What happens when a filing matches no current PRISM model?**
Should the system output "no matching model — candidate for new model definition"? Or is the assumption that PRISM always covers what EDGAR contains? If structured products evolve faster than PRISM does, a graceful "I don't know" path is needed.

**Q5 — Is classification primarily about product type, or also about issuer-specific naming?**
Two Barclays Phoenix Notes and one JPMorgan Contingent Income Note may be structurally identical PRISM models described in completely different vocabulary. At what point is a new product genuinely a new PRISM model vs. a renamed variant of an existing one?

**Q6 — What is the acceptable classification error rate for a new model on first encounter?**
A brand-new model with only schema hints and no historical examples will have higher misclassification risk on the first few filings. Is "flag for manual review for the first N filings of a new model type" an acceptable policy?

---

## Relationship to Existing Open Tasks

This strategy directly drives or informs:

- **A1** — Add `classificationHints` to `prism-v1.schema.json` (9 existing models + 2 missing)
- **A2** — Add two missing payout models (`yieldEnhancementAutocallBufferCoupon`, `participationBufferDigital`)
- **B1/B2/B3** — Classification review gate and confirmation workflow (needed for the "flag new model type for review" policy)
- The xlsx can be formally deprecated once A1 and A2 are complete and validated on a test batch

---

*Next step: answer Q1–Q6 above, then proceed to implement Option 1 (classificationHints) as the foundation.*
