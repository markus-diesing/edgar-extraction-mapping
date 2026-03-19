# Plan: Section-by-Section Extraction Refactor

*Status: Planning — not yet implemented*
*Author: Architecture session 2026-03-18*
*Based on: Motive AI insight #3 — "section-by-section extraction beats one big call"*

---

## Section 1: Architecture Overview

### Current State

`extract_filing()` in `backend/extract/extractor.py` makes a single Anthropic tool-call per filing:

- Sends the **full resolved schema** for the classified model (up to several thousand tokens of JSON Schema)
- Sends **up to 120,000 characters** of stripped filing text (`config.MAX_FILING_CHARS = 120_000`)
- Instructs Claude to populate the entire PRISM object in one response
- Receives a single tool-call result with all fields: `prism_data`, `_confidence`, `_excerpts`

**Known problems with the single-call approach:**

1. With 120K chars of filing text plus the full schema, the context is large and unfocused — Claude must locate all fields simultaneously across a dense, heterogeneous document.
2. The system prompt and user prompt are generic: no section-specific guidance about where to look, what synonyms to expect, or what edge cases apply.
3. Non-applicable sections (e.g., `autocall.*` fields for a product with no autocall feature) consume prompt tokens and can produce hallucinated values rather than null.
4. Current observed fill rate: 40–55% across UBS, Citigroup, JPMorgan. Motive AI reached ~99% accuracy with the section-by-section approach.

### Target State

Replace the single large call with 6–8 focused calls, one per **section group**, each receiving:

- Only the relevant sub-schema (the properties for that section group)
- Only the relevant filing text slice (the portion of the document most likely to contain those fields)
- A section-specific system prompt that explains terminology, synonyms, and where to look

The results of all section calls are merged into a single `ExtractionResultData` object before being written to the database — the DB schema, API, and UI are unchanged.

The refactor is controlled by a feature flag (`config.SECTIONED_EXTRACTION = False` initially), allowing both strategies to run in parallel for A/B comparison.

### Section Groups

The following section groups are defined based on the top-level properties used across all current PRISM models (derived from `prism-v1.schema.json`):

| Section Group Name | Schema Keys Covered | Filing Content Target |
|---|---|---|
| `identifiers` | `identifiers.*` | Cover page: CUSIP, ISIN, ticker, product name |
| `product_generic` | `structuredProductsGeneric.*`, `funding.*`, `downsideRisk.*` | Key terms table: issue date, maturity, strike, denomination, currency |
| `underlying_terms` | `underlyingTerms.*`, `underlyings.*` | Underlying section: index names, initial/final fixing dates, weights |
| `barrier` | `barrier.*` | Barrier/trigger section: barrier level, observation type, knock-in terms |
| `autocall` | `autocall.*` | Autocall/early redemption section: call schedule, call level, call payment |
| `coupon` | `coupon.*` | Coupon/interest section: coupon rate, frequency, contingent conditions, barrier |
| `settlement` | Settlement fields within `structuredProductsGeneric` | Settlement section: cash vs physical, settlement currency, settlement date |
| `parties` | `parties.*` | Legal/parties section: issuer LEI, calculation agent, guarantor, market maker |

### Which Models Use Which Section Groups

| PRISM Model | identifiers | product_generic | underlying_terms | barrier | autocall | coupon | parties |
|---|---|---|---|---|---|---|---|
| `yieldEnhancementCoupon` | Y | Y | Y | — | — | Y | Y |
| `yieldEnhancementBarrierCoupon` | Y | Y | Y | Y | — | Y | Y |
| `yieldEnhancementAutocallCoupon` | Y | Y | Y | — | Y | Y | Y |
| `yieldEnhancementAutocallBarrierCoupon` | Y | Y | Y | Y | Y | Y | Y |
| `yieldEnhancementAutocall` | Y | Y | Y | — | Y | — | Y |
| `forwardKoStripEquity` | Y | Y* | Y | — | — | — | Y |
| `equityShare` | Y | — | — | — | — | — | Y |
| `index` | Y | — | — | — | — | — | Y |
| `depositaryReceipt` | Y | — | — | — | — | — | Y |

*`forwardKoStripEquity` uses `otcDerivativesGeneric` and `equityForward` instead of `structuredProductsGeneric`; these map to `product_generic` for routing purposes.

---

## Section 2: Required Code Changes

### `backend/extract/extractor.py`

**New function `extract_filing_sectioned(filing_id: str) -> ExtractionResultData`**

This is the main entry point when `config.SECTIONED_EXTRACTION = True`. It orchestrates all section calls and merges results.

Steps:
1. Load filing and resolve `model_name`, `issuer_name`, `raw_html_path` (same as current `extract_filing()` lines 286–294).
2. Call `section_router.get_sections_for_model(model_name)` to get the list of `SectionSpec` objects applicable to this model.
3. For each `SectionSpec`:
   a. Extract the sub-schema for that section (new helper `_extract_section_schema(model_schema, section_spec)`).
   b. Locate the relevant filing text slice (new helper `_slice_filing_text(full_text, section_spec)`).
   c. Build a section-specific tool definition (reuse `_build_extraction_tool()` but with the sub-schema).
   d. Build a section-specific user prompt (new helper `_build_section_prompt()`).
   e. Make the Anthropic API call, log usage with `call_type=f"extract_{section_spec.name}"`.
   f. Parse result with `_parse_tool_response()` (unchanged).
4. Merge all section results with new function `_merge_section_results(section_results: list[dict])`.
5. Run the same flatten + enum validation + field coverage logic as current `extract_filing()`.
6. Persist to DB with a new column `extraction_mode = "sectioned"` in `ExtractionResult`.

**Modified `extract_filing(filing_id: str)`**

Add a feature-flag branch near the top (after loading the filing):

```python
if config.SECTIONED_EXTRACTION:
    return extract_filing_sectioned(filing_id)
```

The rest of the existing function is unchanged — it continues to be the fallback path.

**New helper `_extract_section_schema(model_schema: dict, section_spec: SectionSpec) -> dict`**

Returns a JSON-Schema object containing only the properties listed in `section_spec.schema_keys`. Example: for the `barrier` section, returns `{"type": "object", "properties": {"barrier": model_schema["properties"]["barrier"]}, "required": [...]}`.

**New helper `_slice_filing_text(full_text: str, section_spec: SectionSpec) -> str`**

