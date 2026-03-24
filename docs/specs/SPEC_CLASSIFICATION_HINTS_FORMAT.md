# classificationHints — Format Specification and Rationale

**Version:** 1.0 draft
**Date:** 2026-03-22
**Status:** For discussion with PRISM schema team
**Audience:** Authors of PRISM model schemas

---

## 1. The Problem: JSON Schema Describes Structure, Not Meaning

A JSON Schema document is an excellent machine-readable contract for data structure: it specifies which fields exist, their types, their constraints, and their relationships. This is precisely what it is designed to do.

It does not, however, convey what a model *represents* in the real world. Two schema definitions that differ substantially in financial meaning may look nearly identical structurally — both may have an `autocall` block, a `coupon` block, and a `downsideRisk` block, while representing fundamentally different product families with different risk profiles, different investor purposes, and entirely different documentary language.

This gap is invisible to a human expert reading the schema alongside a product term sheet, because the human brings prior knowledge. It is not invisible to the expert — it is transparent. But it is a genuine gap for any automated system that reads the schema programmatically.

---

## 2. Why This Matters Specifically for AI-Based Processing

Large language model (LLM) systems that classify documents or extract structured data from them operate by reasoning over natural language. When such a system is asked to determine which schema model a source document corresponds to, it does the following:

1. Reads a description of each candidate model
2. Reads the source document
3. Reasons about which description best matches the document's content

Step 1 is the critical step. If the only description available is the JSON Schema itself — field names, types, required arrays — the LLM must infer the product's meaning from structural signals alone. It will attempt this, and it will often succeed for models with highly distinctive structures. But for models that are structurally similar, or whose schema field names do not directly correspond to the vocabulary used in source documents, the inference is unreliable.

**The vocabulary mismatch problem** is particularly acute. A source document describing a structured note may use the phrase "contingent quarterly coupon" dozens of times. The corresponding schema field may be named `coupon.barrierLevel`. The LLM must bridge that gap — and it can — but every gap introduces noise into the classification decision. Multiply that across many similar models and the cumulative noise degrades accuracy meaningfully.

**The negative-space problem** is equally important but less obvious. Knowing what a model *is* is useful. Knowing what it is *not* — specifically, which superficially similar models it should be distinguished from — is often more useful. JSON Schema provides no mechanism for expressing this. An LLM classifying between two adjacent models has no signal about which features discriminate between them unless that signal is explicitly provided.

---

## 3. The Proposed Solution: `classificationHints`

`classificationHints` is an optional companion block added to each model definition in the schema. It is not validated as part of data payloads — it is metadata about the model itself, written in natural language and structured for machine consumption by AI tooling.

Its purpose is to close the gap between structural schema knowledge and the semantic knowledge a domain expert brings when reading source documents. The block is authored once by the person who defines the model — the natural knowledge-holder — and travels with the schema thereafter. Any system that reads the schema can use the hints without consulting a separate file, a separate service, or a separate team.

---

## 4. Format Specification

The `classificationHints` block is placed at the top level of each model object, alongside `title`, `properties`, and `required`. It is a JSON object with the following fields.

```json
"classificationHints": {
  "description": "string — required",
  "typical_document_language": ["string", "..."],
  "title_keywords": ["string", "..."],
  "discriminating_features": ["string", "..."],
  "counter_indicators": ["string", "..."],
  "notes_for_classifier": "string — optional"
}
```

### 4.1 `description` *(required)*

A concise prose description of the product type this model represents. Written as if explaining to a knowledgeable analyst who has not seen this specific model before. Should cover:

- What economic purpose the product serves for its buyer
- The key structural mechanism (how returns are generated, how downside is managed)
- What makes this product type distinct from adjacent types

**Length:** 3–6 sentences. Longer is not better — precision is the goal.

**Do not:** Describe the schema fields. Describe the product.

**Example:**
> "A structured note that pays a periodic coupon contingent on the underlying closing above a predetermined barrier level on each observation date. If the underlying falls below a separate knock-in barrier at maturity, the investor bears the downside loss proportional to the underlying's decline. The product may redeem early (autocall) if the underlying closes above a trigger level on a scheduled observation date. Capital is at risk; there is no floor on losses below the knock-in."

---

### 4.2 `typical_document_language` *(recommended)*

