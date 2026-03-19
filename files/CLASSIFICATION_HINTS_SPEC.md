# PRISM Schema — `classificationHints` Specification

**Prepared by:** EDGAR Extraction & Mapping project
**Audience:** PRISM model creation group
**Date:** 2026-03-18
**Status:** Request for implementation

---

## 1. The Problem

The PRISM extraction pipeline uses an LLM (Claude) to classify incoming financial
product documents into a PRISM model before extracting field values.  The classifier
is given the list of model names and any description present in the schema and asked
to pick the best match.

**Two structural problems limit accuracy:**

**1a. Vocabulary mismatch.**  PRISM model names use an internal, normalised
taxonomy (`yieldEnhancementAutocallBarrierCoupon`).  The source documents — whether
424B2 SEC filings, bank term sheets, or ESMA Final Terms — use natural-language
product names that follow distinct, issuer-specific conventions:

> *"Auto Callable Contingent Interest Notes Linked to the S&P 500 Index"*
> *"Autocall Barrier Reverse Convertible on Nestlé AG"*
> *"Conditional Coupon Notes with Knock-In Risk — Quarterly Review"*
> *"Autocall Phoenix Note — Memory Coupon — 60% Barrier"*

None of these phrases appear in PRISM model names or their current descriptions.
The LLM has no explicit bridge.

**1b. Schema coverage gaps.**  The current schema has 9 models.  The operational
product universe contains additional types (e.g. `participationBufferDigital`,
`yieldEnhancementAutocallBufferCoupon`) that do not exist in the schema.  Without
guidance, the classifier forces these into the nearest wrong model.

**The proposed solution** is a `classificationHints` block added to each model
entry in `prism-v1.schema.json`.  This block provides the vocabulary bridge the
classifier needs without embedding business logic in code.  As the schema grows,
the classifier automatically improves — no code changes required.

---

## 2. Proposed JSON Structure

Add `classificationHints` as a top-level sibling to `properties` and `description`
within each model's `oneOf` entry:

```json
{
  "description": "Reverse convertible where the downside risk is activated if the barrier is breached. Supports multiple coupon types and includes an autocall feature.",
  "classificationHints": {
    "requiredFeatures": ["autocall", "barrier"],
    "optionalFeatures": ["contingentCoupon", "memoryCoupon", "phoenixCoupon"],
    "excludedFeatures": ["buffer", "digitalPayoff", "capitalProtection"],
    "productNamePatterns": [
      "Auto Call.*Contingent Interest",
      "Autocall.*Barrier",
      "Conditional Coupon.*Knock.In",
      "Phoenix.*Barrier.*Autocall",
      "Memory Coupon.*Autocall"
    ],
    "marketTerminology": {
      "en": ["auto callable contingent interest note", "autocall barrier reverse convertible", "phoenix note with barrier", "conditional coupon note with knock-in"],
      "de": ["Autocall Barrier Reverse Convertible", "Bedingte Coupon Note mit Barrier", "Phoenix Autocall Zertifikat"],
      "fr": ["note autocallable à coupon conditionnel", "reverse convertible autocall avec barrière"]
    },
    "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA", "pricingSupplement"],
    "disambiguationNotes": "Distinguish from yieldEnhancementBarrierCoupon (no autocall) and yieldEnhancementAutocallBufferCoupon (buffer instead of hard barrier). Key test: does downside protection use a hard knock-in barrier or a buffer/soft protection level?"
  },
  "properties": { ... }
}
```

---

## 3. Field Definitions

### `requiredFeatures` (array of strings)
Structural features that **must** be present for this model to apply.  These are
internal PRISM feature identifiers, not natural-language terms.

**Canonical feature identifiers (proposed):**

| Identifier | Meaning |
|---|---|
| `autocall` | Product can be called early by the issuer if a level is met |
| `barrier` | Hard knock-in barrier — full downside below a threshold |
| `buffer` | Soft buffer — absorbs the first N% of loss |
| `capitalProtection` | Principal fully or partially protected at maturity |
| `contingentCoupon` | Coupon paid only if underlying is at/above an observation level |
| `memoryCoupon` | Missed coupons are paid retrospectively if condition is later met |
| `phoenixCoupon` | Variant of memory coupon with per-period memory |
| `digitalPayoff` | Binary / fixed payoff (either X or 0) |
| `participationUpside` | Leveraged or 1:1 participation in upside above a level |
| `knockOutForward` | Forward with scheduled exchanges and a knock-out level |
| `fixedCoupon` | Unconditional fixed-rate coupon |
| `floatingCoupon` | Coupon linked to a floating rate (SOFR, EURIBOR, etc.) |
| `basketUnderlying` | Product references a basket of 2+ underlyings |
| `worstOf` | Payoff determined by worst-performing underlying in the basket |
| `bestOf` | Payoff determined by best-performing underlying in the basket |