Uses the `section_spec.search_headers` list to locate the relevant portion of the filing text (same regex window approach as `classifier._extract_targeted_sections()` in `backend/classify/classifier.py` lines 228–269). Returns a slice of filing text bounded by heuristic start/end positions, capped at `section_spec.max_chars`.

**New helper `_build_section_prompt(model_name, section_name, section_schema_json, filing_slice, hints_block) -> str`**

Similar to existing `_build_extraction_prompt()` (lines 250–273) but:
- States which section is being extracted
- Includes section-specific instructions (from `SectionSpec.system_note`)
- Uses the section filing slice rather than truncated full text

**New helper `_merge_section_results(section_results: list[tuple[str, dict, dict, dict]]) -> tuple[dict, dict, dict]`**

Takes a list of `(section_name, prism_data, confidence_map, excerpts_map)` tuples. Merges into a single `(prism_data, confidence_map, excerpts_map)` triple using conflict resolution rules defined in Section 5 below.

### `backend/extract/section_router.py` — NEW FILE

This module owns the mapping from model name to section list, and from section to schema keys and search headers.

```python
from dataclasses import dataclass, field

@dataclass
class SectionSpec:
    name: str                   # e.g. "barrier"
    schema_keys: list[str]      # top-level PRISM property names, e.g. ["barrier"]
    search_headers: list[str]   # filing section headers to anchor text slice
    max_chars: int              # max filing text chars for this section
    system_note: str            # appended to section system prompt
    required_for: set[str]      # model names that require this section

MODEL_SECTIONS: dict[str, list[str]] = { ... }  # model → list of section names

SECTION_SPECS: dict[str, SectionSpec] = { ... }  # section name → SectionSpec

def get_sections_for_model(model_name: str) -> list[SectionSpec]:
    """Return ordered list of SectionSpec applicable to this model."""
```

The full contents of `SECTION_SPECS` are specified in Section 3 of this document.

### `backend/config.py`

Add the following constants after the existing threshold block (current line 49):

```python
# Sectioned extraction feature flag
SECTIONED_EXTRACTION: bool = False        # set True to enable section-by-section mode

# Per-section text window sizes (chars of stripped filing text per section call)
SECTION_MAX_CHARS_IDENTIFIERS    = 8_000
SECTION_MAX_CHARS_PRODUCT        = 15_000
SECTION_MAX_CHARS_UNDERLYING     = 12_000
SECTION_MAX_CHARS_BARRIER        = 10_000
SECTION_MAX_CHARS_AUTOCALL       = 10_000
SECTION_MAX_CHARS_COUPON         = 10_000
SECTION_MAX_CHARS_SETTLEMENT     = 8_000
SECTION_MAX_CHARS_PARTIES        = 8_000

# Minimum confidence delta to prefer a section result over a prior result for same field
SECTION_MERGE_CONFIDENCE_DELTA   = 0.15
```

### `backend/database.py`

**`ExtractionResult` table: add one new column**

In the `ExtractionResult` class (current lines 93–107), add:

```python
extraction_mode = Column(String, default="single")  # "single" | "sectioned"
```

Add a migration entry to `_migrate()` (current lines 191–207):

```python
("extraction_results", "extraction_mode", "TEXT"),
```

No change to `FieldResult`, `Filing`, or other tables. The sectioned mode stores the same per-field rows — only the summary row is tagged differently.

**Optional: `FieldResult` table: add section provenance column**

For debugging, it is useful to know which section call produced each field. This is low priority but can be added:

```python
section_name = Column(String)   # e.g. "barrier", "coupon", "identifiers"
```

With migration: `("field_results", "section_name", "TEXT")`.

### `backend/extract/router.py`

No API contract changes required. The `POST /api/extract/{filing_id}` endpoint calls `extract_filing(filing_id)` which internally branches on the feature flag — the response shape is identical.

The `ExtractionSummary` response model does not need a new field for `extraction_mode` in the initial implementation (it can be added later as a diagnostic field if needed).

### `files/issuer_extraction_hints.json`

The existing hints file already provides per-issuer `section_headings` and per-field `synonyms`. For the sectioned extraction mode, add a new optional key `section_hints` at the issuer level:

```json
{
  "issuers": {
    "ubs": {
      "section_hints": {
        "barrier": {
          "anchor_phrases": ["Barrier Level", "Knock-In Level", "Trigger Level"],
          "typical_page_range": "3-5"
        },
        "autocall": {
          "anchor_phrases": ["Autocall Level", "Early Redemption", "Call Level"]
        }
      }
    }
  }
}
```

The `section_router.py` module will check the hints file (already loaded as `_EXTRACTION_HINTS` in `extractor.py`) for issuer-specific anchor overrides before falling back to the default `search_headers` in `SectionSpec`.

---

## Section 3: Section Prompt Templates

### `identifiers` Section

**Fields covered (dot-paths):**
- `identifiers.cusip`, `identifiers.isin`, `identifiers.valoren`, `identifiers.wkn`, `identifiers.figi`
- `structuredProductsGeneric.productName`, `structuredProductsGeneric.productType`

**Search headers for text slice:**
```
["CUSIP", "ISIN", "VALOREN", "WKN", "PRODUCT NAME", "SECURITY NAME", "PRICING SUPPLEMENT"]
```

**System prompt emphasis:**
> "You are extracting identifying codes and the product name from the cover page of a 424B2 SEC filing. Focus on the first 200 lines of the document. CUSIP is always 9 characters (digits and letters). ISIN is 12 characters starting with a country code. The product name is the full legal title as printed, typically in bold on page 1. Do not confuse the CUSIP of the underlying index or stock with the CUSIP of this structured note."

**Section boundary detection:**
The cover page is almost always within the first 8,000 characters of stripped text. No special header detection needed — slice `full_text[:SECTION_MAX_CHARS_IDENTIFIERS]`.

---

### `product_generic` Section

**Fields covered (dot-paths):**
- `structuredProductsGeneric.issuanceDate`, `structuredProductsGeneric.maturityDate`
- `structuredProductsGeneric.denominationCurrency`, `structuredProductsGeneric.denominationAmount`
- `structuredProductsGeneric.issuePrice`, `structuredProductsGeneric.redemptionCurrency`
- `funding.fundingType`, `funding.notionalAmount`
- `downsideRisk.downsideType`, `downsideRisk.strikeLevel`, `downsideRisk.strikeLevelRelative`