A list of phrases, exactly or near-exactly as they appear in source documents describing products of this type. These are not invented terms — they are transcribed from real term sheets, offering documents, or prospectus supplements.

**Purpose:** Bridges the vocabulary gap between schema field names and document language. The AI classifier uses these as anchors when reading a source document.

**Guidance:** Include 6–12 phrases. Prefer phrases that appear *across multiple issuers and jurisdictions* — idiosyncratic single-issuer language is less useful here. Prefer phrases that are structurally diagnostic (they indicate this product type) rather than merely common (they appear in many product types).

**Example:**
```json
"typical_document_language": [
  "contingent coupon",
  "coupon barrier",
  "memory coupon",
  "knock-in level",
  "autocall trigger",
  "early redemption at par",
  "observation date",
  "contingent interest"
]
```

---

### 4.3 `title_keywords` *(recommended)*

A list of words or short phrases that commonly appear in the marketing name or official title of products of this type. These are the terms issuers use in the security name that appears on a cover page.

**Purpose:** Cover pages and titles are highly consistent within a product family. An AI reading the document title benefits from knowing which title terms are diagnostic for this model.

**Guidance:** Include 4–8 terms. Focus on terms that distinguish this model from adjacent ones, not terms that appear broadly across all structured products.

**Example:**
```json
"title_keywords": [
  "Phoenix",
  "Contingent Income",
  "Barrier Note",
  "Memory Note",
  "Auto-Callable Contingent",
  "Stepdown Autocallable"
]
```

---

### 4.4 `discriminating_features` *(required)*

A list of structural characteristics that define this model and distinguish it from other similar models. Written as brief declarative phrases. These should correspond to the most diagnostically significant aspects of the product — the features whose presence or absence most reliably identifies the model family.

**Purpose:** Gives the classifier a structured checklist of what to look for. Particularly effective when two models share many surface features but differ on one or two critical dimensions — the discriminating features make those dimensions explicit.

**Guidance:** Include 4–8 items. Be specific. "Has a coupon barrier" is useful. "Has a coupon" is not — too many models have coupons.

**Example:**
```json
"discriminating_features": [
  "Coupon is conditional on underlying closing above a barrier on observation dates",
  "Coupon memory: missed coupons are paid on the next qualifying observation date",
  "Capital loss is tied to a separate knock-in (barrier) event at maturity",
  "Autocall redeems the note early when trigger is met, not on any date"
]
```

---

### 4.5 `counter_indicators` *(required)*

A list of features or phrases that, if present in a source document, make this model the *wrong* classification — even if other signals point toward it. These are the negative signals: they rule this model out.

**Purpose:** Reduces false positives between adjacent models. A classifier that knows only what a model *is* will sometimes assign it incorrectly when a neighbouring model is slightly less well-described. Counter-indicators provide the discriminating boundary explicitly.

**Guidance:** Include 3–6 items. Focus on features that appear in models that are commonly confused with this one, not arbitrary negative features. If model A and model B are frequently confused, model A's counter-indicators should describe model B's distinguishing features, and vice versa.

**Example:**
```json
"counter_indicators": [
  "Capital is fully protected or guaranteed at maturity",
  "Return is based on upside participation or leverage, with no coupon mechanism",
  "Downside is cushioned by a buffer, not a barrier (no cliff-edge loss event)",
  "There is no conditional coupon — this is a pure growth product"
]
```

---

### 4.6 `notes_for_classifier` *(optional)*

Free-form guidance for edge cases, common misclassification scenarios, or issuer-specific nuances that do not fit neatly into the structured fields above.

**Use sparingly.** If a distinction is important enough to note here, consider whether it belongs in `discriminating_features` or `counter_indicators` instead.

**Example:**
> "Some issuers describe the knock-in as a 'downside threshold' rather than a 'barrier'. The economic function is identical. Do not distinguish these terminologically — treat 'downside threshold' as synonymous with 'knock-in barrier' for classification purposes."

---

## 5. Worked Examples

### Example A — a yield-enhancement product with autocall and barrier