### `optionalFeatures` (array of strings)
Features from the same list that **may** be present but are not required.

### `excludedFeatures` (array of strings)
Features whose presence indicates this model does **not** apply.  Used to disambiguate
between similar models.  Example: `yieldEnhancementAutocallBarrierCoupon` excludes
`buffer` (that would be the Buffer variant).

### `productNamePatterns` (array of regex strings)
Regular-expression patterns that match typical product title strings verbatim or
with minor variation.  These are matched case-insensitively against the first
paragraph of any document.  A match raises the prior probability for this model
before the full LLM classification runs.

Write patterns that are:
- Specific enough to distinguish from sibling models
- Flexible enough to handle issuer-specific wording (use `.*` between key terms)
- Anchored on the most distinctive word combination, not the whole title

**Examples:**
```
"Auto.?Call.*Contingent Interest"      → matches "Auto Callable Contingent Interest..."
"Barrier.*Reverse Convertible"         → matches "Barrier Reverse Convertible..."
"Knock.?In.*Coupon"                    → matches "Knock-In Coupon Note..."
"Phoenix.*Memory"                      → matches "Phoenix Memory Coupon Note"
```

### `marketTerminology.{lang}` (dict of language → array of strings)
Human-readable product name synonyms in each language.  Used both as classifier
guidance and as documentation for the model creation group.

Priority languages for the current pipeline:
- `en` — US (SEC 424B2, term sheets from US banks)
- `de` — Germany/Switzerland (bank term sheets, Termblatt)
- `fr` — France/Switzerland (term sheets, Fiches Techniques)
- `it` — Italy/Switzerland
- `es` — Spain

Even a partial list (English only) provides significant benefit.  Add other languages
as the pipeline scope expands.

### `documentFormats` (array of strings)
Document types for which this model is relevant.  Supported values:

| Value | Description |
|---|---|
| `424B2` | SEC 424B2 filing (US structured product pricing supplement) |
| `termSheet` | Generic bank term sheet (no fixed format) |
| `finalTerms_ESMA` | ESMA-compliant Final Terms (EU regulatory format) |
| `pricingSupplement` | Pricing supplement attached to a base prospectus |
| `kiid` | Key Investor Information Document (pre-PRIIPs) |
| `kid_priips` | Key Information Document (PRIIPs regulation) |
| `indicativeTermSheet` | Indicative / pre-deal term sheet |

This field allows the classifier to adjust its prior based on the source document
type — a `404B2` document will never be an ESMA Final Terms, so models marked
exclusively for `finalTerms_ESMA` can be deprioritised.

### `disambiguationNotes` (string)
Free-text guidance specifically for cases where two models are easily confused.
Write from the perspective of someone who has already identified the product family
and needs to pick between two specific models.

**Format:** "Distinguish from [model X] ([reason]). Key test: [decisive question]."

---

## 4. Example: All 9 Current Models Annotated

Below is a proposed `classificationHints` for each current model.
This is a starting point — the model creation group should refine based on expert knowledge.

### `yieldEnhancementCoupon`
```json
"classificationHints": {
  "requiredFeatures": ["fixedCoupon"],
  "optionalFeatures": [],
  "excludedFeatures": ["autocall", "barrier", "buffer"],
  "productNamePatterns": [
    "Fixed Coupon Note",
    "Reverse Convertible.*Fixed",
    "Capital at Risk.*Fixed Coupon"
  ],
  "marketTerminology": {
    "en": ["fixed coupon note", "reverse convertible with fixed coupon", "yield enhancement note"]
  },
  "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA"],
  "disambiguationNotes": "Simplest yield enhancement model — no barrier, no autocall. Distinguish from yieldEnhancementBarrierCoupon (adds barrier) and yieldEnhancementAutocallCoupon (adds autocall). Use when the product pays a fixed unconditional coupon with downside risk at maturity only."
}
```

### `yieldEnhancementBarrierCoupon`
```json
"classificationHints": {
  "requiredFeatures": ["barrier"],
  "optionalFeatures": ["contingentCoupon", "fixedCoupon"],
  "excludedFeatures": ["autocall", "buffer"],
  "productNamePatterns": [
    "Barrier Reverse Convertible",
    "BRC",
    "Knock.?In.*Reverse Convertible",
    "Contingent.*Interest.*Barrier",
    "(Reverse Convertible|RC).*Barrier"
  ],
  "marketTerminology": {
    "en": ["barrier reverse convertible", "knock-in reverse convertible", "contingent coupon barrier note"],
    "de": ["Barrier Reverse Convertible", "Knock-In Reverse Convertible", "BRC"]
  },
  "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA"],
  "disambiguationNotes": "Has a hard knock-in barrier — no autocall. Distinguish from yieldEnhancementAutocallBarrierCoupon (adds autocall) and yieldEnhancementAutocallBufferCoupon (buffer not barrier). Key test: is there an early redemption / autocall observation schedule?"
}
```