**Search headers for text slice:**
```
["ISSUE DATE", "PRICING DATE", "MATURITY DATE", "FINAL VALUATION DATE",
 "DENOMINATION", "AGGREGATE PRINCIPAL AMOUNT", "ISSUE PRICE",
 "STRIKE", "INITIAL LEVEL", "FINAL LEVEL", "SETTLEMENT AMOUNT",
 "ORIGINAL ISSUE DATE", "TRADE DATE"]
```

**System prompt emphasis:**
> "You are extracting product-level economic terms from the key terms table of a 424B2 structured note filing. The key terms table typically appears within the first 15 pages and is formatted as a two-column table (Term | Value). Strike level: output as a decimal (1.00 = 100% of initial level). Maturity date and issue date are distinct from the underlying observation/fixing dates — do not confuse them. Notional amount is the total aggregate principal, not the face value per unit."

**Section boundary detection:**
Use the first occurrence of any search header as the start anchor, extended 15,000 chars forward. Cap at `SECTION_MAX_CHARS_PRODUCT`.

---

### `underlying_terms` Section

**Fields covered (dot-paths):**
- `underlyingTerms.initialValuationDate`, `underlyingTerms.finalValuationDate`
- `underlyingTerms.basketType`, `underlyingTerms.observationSchedule`
- `underlyings.U1.name`, `underlyings.U1.bloombergTicker`, `underlyings.U1.initialLevel`
- `underlyings.U1.weight` (and U2, U3 for baskets)

**Search headers for text slice:**
```
["UNDERLYING", "BASKET", "INDEX COMPONENT", "INITIAL LEVEL", "INITIAL CLOSING LEVEL",
 "INITIAL VALUATION DATE", "FINAL VALUATION DATE", "OBSERVATION DATE",
 "REFERENCE ASSET", "LINKED TO"]
```

**System prompt emphasis:**
> "You are extracting underlying asset information from a structured note prospectus. For single-underlying products, use key 'U1'. For baskets, use 'U1', 'U2', 'U3', etc. in order of appearance. Bloomberg ticker format: 'SPX Index', 'RTY Index', 'NDX Index'. Initial level is the closing price or index level on the initial valuation date — not a strike percentage. If weights are not stated, output null (do not assume equal weighting). Do not confuse the underlying's valuation dates with the note's maturity date."

**Section boundary detection:**
Locate the underlying section using search headers; collect a window of `SECTION_MAX_CHARS_UNDERLYING` chars. For basket products, the full basket table may span several pages — use a wider window.

---

### `barrier` Section

**Fields covered (dot-paths):**
- `barrier.triggerDetails.triggerLevelRelative`, `barrier.triggerDetails.triggerLevelAbsolute`
- `barrier.triggerDetails.triggerType` (enum: `"European"`, `"American"`, `"Closing"`)
- `barrier.triggerDetails.observationSchedule`
- `barrier.knockInTerms.*`

**Search headers for text slice:**
```
["BARRIER", "TRIGGER", "KNOCK-IN", "KNOCK IN", "TRIGGER LEVEL",
 "BARRIER LEVEL", "DOWNSIDE THRESHOLD", "PROTECTION LEVEL",
 "CONTINGENT PROTECTION", "CAPITAL AT RISK"]
```

**System prompt emphasis:**
> "You are extracting barrier/trigger terms from a structured note prospectus. triggerLevelRelative is a decimal: 0.60 means the barrier is 60% of the initial level (i.e. 40% downside protection). triggerType must be one of: 'European' (observed only at maturity), 'American' (observed continuously), or 'Closing' (observed at each scheduled close). Some filings call the barrier the 'Trigger', 'Knock-In Level', 'Protection Level', or 'Downside Threshold' — these are synonymous. If the filing states '60% barrier', output triggerLevelRelative = 0.60."

**Section boundary detection:**
Any occurrence of BARRIER or TRIGGER in the text anchors the slice. The barrier terms are typically in a compact paragraph or table row; `SECTION_MAX_CHARS_BARRIER = 10_000` chars is sufficient.

---

### `autocall` Section

**Fields covered (dot-paths):**
- `autocall.callSchedule` (list/object of observation dates and call levels)
- `autocall.callLevelRelative`, `autocall.callLevelAbsolute`
- `autocall.callPayment`, `autocall.callObservationFrequency`
- `autocall.autocallType` (enum)

**Search headers for text slice:**
```
["AUTOCALL", "AUTO CALL", "AUTOMATIC REDEMPTION", "AUTOMATIC CALL",
 "EARLY REDEMPTION", "CALL DATE", "CALL LEVEL", "OBSERVATION DATE",
 "MEMORY COUPON", "ISSUER CALL"]
```

**System prompt emphasis:**
> "You are extracting autocall/early redemption terms from a structured note prospectus. The call schedule is a list of observation dates paired with call levels. callLevelRelative is a decimal: 1.00 means the call triggers when the underlying closes at or above 100% of its initial level. Many filings present the call schedule as a table — extract all rows. callPayment is the amount paid to the holder on early call (often stated as principal + accrued coupon or a fixed premium). Do not confuse the autocall observation dates with coupon payment dates."

**Section boundary detection:**
AUTOCALL or EARLY REDEMPTION headers are reliable anchors. The call schedule table may be long — use `SECTION_MAX_CHARS_AUTOCALL = 10_000` and capture the full table if possible.

---

### `coupon` Section

**Fields covered (dot-paths):**
- `coupon.couponType` (enum: `"fixed"`, `"contingent"`, `"floating"`, etc.)
- `coupon.couponRate`, `coupon.couponBarrierRelative`, `coupon.couponBarrierAbsolute`
- `coupon.couponFrequency` (enum: `"Monthly"`, `"Quarterly"`, `"SemiAnnual"`, `"Annual"`)
- `coupon.paymentSchedule`, `coupon.memoryCoupon`

**Search headers for text slice:**
```
["COUPON", "CONTINGENT INTEREST", "CONDITIONAL COUPON", "INTEREST RATE",
 "COUPON BARRIER", "INTEREST BARRIER", "PAYMENT DATE", "INTEREST PAYMENT",
 "CONTINGENT COUPON RATE", "COUPON OBSERVATION"]
```