```json
"classificationHints": {
  "description": "A structured note that pays a periodic conditional coupon when the underlying asset closes above a coupon barrier on scheduled observation dates. The note autocalls (redeems early at par plus any due coupon) if the underlying closes above an autocall trigger level on an observation date. At maturity, if the note has not autocalled and the underlying has breached a knock-in barrier at any point, the investor receives a return linked to the underlying's decline rather than par. Capital is at risk below the knock-in level.",
  "typical_document_language": [
    "contingent coupon",
    "coupon barrier",
    "observation date",
    "knock-in level",
    "autocall trigger",
    "automatic early redemption",
    "contingent interest",
    "memory coupon"
  ],
  "title_keywords": [
    "Phoenix",
    "Contingent Income",
    "Memory Coupon",
    "Auto-Callable Contingent",
    "Barrier Note"
  ],
  "discriminating_features": [
    "Coupon is paid only when the underlying closes at or above the coupon barrier",
    "Missed coupons accumulate and are paid when a qualifying observation date occurs (memory feature)",
    "Autocall redeems at par plus accrued coupon on a scheduled observation date",
    "Capital loss at maturity is triggered by a breach of the knock-in barrier — a step-change loss, not a gradual buffer"
  ],
  "counter_indicators": [
    "Capital is protected or guaranteed at maturity regardless of underlying performance",
    "There is no conditional coupon — the product provides upside participation instead",
    "Downside protection takes the form of a buffer (proportional absorption of losses), not a barrier",
    "The product provides leveraged upside above a digital return threshold"
  ]
}
```

---

### Example B — a capital-protected growth product with floor

```json
"classificationHints": {
  "description": "A structured note or deposit that guarantees return of principal at maturity regardless of underlying performance (the 'floor'), while offering participation in any upside of the underlying asset. The investor cannot lose their initial investment but gains exposure to the positive performance of the underlying, subject to any participation rate or cap. The product is suitable for capital-preservation mandates seeking market exposure.",
  "typical_document_language": [
    "principal protection",
    "capital guarantee",
    "floor",
    "100% capital protected",
    "participation rate",
    "upside participation",
    "protected note",
    "guaranteed return of principal"
  ],
  "title_keywords": [
    "Protected Note",
    "Capital Guaranteed",
    "Principal Protected",
    "Growth Note with Floor",
    "Protected Participation"
  ],
  "discriminating_features": [
    "Principal is fully returned at maturity under all underlying scenarios — no capital loss possible",
    "Upside is linked to underlying performance via a participation rate (may be capped or uncapped)",
    "There is no knock-in barrier and no barrier-triggered loss event",
    "Coupon, if present, is fixed and unconditional — not contingent on underlying performance"
  ],
  "counter_indicators": [
    "Capital is at risk if the underlying breaches a barrier — this indicates a barrier or buffer product, not capital protection",
    "The product pays a conditional coupon contingent on the underlying level — this is a yield-enhancement structure",
    "The product autocalls and bears downside risk below a knock-in — this is not a capital-protection product",
    "There is no floor or guarantee on the return of principal"
  ]
}
```

---

## 6. Guidance for Schema Authors

**Who should write the hints?** The person defining the model schema is the right author. They know the product type, the intended use case, and the adjacent models it might be confused with. The hints do not require engineering knowledge — they require product knowledge.

**When should hints be written?** At the same time as the model schema itself. Hints written alongside the schema take 10–15 minutes. Hints retrofitted onto an existing schema take 20–30 minutes because the author must re-engage with the model's semantics.

**What is the primary test of a good hints block?** Read the `description` and `discriminating_features` aloud. Could a junior analyst use them to correctly classify a term sheet they have never seen before, with no other information? If yes, the hints are sufficient. If not, something is missing.

**What should not go in the hints block?** Schema field names. Implementation details. References to specific issuers, CUSIPs, or individual products. The hints describe the product type in general, not any particular instance.

---

## 7. Why the Hints Travel with the Schema

An alternative design would place classification knowledge in a separate lookup table, a separate configuration file, or a separate service. That design has a consistent failure mode: the lookup table drifts out of sync with the schema. Models are added to the schema; the lookup is not updated. Classification degrades. Someone notices months later.

When the hints block is part of the schema definition, this failure mode is structurally prevented. Adding a model without hints produces an incomplete model — visible and auditable. The schema becomes the single source of truth for both structure and semantics. Any system that reads the schema gets both, automatically, without further coordination.

For teams working at high model-addition velocity, this is the difference between a sustainable workflow and an accumulating maintenance burden.
