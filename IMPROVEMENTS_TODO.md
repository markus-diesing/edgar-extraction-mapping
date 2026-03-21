# EDGAR Extraction — Improvements Backlog

*Last updated: 2026-03-21*

Items are roughly ordered by priority within each group.
Completed items are moved to the bottom section for reference.

---

## 🔴 P1 — Correctness blockers

- [ ] **Extend schema with missing models** (`participationBufferDigital`,
  `yieldEnhancementAutocallBufferCoupon`, `digitalBarrierNote`).  Classification is
  structurally broken for any CUSIP in those families until they are added.
  *Confirmed missing from 24-CUSIP batch run (2026-03-18):*
  - `participationBufferDigital` — Barclays "Capped Leveraged Participation Notes"
    (3 CUSIPs: all returned `unknown`, product_features correctly identified "leveraged
    participation", "cap", "buffer" but no matching schema model exists)
  - `yieldEnhancementAutocallBufferCoupon` — previously identified gap, batch confirmed
  - `digitalBarrierNote` — JPMorgan `46660MNU5` "Digital Barrier Notes Linked to Least
    Performing of...": classifier identified correct product type in `product_features`
    (`{type: "digital barrier note", features: ["barrier", "digital coupon", "worst-of"]}`)
    but forced to `yieldEnhancementBarrierCoupon` (wrong); 0/47 fields extracted as result.
    This is a silent total extraction failure — the most damaging schema gap in the batch.
  *Owner: PRISM model creation group.*

- [ ] **Add `classificationHints` to each model in `prism-v1.schema.json`**.
  See `files/CLASSIFICATION_HINTS_SPEC.md` for the exact JSON structure and rationale.
  *Owner: PRISM model creation group.*

- [ ] **Date grids and coupon schedules** — complete topic, see dedicated section below.

- [ ] **Scope decision: plain-rate debt instruments** — Wells Fargo full batch (10/10 CUSIPs)
  returned `unknown` (conf 0.90–0.95), correctly — all are plain-rate instruments:
  "Floating Rate Notes Linked to Compounded SOFR", "Fixed Rate Callable Notes". These are
  not structured products and carry no PRISM optionality.
  *Decision needed*: route to explicit "plain debt" terminal state, or leave as `unknown`?
  If yes, add a lightweight plain-rate gate before the PRISM model list.
  **HSBC (4/4 CUSIPs)** similarly needs investigation — all `needs_review` with conf 0.45–0.55.
  HSBC has no issuer hint file; product types are currently unknown.
  *Owner: Markus / product owner decision.*

**Batch run results (2026-03-21, 84 filings):**

| Issuer | Total | Extracted | Classified | Needs Review | Avg Fill% |
|---|---|---|---|---|---|
| BANK OF MONTREAL /CAN/ | 9 | 3 | 1 | 5 | 48.6% |
| Bank of Montreal | 2 | 2 | 0 | 0 | 47.0% |
| BARCLAYS BANK PLC | 10 | 6 | 1 | 3 | 52.1% |
| BofA Finance LLC | 2 | 2 | 0 | 0 | 57.6% |
| CITIGROUP INC | 11 | 4 | 5 | 2 | 45.1% |
| GOLDMAN SACHS GROUP INC | 4 | 2 | 0 | 2 | 46.4% |
| HSBC USA INC /MD/ | 4 | 0 | 0 | 4 | — |
| JPMORGAN CHASE & CO | 20 | 9 | 5 | 6 | 45.4% |
| JPMorgan Chase Financial | 2 | 2 | 0 | 0 | 51.7% |
| UBS AG | 10 | 6 | 3 | 1 | 48.9% |
| WELLS FARGO & CO | 10 | 0 | 0 | 10 | — |

Key observations:
- Overall extraction fill rate: ~49% average (target: >65%)
- 15 `classified` filings are queued but not yet extracted (Citigroup 5, JPMorgan 5, UBS 3, Barclays 1, BMO 1)
- JPMorgan has 1 filing at **0% fill** — confirmed digitalBarrierNote mis-mapped to yieldEnhancementBarrierCoupon (see P1 schema gap above)
- Wells Fargo 10/10 and HSBC 4/4 are structural `needs_review` — not extraction failures

---

## 🟠 P2 — Quality improvements

- [ ] **Issuer-specific extraction hints** — batch evidence (2026-03-18) shows extraction
  consistency varies significantly by issuer:
  - **UBS**: 3/3 CUSIPs correctly classified (`yieldEnhancementBarrierCoupon`), field counts
    32–33/61–72 — consistent layout, strong candidate for per-issuer section hints
  - **Citigroup**: 3/3 correct (`yieldEnhancementBarrierCoupon`), stable field counts —
    second priority candidate
  - **Barclays / Wells Fargo**: need schema expansion first; issuer hints premature
  *Implementation*: `files/issuer_extraction_hints.json` — per-issuer map of
  `{section_headings[], field_aliases{}, typical_layout_notes}`.  Extractor uses hints
  when available; falls back to full discovery when `fields_found / field_count < 0.5`.
  Estimated effort: 1 day for UBS + Citigroup templates.

- [x] **Frontend: display `title_excerpt` and `product_features`** on the classification
  result card so reviewers can immediately see what Claude quoted as the product name
  and which features it detected (autocall, barrier, etc.).

- [x] **Frontend: "correct this classification" button** — implemented as the
  "Set Model" dropdown panel (available on all non-approved states). Calls
  `POST /api/filings/{id}/classify-override` which sets confidence to 1.0 and
  writes a `ClassificationFeedback` row for audit. "↺ Reset" button added for
  `classified` / `needs_review` states — reverts to `ingested` via
  `POST /api/filings/{id}/reset-classification`.

- [x] **Frontend: flag `schema_error` fields** in the field table and expert review view.
  Fields with a `validation_error` are shown with a red left-border row, red "schema error"
  badge, and the error message visible on hover.

- [x] **Feed approved `ClassificationFeedback` rows as few-shot examples** into the
  classification prompt.  `_get_few_shot_examples()` queries up to 3 recent rows and
  injects them into the Stage 1 prompt; `_mark_examples_used()` marks them afterward.
  Implemented in `classify/classifier.py`.

- [ ] **`_confidence` per-field scoring — explicit scale**.  Update the extraction
  prompt to request a three-level confidence: 1.0 = verbatim quoted, 0.7 = inferred
  from context, 0.4 = estimated / typical.  Display in the expert review view.

- [ ] **KPI endpoint: include `classify_stage1` + `classify_stage2` separately**.
  The new `call_type` values (`classify_stage1`, `classify_stage2`) are not yet
  aggregated in `GET /api/filings/{id}/kpis`.

---

## 🟡 P3 — Date grids and coupon schedules *(own epic)*

**Background**: the extractor currently identifies coupon frequency (e.g. "monthly")
but does not construct a full payment schedule from start date, end date, frequency,
day count convention, and roll convention.  These are standard fixed-income concepts
that apply directly to structured product coupons.

**What is needed:**

1. **Schedule generation engine** — given:
   - `startDate` (or `tradeDate` / `issueDate`)
   - `endDate` (or `maturityDate`)
   - `frequency` (daily / weekly / monthly / quarterly / semi-annual / annual)
   - `dayCountConvention` (ACT/360, ACT/365, 30/360, …)
   - `businessDayConvention` (Following, Modified Following, Preceding, End-of-Month)
   - `calendar` (NYC, LON, TARGET, …)
   → produce a list of `{periodStart, periodEnd, paymentDate, accrualDays, couponFactor}`

2. **Schema additions** — `coupon.paymentSchedule` (array of date entries) should be
   added to the relevant PRISM models if not already present.

3. **Extraction prompt update** — instruct Claude to extract the individual schedule
   parameters (start, end, frequency, DCC, BDC, calendar) rather than trying to
   enumerate dates itself.  The schedule generation should happen in Python post-
   extraction using a library like `QuantLib` or `pandas_market_calendars` +
   `dateutil.rrule`.

4. **Validation** — generated schedules should be cross-checked against any explicit
   date tables appearing in the filing (many 424B2 supplements include a "Review
   Dates" or "Coupon Dates" table).  Mismatches are flagged as `schema_error`-style
   warnings.

5. **Handling day-count and roll conventions from filings** — 424B2 filings express
   these in prose ("Following Business Day Convention", "Actual/360"), not as machine-
   readable codes.  A mapping table (`ACT/360` → `"act360"`, etc.) should be embedded
   in the extractor prompt or in a config file.

**Suggested libraries:**
- `python-dateutil` (rrule) — lightweight, no C dependencies
- `QuantLib-Python` (ql) — authoritative for DCC/BDC but heavier
- `pandas_market_calendars` — good for exchange calendars
- `bizdays` — minimal calendar library

*Effort estimate: 3–5 days for a production-quality implementation.*

---

## 🔵 P4 — Pipeline coverage

- [ ] **Extend beyond EDGAR 424B2**: the pipeline should support Term Sheets,
  Final Terms (ESMA format), and pricing supplements from other regulatory regimes
  (e.g. KIID, KID, PRIIPs).  The classification and extraction prompts already work
  on plain text — the main changes needed are:
  - A new ingest path for non-EDGAR documents (file upload or URL)
  - Format detection (PDF → text via `pdfplumber`; Word → text via `python-docx`)
  - Prompt adjustments where document structure differs materially from 424B2
  - `classificationHints.documentFormats` in the schema (see CLASSIFICATION_HINTS_SPEC.md)

- [x] **Image / chart persistence in HTML filings** — `edgar_client.download_filing_images()`
  now downloads formula images from the same EDGAR filing folder during ingest. Images are
  saved alongside `raw.html` and listed in `metadata.json["images"]`. The served HTML still
  uses `<base href="...sec.gov/...">` injection; locally-saved images serve as a persistent
  backup for formula charts used in extraction. `POST /api/filings/{id}/fetch-images` and
  `scripts/backfill_images.py` allow backfilling existing filings.

- [ ] **PDF-only filings** — currently rejected at ingest.  Add `pdfplumber` extraction
  as a fallback.  Many older 424B2 filings and most bank-internal term sheets are PDF-only.

- [ ] **Batch ingest** — accept a list of CUSIPs / accession numbers and process them
  in a queue with rate-limit awareness.

---

## ✅ Completed

- [x] **Section pre-filtering (A2)** — `_trim_to_key_terms_section()` in `extract/extractor.py`
  trims filing text to a window anchored at the earliest Key Terms section heading before
  passing to Claude. Uses issuer YAML `section_headings` → cross-issuer fallbacks → head.
- [x] **Batch classify+extract script (A1)** — `scripts/batch_classify_extract.py` classifies all
  `ingested` filings and extracts all `classified` filings via live REST API.  Supports
  `--dry-run`, `--classify-only`, `--reextract`, configurable delays.
- [x] **BMO autocall hints** — `files/hints/issuer_Bank_of_Montreal.yaml` and
  `files/hints/cross_issuer_field_hints.yaml` updated with `autocall.observationFrequency`,
  `autocall.callSchedule`, `autocall.callFrequency`, `autocall.observationFrequency.$type`
  (discriminated union documentation), and clarification that BMO "Optional Early Redemption"
  is an index-triggered autocall, not a discretionary issuer call.

- [x] EDGAR search + ingest pipeline (FastAPI + SQLite)
- [x] Claude-based classification with PRISM schema
- [x] Claude-based field extraction with `_excerpts` and `_confidence`
- [x] Expert review view with side-by-side HTML filing and excerpt highlighting
- [x] KPI strip (ingest timing, API cost, token counts)
- [x] Collapsible sidebar
- [x] `unknown` model + confidence floor (≥ 0.60 required)
- [x] Two-stage classification (cover page + targeted fallback)
- [x] Product name / feature extraction in classifier response
- [x] Out-of-schema CUSIP hint communicated to Claude
- [x] Post-extraction enum/const schema validation (`validation_error` + `schema_error` status)
- [x] `ClassificationFeedback` table (feedback loop infrastructure)
- [x] `classification_title_excerpt` + `classification_product_features` on Filing row
- [x] Image downloading during ingest (`edgar_client.download_filing_images()`; images saved alongside `raw.html`; `metadata.json["images"]` populated)
- [x] `POST /api/filings/{id}/fetch-images` — backfill image download for existing filings
- [x] `POST /api/filings/{id}/reset-classification` — revert to `ingested`, clearing classification data
- [x] `POST /api/filings/{id}/classify-override` — manual PRISM model assignment, logged to `classification_feedback`
- [x] `GET /api/classify/models` — list valid PRISM model IDs from schema
- [x] "↺ Reset" button in UI (`classified` / `needs_review` states)
- [x] "Set Model" dropdown panel in UI (all non-approved states) with model select + reason field
- [x] "⬛ Filing HTML" button in field review view — always accessible
- [x] HTML iframe shown for `exported` status
- [x] `files/financial_glossary.md` — loaded into extraction system prompt (mtime-cached)
- [x] BofA issuer hints expanded (image-embedded formulas guidance, Least Performing synonym)
- [x] JPMorgan issuer hints expanded (worst-of basket, payout formula priority)
- [x] `files/architecture.drawio` — system architecture diagram created
- [x] `scripts/backfill_images.py` — bulk image backfill for existing filings
- [x] `_SECTION_HEADERS` in `classifier.py` expanded with worst-of synonyms and payout formula anchors
- [x] `section_specs.yaml` `product_generic` section updated with PAYOUT FORMULA PRIORITY note