**System prompt emphasis:**
> "You are extracting coupon/interest terms from a structured note prospectus. couponRate is a decimal (0.08 = 8% per annum). couponFrequency must be one of: 'Monthly', 'Quarterly', 'SemiAnnual', 'Annual'. couponBarrierRelative is a decimal: if the filing states 'the coupon is paid if the underlying closes at or above 70% of initial level', output 0.70. JPMorgan filings often call the coupon barrier the 'Interest Barrier'. Memory coupon: if missed coupons can be recovered in a later period, set memoryCoupon = true. Do not confuse the coupon payment frequency with the coupon observation/determination frequency."

**Section boundary detection:**
COUPON or CONTINGENT INTEREST anchors the slice. For products with complex coupon schedules, capture extra context.

---

### `parties` Section

**Fields covered (dot-paths):**
- `parties.issuer.legalName`, `parties.issuer.lei`
- `parties.calculationAgent.legalName`, `parties.calculationAgent.lei`
- `parties.guarantor.legalName`, `parties.guarantor.lei`
- `parties.marketMaker.legalName`, `parties.marketMaker.lei`

**Search headers for text slice:**
```
["ISSUER", "GUARANTOR", "CALCULATION AGENT", "MARKET MAKER",
 "SELLING AGENT", "PAYING AGENT", "LEGAL ENTITY IDENTIFIER", "LEI"]
```

**System prompt emphasis:**
> "You are extracting party information from a structured note prospectus. Provide the LEI (20-character alphanumeric code, e.g. 'E57ODZWZ7FF32TWEFA76') when explicitly stated in the filing. If the LEI is not stated, provide the full legal entity name exactly as printed. The issuer is the entity that issues the notes (e.g. 'UBS AG', 'Citigroup Global Markets Holdings Inc.'). The guarantor is the parent entity that guarantees the notes — only present if explicitly stated. Do not confuse the calculation agent with the market maker."

**Section boundary detection:**
Party information is usually on the cover page or in a dedicated 'Parties' or 'Summary' section. Include both a cover page slice and any explicit party section later in the document.

---

## Section 4: Section Skipping Logic

### Mapping `payout_type_id` to Required Sections

This mapping lives in `backend/extract/section_router.py` as `MODEL_SECTIONS`:

```python
MODEL_SECTIONS: dict[str, list[str]] = {
    "yieldEnhancementCoupon": [
        "identifiers", "product_generic", "underlying_terms", "coupon", "parties"
    ],
    "yieldEnhancementBarrierCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "barrier", "coupon", "parties"
    ],
    "yieldEnhancementAutocallCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "autocall", "coupon", "parties"
    ],
    "yieldEnhancementAutocallBarrierCoupon": [
        "identifiers", "product_generic", "underlying_terms",
        "barrier", "autocall", "coupon", "parties"
    ],
    "yieldEnhancementAutocall": [
        "identifiers", "product_generic", "underlying_terms",
        "autocall", "parties"
    ],
    "forwardKoStripEquity": [
        "identifiers", "product_generic", "underlying_terms", "parties"
    ],
    "equityShare":       ["identifiers", "parties"],
    "index":             ["identifiers"],
    "depositaryReceipt": ["identifiers", "parties"],
}
```

The `get_sections_for_model(model_name)` function in `section_router.py` looks up this dict and returns the corresponding `SectionSpec` objects. Unrecognised model names fall back to all sections (safe default).

### Runtime Skipping

`extract_filing_sectioned()` skips sections dynamically if:

1. The model does not include the section in `MODEL_SECTIONS` — primary skip path.
2. The filing text slice for a section is shorter than 100 characters after stripping (section anchor not found in document) — log a warning at DEBUG level, do not make the API call.

For skip case 2, all fields in the section are recorded as `not_found=1`, `confidence_score=0.0`, with `source_excerpt=""`. This ensures all `descriptor_paths` are still covered in the merged result.

---

## Section 5: Result Merging

### Overview

After all section calls complete, `_merge_section_results()` combines them into a single `(prism_data, confidence_map, excerpts_map)` triple which is then fed into the existing `_flatten()` + field-building logic.

### Data Structure During Merge

Each section call returns a `SectionResult` (an intermediate named-tuple):

```python
from typing import NamedTuple

class SectionResult(NamedTuple):
    section_name: str
    prism_data: dict       # partial PRISM object (only fields for this section)
    confidence_map: dict   # {dot-path: float}
    excerpts_map: dict     # {dot-path: str}
```

### Conflict Resolution

If two sections extract the same field (possible in the overlap between `identifiers` and `product_generic` for fields like `structuredProductsGeneric.productName`):

1. **Higher confidence wins.** Compare `confidence_map[field_path]` across all sections that provided a non-null value. Keep the value with the higher confidence score.
2. **Minimum delta override.** Only replace the existing value if the challenger's confidence exceeds the existing confidence by at least `SECTION_MERGE_CONFIDENCE_DELTA = 0.15`. This prevents a slightly higher-confidence wrong value from evicting a good value.
3. **Log conflicts.** When a conflict is resolved, log at DEBUG level: `"Merge conflict on {field}: {old_section} ({old_conf:.2f}) vs {new_section} ({new_conf:.2f}) → kept {winner}"`.

```python
def _merge_section_results(
    section_results: list[SectionResult],
) -> tuple[dict, dict, dict]:
    merged_prism: dict = {}
    merged_conf: dict = {}
    merged_excr: dict = {}

    for result in section_results:
        flat: dict = {}
        _flatten(result.prism_data, "", flat, skip_keys={"model", "_confidence", "_excerpts"})
        for path, value in flat.items():
            if value is None:
                continue   # nulls never evict a prior value
            existing_conf = merged_conf.get(path, -1.0)
            new_conf = float(result.confidence_map.get(path, 0.5))
            if existing_conf < 0 or (new_conf - existing_conf) >= config.SECTION_MERGE_CONFIDENCE_DELTA:
                merged_prism = _deep_set(merged_prism, path, value)
                merged_conf[path] = new_conf
                merged_excr[path] = result.excerpts_map.get(path, "")

    return merged_prism, merged_conf, merged_excr
```

`_deep_set(d, dot_path, value)` is a new helper that reconstructs the nested dict structure from a dot-path. Needed because `_merge_section_results` works in flat space but `merged_prism` must be a nested dict for the downstream `_flatten()` call.

### Confidence Aggregation