### `yieldEnhancementAutocallBarrierCoupon`
```json
"classificationHints": {
  "requiredFeatures": ["autocall", "barrier"],
  "optionalFeatures": ["contingentCoupon", "memoryCoupon", "phoenixCoupon"],
  "excludedFeatures": ["buffer", "digitalPayoff", "capitalProtection"],
  "productNamePatterns": [
    "Auto.?Call.*Contingent Interest",
    "Autocall.*Barrier",
    "Conditional Coupon.*Knock.?In",
    "Phoenix.*Barrier.*Autocall",
    "Memory Coupon.*Autocall.*Barrier"
  ],
  "marketTerminology": {
    "en": ["auto callable contingent interest note", "autocall barrier reverse convertible", "phoenix note with knock-in barrier", "conditional coupon autocall note"],
    "de": ["Autocall Barrier Reverse Convertible", "Bedingte Coupon Note mit Barrier und Autocall"]
  },
  "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA"],
  "disambiguationNotes": "Most common US structured product type. Has BOTH autocall AND hard barrier. Distinguish from yieldEnhancementBarrierCoupon (no autocall) and yieldEnhancementAutocallBufferCoupon (buffer instead of barrier). Key test: is the downside protection a hard knock-in level (full loss if breached) or a soft buffer (absorbs first N% of loss)?"
}
```

### `yieldEnhancementAutocallCoupon`
```json
"classificationHints": {
  "requiredFeatures": ["autocall", "contingentCoupon"],
  "optionalFeatures": ["fixedCoupon"],
  "excludedFeatures": ["barrier", "buffer"],
  "productNamePatterns": [
    "Autocall.*Coupon.*No Barrier",
    "Auto.?Call.*Note.*without.*Barrier",
    "Step.?Down Autocall"
  ],
  "marketTerminology": {
    "en": ["autocall coupon note without barrier", "stepper autocall", "step-down autocall note"]
  },
  "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA"],
  "disambiguationNotes": "Has autocall but NO barrier — downside risk is the full drop from strike at maturity, not triggered by an intraday barrier breach. Rarer than the barrier variant."
}
```

### `yieldEnhancementAutocall`
```json
"classificationHints": {
  "requiredFeatures": ["autocall"],
  "optionalFeatures": [],
  "excludedFeatures": ["barrier", "buffer", "contingentCoupon", "fixedCoupon"],
  "productNamePatterns": [
    "Autocall.*No Coupon",
    "Auto.?Callable.*Capital at Risk",
    "Pure Autocall"
  ],
  "marketTerminology": {
    "en": ["autocall without coupon", "pure autocall note", "capital-at-risk autocall"]
  },
  "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA"],
  "disambiguationNotes": "Autocall structure with NO coupon component. Distinguish from all other yieldEnhancement* models which include a coupon."
}
```

### `forwardKoStripEquity`
```json
"classificationHints": {
  "requiredFeatures": ["knockOutForward"],
  "optionalFeatures": [],
  "excludedFeatures": ["autocall", "barrier", "contingentCoupon"],
  "productNamePatterns": [
    "Accum[ue]lator",
    "Decum[ue]lator",
    "Knock.?Out Forward",
    "Daily Accrual.*Knock.?Out",
    "Share Accumulation"
  ],
  "marketTerminology": {
    "en": ["accumulator", "decumulator", "knock-out forward strip", "daily accrual note"],
    "de": ["Akkumulator", "Dekumulator", "Knock-out Forward Strip"],
    "zh": ["累计期权", "鲨鱼鳍期权"]
  },
  "documentFormats": ["424B2", "termSheet", "finalTerms_ESMA"],
  "disambiguationNotes": "Scheduled series of forward transactions with a knock-out level. Often known as 'accumulators' or 'decumulators'. Completely different payoff family from reverse convertibles."
}
```

### `equityShare`, `index`, `depositaryReceipt`
```json
"classificationHints": {
  "requiredFeatures": [],
  "optionalFeatures": [],
  "excludedFeatures": ["autocall", "barrier", "contingentCoupon", "knockOutForward"],
  "productNamePatterns": ["(ordinary|common|preferred) share[s]?", "equity share"],
  "marketTerminology": { "en": ["ordinary share", "common stock", "preferred stock"] },
  "documentFormats": ["424B2"],
  "disambiguationNotes": "Use only for plain equity instruments — no structured payoff."
}
```
*(Similar minimal hints for `index` and `depositaryReceipt`.)*

