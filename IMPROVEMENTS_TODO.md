# EDGAR Extraction — Improvements Backlog

*Last updated: 2026-03-19*

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

- [ ] **Scope decision: plain-rate debt instruments** — Wells Fargo batch (3/3 CUSIPs) returned
  `unknown` (conf 0.90–0.95), correctly, because all three are plain-rate instruments:
  "Floating Rate Notes Linked to Compounded SOFR" and "Fixed Rate Callable Notes".  These
  are not structured products; they carry no optionality captured by the PRISM schema.
  *Decision needed*: should the pipeline explicitly reject / route these to a separate
  "plain debt" classification rather than `unknown`?  If yes, add a lightweight plain-rate
  classifier gate before the PRISM model list.  If no, `unknown` is the correct terminal
  state and no action is required.  *Owner: Markus / product owner decision.*

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

- [ ] **Frontend: display `title_excerpt` and `product_features`** on the classification
  result card so reviewers can immediately see what Claude quoted as the product name
  and which features it detected (autocall, barrier, etc.).

- [x] **Frontend: "correct this classification" button** — implemented as the
  "Set Model" dropdown panel (available on all non-approved states). Calls
  `POST /api/filings/{id}/classify-override` which sets confidence to 1.0 and
  writes a `ClassificationFeedback` row for audit. "↺ Reset" button added for
  `classified` / `needs_review` states — reverts to `ingested` via
  `POST /api/filings/{id}/reset-classification`.

- [ ] **Frontend: flag `schema_error` fields** in the expert review view.
  Fields with `review_status = "schema_error"` should be shown in red with the
  `validation_error` message visible on hover / expand.

- [ ] **Feed approved `ClassificationFeedback` rows as few-shot examples** into the
  classification prompt.  Logic: query `classification_feedback` for
  `used_as_example = False`, include up to 3 in the prompt, then mark them
  `used_as_example = True`.  Add to `classifier.py`.

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