After merging, the overall extraction confidence for the filing (used for future quality monitoring) is the mean of all non-null field confidences across all sections:

```python
mean_confidence = sum(merged_conf.values()) / len(merged_conf) if merged_conf else 0.0
```

This mean is not currently stored in a column, but it can be logged via `log.info()` for the A/B comparison phase.

### Excerpt Merging

Each field keeps the single excerpt from the winning section call (the one with the higher confidence, as chosen during conflict resolution). There is no concatenation of excerpts.

### API Usage Logging

Each section call is logged with `call_type = f"extract_{section_name}"` (e.g., `"extract_barrier"`, `"extract_coupon"`). This allows per-section token cost tracking in the `api_usage_log` table for the A/B comparison phase.

---

## Section 6: Migration Path

### Feature Flag

In `backend/config.py`, the new constant is:

```python
SECTIONED_EXTRACTION: bool = False
```

With `False` (default), `extract_filing()` runs the existing single-call path unchanged. No production behavior changes until the flag is flipped.

To enable sectioned extraction in a local session without changing `config.py`:
```bash
SECTIONED_EXTRACTION=true uvicorn main:app --reload --port 8000
```

The flag should be read with `bool(os.environ.get("SECTIONED_EXTRACTION", "false").lower() == "true")` or, more simply, left as a `bool` constant that is changed and committed when the team is ready.

### A/B Comparison Methodology

Run both modes on the same set of filings and compare field fill rates:

1. Select 10 filings across UBS and Citigroup (most consistent layouts; baseline fill rate 39–54%).
2. Run single-call extraction (`SECTIONED_EXTRACTION = False`). Record `fields_found / field_count` per filing.
3. Reset filings to `classified` status (via `POST /api/extract/{id}/reextract`).
4. Set `SECTIONED_EXTRACTION = True`. Re-run extraction on the same 10 filings.
5. Compare `fields_found`, mean `confidence_score`, and `validation_error` counts between the two runs.
6. Use the `api_usage_log` table to compare token costs per filing.

Success criteria for promoting sectioned extraction to the default:
- Fill rate improvement of at least 10 percentage points (e.g., 44% → 54%+)
- No increase in `schema_error` count (validation error rate must not worsen)
- Token cost per document must not exceed 1.8x the single-call cost (Motive AI paid ~$1.51 vs our expected ~$0.80 in single-call mode; the per-section approach adds overhead from multiple system prompts but reduces per-call context)

### Rollout Plan

**Phase 1 — UBS and Citigroup** (most consistent filing layouts)

These issuers have the most reliable section headings and key terms table structures. The `issuer_extraction_hints.json` agent has already generated per-issuer section heading lists for these issuers. Start here to validate the approach on the ~6 already-extracted filings.

**Phase 2 — JPMorgan Chase and JPMorgan Financial**

JPMorgan filings use "Interest Barrier" instead of "Coupon Barrier" and have a distinct key terms section structure. The existing hints cover this divergence. JPMorgan Financial has one known misclassification case (`46660MNU5` — `digitalBarrierNote`) which will remain a `needs_review` filing regardless of extraction mode.

**Phase 3 — Bank of Montreal and Goldman Sachs**

BMO's key terms section is known to be on lines 147–280 of their stripped text (per `RESEARCH_FINDINGS_AND_NEXT_STEPS.md §3.3 Insight 4`). The `underlying_terms` section slice needs a wider window for BMO basket products.

Goldman Sachs note: CUSIPs with prefix 40447C currently map to HSBC USA INC /MD/ in EDGAR (CUSIP prefix collision). Treat these as diagnostics only; the correctly identified Goldman CUSIPs (prefix 40058Q, 40058J) are the primary extraction targets.

**Phase 4 — Barclays and Wells Fargo**

Barclays uses 424B2 filings with a consistent key-terms table structure; classification results to date show `unknown` for several filings — investigate whether these are products outside the current 9-model schema (e.g., digital/barrier notes) or classification prompt issues.

Wells Fargo: three CUSIPs (95001DP95, 95001DPB0, 95001DPA2) are standard structured notes and behave similarly to JPMorgan. Two CUSIPs (95001HJH5, 95001HJJ1) are not in the original target set and are at `needs_review` / `unknown` — classify manually first to confirm product type.

**95001DP87 exception**: This CUSIP is a "Fixed Rate Callable Notes" (plain vanilla callable bond). It has no underlying index, no barrier, no autocall trigger. The `optional_redemption` dates in the filing are unconditional issuer call rights. This filing **cannot be correctly extracted** until a `fixedRateCallableNote` (or equivalent) model is added to `prism-v1.schema.json`. It should remain `ingested` status and be excluded from the Phase 4 extraction run. See Section 8.5 for schema gap details.

**Phase 5 — Default on**

Once Phase 1–4 show consistent improvement, flip `SECTIONED_EXTRACTION = True` as the committed default and remove the single-call path in a cleanup commit.

---

## Section 7: Effort Estimate and Task List

| # | Task | Effort | Owner |
|---|---|---|---|
| 1 | Create `backend/extract/section_router.py` with `SectionSpec` dataclass, `MODEL_SECTIONS` dict, `SECTION_SPECS` dict for all 8 section groups, and `get_sections_for_model()` function | 4 h | Dev |
| 2 | Add constants to `backend/config.py`: `SECTIONED_EXTRACTION`, `SECTION_MAX_CHARS_*`, `SECTION_MERGE_CONFIDENCE_DELTA` | 0.5 h | Dev |
| 3 | Add `extraction_mode` column to `ExtractionResult` in `backend/database.py` + migration entry | 0.5 h | Dev |
| 4 | Implement `_slice_filing_text()` in `extractor.py` — adapt the regex window logic from `classifier._extract_targeted_sections()` for per-section use | 2 h | Dev |
| 5 | Implement `_extract_section_schema()` in `extractor.py` — extract sub-schema for a given section's keys from the full resolved model schema | 1 h | Dev |
| 6 | Implement `_build_section_prompt()` in `extractor.py` — section-specific prompt builder | 1 h | Dev |
| 7 | Implement `_merge_section_results()` and `_deep_set()` helpers in `extractor.py` | 3 h | Dev |
| 8 | Implement `extract_filing_sectioned()` orchestrator function in `extractor.py` | 4 h | Dev |
| 9 | Add feature-flag branch to `extract_filing()` | 0.5 h | Dev |
| 10 | Write section system prompt notes for all 8 section groups (refine text in `SectionSpec.system_note`) | 2 h | Dev + domain expert |
| 11 | Add `section_hints` key support to `issuer_extraction_hints.json` schema and loader | 1 h | Dev |
| 12 | A/B comparison: run 10 UBS+Citigroup filings in both modes, record fill rates, document results | 2 h | Dev |
| 13 | Review A/B results, tune section window sizes and search headers based on actual filing behaviour | 3 h | Dev |
| 14 | Phase 1 sign-off: promote `SECTIONED_EXTRACTION = True` for UBS + Citigroup in config comment | 0.5 h | Dev |
| 15 | Phase 2–3: JPMorgan, BMO, Goldman Sachs — tune per-issuer section headers in hints file | 3 h | Dev |
| 16 | Flip `SECTIONED_EXTRACTION = True` as committed default; cleanup single-call path (after all phases pass) | 1 h | Dev |