---

## 5. Models to Add (Confirmed Gaps)

The following models are referenced in the CUSIP mapping but absent from the schema.
Classification will return `unknown` for these products until they are added.

### `yieldEnhancementAutocallBufferCoupon` *(high priority)*
```json
"classificationHints": {
  "requiredFeatures": ["autocall", "buffer", "contingentCoupon"],
  "optionalFeatures": [],
  "excludedFeatures": ["barrier"],
  "productNamePatterns": [
    "Autocall.*Buffer",
    "Auto.?Call.*Soft Protection",
    "Contingent.*Coupon.*Buffer",
    "Capital Buffer.*Autocall"
  ],
  "marketTerminology": {
    "en": ["autocall buffer note", "autocall with soft protection", "buffer autocall contingent coupon"]
  },
  "disambiguationNotes": "Key distinction from yieldEnhancementAutocallBarrierCoupon: a buffer absorbs the first N% of loss (investor loses only when decline exceeds buffer). A barrier activates full downside once breached. Check for language like 'buffer amount', 'soft protection level', 'you will lose 1% for every 1% decline beyond the buffer'."
}
```

### `participationBufferDigital` *(high priority)*
```json
"classificationHints": {
  "requiredFeatures": ["participationUpside", "buffer", "digitalPayoff"],
  "optionalFeatures": [],
  "excludedFeatures": ["autocall", "barrier", "contingentCoupon"],
  "productNamePatterns": [
    "Digital.*Buffer",
    "Participation.*Buffer.*Digital",
    "Fixed Return.*Buffer",
    "Capital Buffer.*Digital"
  ],
  "marketTerminology": {
    "en": ["digital buffer note", "participation digital note with buffer", "fixed return buffer note"]
  },
  "disambiguationNotes": "Completely different family from yield enhancement (reverse convertible) products. Key signals: 'digital return', 'fixed return of X% if index above strike', 'buffer of Y% on the downside', NO coupon payments. Misclassified as yieldEnhancementBarrierCoupon if hints are not present."
}
```

---

## 6. How the Classifier Uses `classificationHints`

The extraction pipeline (`backend/classify/classifier.py`) already supports dynamic
loading of model metadata from the schema.  Once `classificationHints` is present,
the classifier will:

1. **Stage 1 (cover page):** Build a feature-matching table from `classificationHints`
   and include it in the classification prompt alongside model descriptions.

2. **Keyword pre-filter:** Test `productNamePatterns` (regex) against the document
   title before the LLM call.  A pattern match becomes a strong prior (+0.20 weight
   on confidence).

3. **Language-aware hints:** When the source document language is detected (via the
   filing's metadata or a simple heuristic), the relevant `marketTerminology` list
   is included in the prompt.

4. **Disambiguation:** `disambiguationNotes` is injected when two models both
   score ≥ 0.50 in stage 1, to help the stage-2 targeted pass make the final call.

5. **Dynamic `excludedFeatures` check:** If an `excludedFeature` keyword (mapped
   to natural-language terms) appears prominently on the cover page, the corresponding
   models are deprioritised before the LLM call.

---

## 7. Forward Compatibility

The `classificationHints` design is intentionally document-format agnostic:

- **EDGAR 424B2** (current): uses `productNamePatterns` + `marketTerminology.en`
- **Bank term sheets**: same patterns; language detection triggers non-English hints
- **ESMA Final Terms**: document structure differs (product name appears in a fixed
  field rather than a narrative title) — add a `finalTerms_ESMA` section to
  `marketTerminology` with the exact field labels used in European Final Terms
  (e.g. "Descrizione dell'Emissione", "Produktbezeichnung")
- **PRIIPs KID**: product name is in a structured table; `productNamePatterns` still
  applies, augmented with label-specific patterns

No code changes are required when new document formats are added — only schema
annotation updates.

---

## 8. Delivery Request

Please provide `classificationHints` for:

1. All 9 existing models (using the examples in Section 4 as a starting point,
   refined by your product expertise)
2. `yieldEnhancementAutocallBufferCoupon` (Section 5)
3. `participationBufferDigital` (Section 5)
4. Any additional models you are planning to add to the schema

**Preferred format:** updated `prism-v1.schema.json` with `classificationHints`
inserted at the appropriate position in each `oneOf` entry.

**Fallback format:** a separate JSON file `classificationHints.json` with
`{ "modelName": { ...hints... } }` structure that can be merged at load time.

---

*Questions or clarifications: contact the EDGAR Extraction & Mapping project.*