**Total estimate: ~35 hours (~4.5 developer days)** *(updated from ~29 h to include Phase 4 Barclays/Wells Fargo tuning and Expert Settings UI)*

The highest-risk items are #7 (merge logic — needs careful testing with real conflicts) and #13 (tuning — the actual filing text varies more than expected). Plan a full sprint for this work rather than a hotfix.

---

## Section 8: Schema Validation — Section Group Integrity Under Growing Model Coverage

*Status: Analysis complete (2026-03-18) — based on `prism-v1.schema.json` schema inspection. Full PRISM wiki cross-check pending PAT access.*

The section groups were reviewed against the actual `$defs` structure in `prism-v1.schema.json` for ambiguity risks as PRISM's model coverage grows. Six concerns were identified; two require action before implementation begins (8.1 and 8.2); the rest are forward-looking notes.

---

### 8.1 — CRITICAL: `barrier` section must absorb `downsideRisk` (rename to `protection`)

**The problem:**
The plan currently places `downsideRisk.*` inside `product_generic` and `barrier.*` inside the `barrier` section. This is a logical inconsistency:

- In a **barrier product** (`yieldEnhancementBarrierCoupon`): the principal protection condition (`downsideRisk.strikeDetails`) is expressed in the filing alongside the knock-in barrier level (`barrier.triggerDetails`). Both appear in the same "BARRIER / TRIGGER" paragraph. Splitting them into different section calls means two Claude calls will both try to locate the same filing paragraph, wasting tokens and risking divergent results.

- When **buffer products** are added (`yieldEnhancementAutocallBufferCoupon`): the buffer level is modelled in `downsideRisk.strikeDetails` — NOT in `barrier.*` (no trigger object exists for buffer products). Filing language uses "BUFFER LEVEL", "BUFFER AMOUNT", "CONTINGENT PROTECTION", which shares terminology with barrier language. A separate `barrier` section call with `barrier.*` schema keys will find nothing for these products; the `product_generic` section call that currently owns `downsideRisk.*` will find the buffer level buried among the key terms table — sub-optimal for focused extraction.

**Recommended fix (pre-implementation):**
Rename the `barrier` section group to `protection` and merge `downsideRisk.*` into it:

```python
SectionSpec(
    name="protection",
    schema_keys=["barrier", "downsideRisk"],   # ← was: ["barrier"] only
    search_headers=[
        "BARRIER", "TRIGGER", "KNOCK-IN", "KNOCK IN", "TRIGGER LEVEL",
        "BARRIER LEVEL", "DOWNSIDE THRESHOLD", "PROTECTION LEVEL",
        "CONTINGENT PROTECTION", "CAPITAL AT RISK",
        "BUFFER", "BUFFER LEVEL", "BUFFER AMOUNT",   # ← new for buffer products
        "SOFT PROTECTION", "PARTIAL PROTECTION",      # ← new
        "STRIKE", "INITIAL LEVEL", "FINAL LEVEL",     # ← catch strike in same section
    ],
    ...
)
```

Remove `downsideRisk` from `product_generic`'s schema_keys. Update `MODEL_SECTIONS` for all models.

**Impact on existing models:** None — `downsideRisk.*` was already being extracted; it just moves to a better-targeted section call. The `product_generic` section becomes leaner (removing `downsideRisk.*` and shifting focus to dates/denomination/currency/settlement only).

---

### 8.2 — CRITICAL: `autocall` section must explicitly cover issuer optional redemption calls

**The problem:**
PRISM `$defs/autocall` models **performance-linked** early redemption (the autocall triggers when the underlying closes above a threshold). However, callable bonds (e.g., Wells Fargo "Fixed Rate Callable Notes") have **unconditional issuer discretion** calls at specified dates — no trigger condition on the underlying's performance.

Filing terminology overlaps significantly:
- Autocall: "CALL DATE", "CALL LEVEL", "EARLY REDEMPTION", "AUTOMATIC CALL"
- Callable bond: "OPTIONAL REDEMPTION DATES", "ISSUER'S OPTION", "REDEMPTION AT THE OPTION OF WELLS FARGO"

If a `fixedRateCallableNote` model is added to PRISM, both product types would trigger the `autocall` section's search headers and Claude would attempt to fill `autocall.autocallPayments[date].triggerDetails` for a callable bond — but there is no trigger condition to extract.

**Recommended fix:**
1. Add "OPTIONAL REDEMPTION", "OPTIONAL REDEMPTION DATES", "ISSUER'S OPTION", "REDEMPTION AT THE OPTION" to `autocall` search_headers now.
2. Add to `autocall` section system_note: *"If the filing describes unconditional issuer call rights (no performance-based trigger condition on the underlying), output `autocall.autocallPayments` using the call dates as keys, but set `triggerDetails` to null for each entry — this represents an issuer optional redemption. Do NOT fabricate trigger levels for unconditional calls."*
3. When a callable/fixed-rate bond model is added: create a separate `callable_redemption` section spec for it, so it does NOT share `product_generic` or `autocall` section calls with structured notes.

---

### 8.3 — `settlement` section is premature for current schema

The plan specifies a separate `settlement` section group covering "Settlement fields within `structuredProductsGeneric`". However, reviewing `$defs/structuredProductsGeneric`, `settlement` is a single `enum` field (`cashOrPhysical`, `physical`, `cash`) — not a rich sub-object.

**Assessment:** There is insufficient schema material to justify a dedicated `settlement` section call for current models. All settlement-related content fits within `product_generic`.

**Recommendation:** Retire the `settlement` section group from the plan for now. If `structuredProductsGeneric` gains richer settlement sub-fields (settlement currency, delivery instructions, physical delivery ratio) in a future schema revision, revisit.

**Impact on task list:** Task #1 (create `section_router.py`) becomes slightly simpler — 7 section groups instead of 8 for initial implementation.

---

### 8.4 — `forwardKoStripEquity` section routing needs a model-specific variant

`forwardKoStripEquity` uses `otcDerivativesGeneric` and `equityForward` (no `structuredProductsGeneric`). The `product_generic` section's search headers ("ISSUE DATE", "MATURITY DATE", "DENOMINATION", "AGGREGATE PRINCIPAL AMOUNT") will produce empty or poor slices for OTC accumulator/decumulator term sheets, which use different vocabulary ("EXPIRY DATE", "SETTLEMENT DATE", "TRADING SHARES", "KNOCK-OUT LEVEL").

**Recommendation (low priority):** When `forwardKoStripEquity` extraction is tested, add a `forwardKo_product` section spec variant in `section_router.py` with OTC-appropriate headers. For now, the fallback to full-document single-call mode is acceptable for this model type.

---

### 8.5 — Wells Fargo 95001DP87: schema gap — `fixedRateCallableNote`

CUSIP 95001DP87 is a "Fixed Rate Callable Notes" filing. Key characteristics:

- **Fixed coupon rate** (not contingent on any underlying performance)
- **No underlying index or equity** — no `underlyings.*`, no `underlyingTerms.*`
- **Optional Redemption Dates** — issuer may redeem early on scheduled dates at par (unconditional)
- **No barrier, no autocall trigger condition**

None of the 9 current PRISM models accommodate this product type. The classifier correctly cannot find a match and would return `unknown`.

**Schema gap to register with PRISM model creation group:**

| New model needed | Key schema blocks | Notes |
|---|---|---|
| `fixedRateCallableNote` | `identifiers`, `funding`, `coupon` (fixed), `structuredProductsGeneric` (dates), `callable` (new block), `parties` | `callable` block: list of optional redemption dates + call price (typically par/100%) |

**For extraction planning purposes:** 95001DP87 should remain at `ingested` status and be excluded from all extraction runs until the model is added. It is valuable as a structural test case once the model exists.

---

### 8.6 — `underlyingTerms.initialFixingLevel` is a key-value map, not a scalar

The schema defines `underlyingTerms.initialFixingLevel` as an object with pattern keys (`^[A-Za-z]\w*$`) — one entry per underlying (e.g., `{"U1": 5234.18}` for a single-underlying note). The current `underlying_terms` section prompt describes "initialLevel" as if it were a scalar value.

**Fix needed in system prompt:** Add to `underlying_terms` section note: *"underlyingTerms.initialFixingLevel is a key-value map. The key must match the underlying identifier code used in the `underlyings` object (e.g., 'U1' for the first underlying, 'U2' for the second). Never output a scalar — always output an object like `{'U1': 5234.18}`."*

---

### 8.7 — PRISM wiki cross-check: confirmed findings

The following pages were reviewed via the Azure DevOps wiki API:
- `/Basics & Important Links/PRISM Overview`
- `/Client models and field gaps/Structures – Model & Payoff Inventory`
- `/Chroma & Modelling/SPECTRUM Governance (Boards, Roles & Process)`
- `/Chroma & Modelling/Model examples` (2 examples: `yieldEnhancementAutocallBarrierCoupon`, `yieldEnhancementCoupon`)

**Confirmed from wiki:**

1. **SPECTRUM governance process**: Any new model (e.g., `fixedRateCallableNote`, `yieldEnhancementAutocallBufferCoupon`) requires:
   - A PRISM story/task submitted to the **SPECTRUM Governance Board** for approval
   - Executed by the **Chroma Admin Group** in the Chroma model designer
   - Model versions are tagged `draft` → `published`; PRISM Core syncs the published model

   _Practical implication_: New model additions are a formal process, not a quick schema edit. The schema gap for callable notes (Section 8.5) and buffer products should be tracked as a PRISM story.

2. **Structures → SPECTRUM migration context**: The Structures inventory confirms the following payoffs exist in the current system that will eventually need SPECTRUM model coverage:
   - `Income` model → "EMTN - Callable Fix and Float Income Note" (38), "EMTN - Call with Fixed Coupons Note" (16), "EMTN - Reverse Convertible" (231) — the first two confirm callable fixed-income is a real migration target
   - `Participation` model → "EMTN - Call CPN" (695), "EMTN - Call CPN with Issuer Call" (8) — participation products with upside and optional issuer call
   - `AutoCall` model → 8,499 products; several "buffer" and "protected" variants in the subtypes

3. **No conflicting model names found** in the wiki for `autocall`/`protection` delineation — the current section group proposal is consistent with SPECTRUM naming conventions.

4. **Model example pages are sparse** (only 2 of 9 models have examples). No wiki documentation for buffer, participation, callable, or digital models yet — further confirming these are schema roadmap items, not yet formalised.

**Open items to raise with PRISM model creation group:**
- Confirm `yieldEnhancementAutocallBufferCoupon` schema design: will the buffer level use `downsideRisk.strikeDetails` (existing pattern) or a new `buffer` sub-object?
- Confirm naming / model key for callable/fixed-rate note — closest Structures payoffs are "Callable Fix and Float Income Note" and "Call with Fixed Coupons Note"
- Consider creating PRISM stories for the two confirmed missing models from the CUSIP test set (see `CLASSIFICATION_ANALYSIS_AND_ROADMAP.md §Tier 3`)

---

## Section 9: Expert Settings Frontend — SectionPromptEditor Plan

*Status: Planning only — not yet implemented*

### 9.1 Overview

Currently the top-level navigation has two views: **Filings** and **Hints**. The user requested that both **Hints** (existing `HintsEditor`) and a new **Section Prompts** editor be grouped under a single **Expert Settings** area, accessible via the top nav. This reduces noise for non-expert users while keeping both tools accessible.

### 9.2 Nav Restructure (App.jsx)

**Current nav:**
```
[ Filings ] [ Hints ]
```

**Target nav:**
```
[ Filings ] [ Expert Settings ▾ ]
  → Expert Settings expands into internal tabs:
    [ Field Hints ]  [ Section Prompts ]
```

Implementation options:
- **Option A** (simpler): Replace `mainView = 'hints'` with `mainView = 'expert'` plus an `expertTab` sub-state (`'hints' | 'sections'`). The nav shows a single "Expert" button; within the expert view, two horizontal tabs appear at the top.
- **Option B**: Keep "Hints" and add "Sections" as separate top-level nav items. Less clean but marginally simpler to implement.

**Recommendation: Option A.** Both tools are for expert configuration — grouping them reduces nav clutter and pairs naturally with a future "Expert Settings" concept. Changes:
- `App.jsx`: change `mainView` options to `'filings' | 'expert'`
- Add `expertTab` state: `'hints' | 'sections'`
- In the expert view, render a two-tab bar (Field Hints / Section Prompts) and conditionally show `HintsEditor` or the new `SectionPromptsEditor`
- Nav button label: "Expert Settings" (or "Expert ⚙" for brevity)

### 9.3 SectionPromptsEditor Component

**File:** `frontend/src/components/SectionPromptsEditor.jsx`

**Layout:** Two-column. Left: section list sidebar (~200 px). Right: edit panel for selected section.

**Left sidebar — section list:**
- One row per section group (7 groups after removing `settlement`: `identifiers`, `product_generic`, `protection`, `underlying_terms`, `autocall`, `coupon`, `parties`)
- Each row: section name badge + "used by N models" count
- Active selection highlighted

**Right edit panel — per section:**
```
┌─────────────────────────────────────────────────────────────┐
│ Section: protection                                          │
│ Used by: yieldEnhancementBarrierCoupon, ...AutocallBarrier  │
│ Schema keys: barrier, downsideRisk                          │
├─────────────────────────────────────────────────────────────┤
│ System Prompt Note                             [Save note]  │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ You are extracting barrier/trigger terms from a ...     │ │
│ │ triggerLevelRelative is a decimal: 0.60 means ...       │ │
│ └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ Search Headers                              [+ Add]         │
│ [BARRIER ×] [TRIGGER ×] [KNOCK-IN ×] [BUFFER ×] ...       │
│ Max chars:  [10000    ]                      [Save all]     │
└─────────────────────────────────────────────────────────────┘
```

- System note: `<textarea>` with auto-resize, 4-8 rows
- Search headers: tag-pill style (click × to remove, input box to add new)
- Max chars: numeric `<input type="number">` with step=1000
- Save note: saves only `system_note` (frequent small edits)
- Save all: saves all fields for the section in one PUT

### 9.4 Backend: Section Specs Storage

**New files:**

`files/sections/section_specs.yaml` — canonical YAML for all section specs (replaces hardcoded Python dicts in `section_router.py`):

```yaml
# section_specs.yaml — loaded by section_loader.py, editable via Expert Settings UI
#
# Edit this file to tune section prompts, search headers, and window sizes.
# section_loader.py watches for file changes and reloads automatically.

identifiers:
  schema_keys: [identifiers, structuredProductsGeneric.name]
  search_headers:
    - CUSIP
    - ISIN
    - PRODUCT NAME
    - PRICING SUPPLEMENT
  max_chars: 8000
  system_note: >
    You are extracting identifying codes and the product name from the cover
    page of a 424B2 SEC filing. Focus on the first 200 lines...
  required_for:
    - yieldEnhancementCoupon
    - yieldEnhancementBarrierCoupon
    # ... etc

protection:
  schema_keys: [barrier, downsideRisk]
  search_headers:
    - BARRIER
    - TRIGGER
    - BUFFER LEVEL
    - PROTECTION LEVEL
    - KNOCK-IN
  max_chars: 10000
  system_note: >
    You are extracting protection/risk terms from a structured note...
  required_for:
    - yieldEnhancementBarrierCoupon
    - yieldEnhancementAutocallBarrierCoupon
    - yieldEnhancementCoupon   # downsideRisk (strike) only
    # ...
```

**New module: `backend/sections/` directory**

- `backend/sections/__init__.py` — empty
- `backend/sections/section_loader.py` — analogous to `backend/hints_loader.py`:
  - `get_section_specs() -> dict[str, SectionSpec]` — cached, mtime-checked reload
  - `save_section_spec(name: str, updates: dict)` — YAML write helper
- `backend/sections/router.py` — FastAPI router:
  - `GET /api/sections` — list all sections with metadata (name, schema_keys, required_for, max_chars)
  - `GET /api/sections/{section_name}` — full spec including system_note and search_headers
  - `PUT /api/sections/{section_name}` — update full spec (system_note + search_headers + max_chars)
  - `PUT /api/sections/{section_name}/system_note` — update note only (fast save)

`backend/extract/section_router.py` (the existing task #1 module) loads specs from `section_loader.get_section_specs()` instead of from hardcoded Python dicts.

### 9.5 Integration with Extraction

`section_router.py::get_sections_for_model(model_name)` → calls `section_loader.get_section_specs()` → returns live `SectionSpec` objects populated from YAML. Edits in the UI take effect on the next extraction call without server restart (same live-reload pattern as hints).

### 9.6 Effort Estimate

| # | Task | Effort |
|---|---|---|
| S1 | Create `files/sections/section_specs.yaml` with all 7 sections fully populated | 1.5 h |
| S2 | Create `backend/sections/section_loader.py` (mtime-cached YAML loader + save helper) | 1 h |
| S3 | Create `backend/sections/router.py` (4 endpoints) + mount in `main.py` | 1 h |
| S4 | Update `backend/extract/section_router.py` to load from `section_loader` instead of hardcoded dicts | 0.5 h |
| S5 | Add hints API methods to `frontend/src/api.js` (4 new methods) | 0.5 h |
| S6 | Create `frontend/src/components/SectionPromptsEditor.jsx` | 3 h |
| S7 | Update `frontend/src/App.jsx`: rename Hints→Expert, add `expertTab` state, render both editors under Expert view | 1 h |

**Additional effort (Expert Settings UI): ~8.5 hours** — can be parallelised with the section_router.py coding (tasks S1–S4 are backend prerequisites for S6–S7).

---

*End of plan additions. See Section 7 for full task list. Sections 8.1 and 8.2 changes (protection group rename + autocall note) are prerequisites that affect task #1 in Section 7. Start task #1 with the updated section group definitions above.*
