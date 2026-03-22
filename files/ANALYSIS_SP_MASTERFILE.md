# Analysis — SP_MasterFile.xlsx

**Date:** 2026-03-22
**Source file:** `files/SP_MasterFile.xlsx`
**Extracted data:** `files/sp_masterfile_extracted.json`

---

## 1. File Structure

The file is column-oriented: one column = one payout type example. The first column is a row-label column; all subsequent columns are individual product instances identified by their ISIN.

**14 sheets, 12 active:**

| Sheet | Payout types (columns) | Rows | Product family |
|-------|----------------------|------|---------------|
| Autocall | 12 | 45 | Autocallable notes |
| Capital protected | 40 | 40 | Capital-protected (floor) notes |
| Non-capital protected | 40 | 45 | Barrier/participation notes |
| Minimum redemption | 18 | 41 | Notes with minimum redemption floor |
| CLN zero coupon | 7 | 44 | Credit-linked notes, zero coupon |
| CLN fixed coupon | 12 | 42 | Credit-linked notes, fixed coupon |
| CLN floating coupon | 22 | 45 | Credit-linked notes, floating coupon |
| Credit overlay | 17 | 46 | Structured notes with credit overlay |
| BULL & BEAR | 8 | 25 | Directional certificates |
| Warrants | 4 | 28 | Warrants |
| Mini futures | 4 | 25 | Leveraged delta-one products |
| Turbos | 4 | 28 | Knock-out leveraged products |
| Tabelle1 | 7 | 41 | *(Anomalous — see §3 below)* |
| Sheet1 | — | — | Empty |

**Total payout type examples: ~188 across all active sheets**

---

## 2. Information Available Per Column (Row Dimensions)

The following row labels recur across most sheets. Not all are present in every sheet — the schema is semi-structured.

| Row label | Content type | Notes |
|-----------|-------------|-------|
| `row_0` | ISIN | European securities identifier (12-char, e.g. SE0006993184) |
| `row_1` | Internal name | Sequential label ("Autocall 1", "Capital protected 3", etc.) |
| `Level 1` | Taxonomy tier 1 | Broad product family (e.g. "Autocall", "Multi underlying") |
| `Level 2` | Taxonomy tier 2 | Sub-family (e.g. "Worst of", "Participation ratio") |
| `Level 3` | Taxonomy tier 3 | Variant feature (e.g. "Memory coupon", "European DIP Barrier") |
| `Level 4` | Taxonomy tier 4 | Further refinement (e.g. "Quanto", "Flat coupon") |
| `Level 5–6` | Taxonomy tier 5–6 | Present in CLN/Credit sheets only |
| `Short description` | 1–2 sentence prose | Product description in investor language |
| `EUSIPA-code` | Integer code | European Structured Products Association classification code |
| `JIRA Code` | Internal ref | Issuer/system tracking code (not relevant for EDGAR) |
| `JIRA Issue ID` | Internal ref | See above |
| `JIRA Product Feature` | Internal flags | Product configuration flags used by the issuing system |
| `Fixing needed?` | Comma list | Types of fixings required (e.g. "FinalFixing, CallObsFixing") |
| `Type` | MiFID type + legal form | MiFID classification and legal wrapper type |
| `How the investment works` | Multi-sentence narrative | Plain-language payout mechanics (most valuable field) |
| `Upside` | Formula or prose | Upside payoff formula or description |
| `Downside` | Formula or prose | Downside formula (e.g. "(Performance * Participation); DI BARRIER AT MATURITY") |
| `Key figures:` / `Key numbers:` | Parameter list | List of extractable terms (Coupon, Call barrier, Observation dates, etc.) |
| `row_N` (numbered) | Parameter names or values | Specific key terms relevant to this payout type |

---

## 3. The Tabelle1 Sheet — Anomalous Structure

This sheet is structurally inverted compared to the others: rows are the payout types and columns are different products. More importantly, each row contains a full English-language payout description such as:

> *"If, on the valuation date, the underlying asset has had a positive performance the note will pay the nominal amount plus the nominal amount multiplied by the performance of the underlying asset multiplied by the participation ratio, on the redemption date."*

These descriptions are essentially the "How the investment works" content for a large set of capital-protected participation products, laid out in a lookup-table format. This sheet is a semantic reference, not a product catalog.

---

## 4. Relevance Assessment — PRISM Schema and EDGAR Filing Identification

### 4a. Fields relevant for identifying a PRISM schema

| Field | Relevance | Reason |
|-------|-----------|--------|
| `Level 1–4` | **High** | Directly encodes the structural taxonomy hierarchy — aligns closely with the feature dimensions in `Payout_to_Features.xlsx` and the PRISM model families |
| `How the investment works` | **High** | Plain-language payout descriptions use the same vocabulary as term sheets and EDGAR filings. Directly usable as `classificationHints.description` content per PRISM model. |
| `EUSIPA-code` | **High** | Standard European taxonomy code. Provides a cross-reference anchor between this file, other definition files, and the PRISM schema. See §5. |
| `Upside / Downside` | **High** | Structured payoff formulas (where present) are precise feature indicators. "DI BARRIER AT MATURITY" maps directly to `DOWNSIDE_PROTECTION_TYPE = BARRIER`. |
| `Short description` | **Medium** | Useful vocabulary; less precise than the full narrative |
| `Fixing needed?` | **Medium** | "CallObsFixing" → autocall; "DigitalObsFixing" → contingent coupon. Machine-parseable feature indicators. |
| `Type` (MiFID) | **Medium** | MiFID classification (1a, 1b, 1c) provides a broad product-category signal |
| `Key figures:` rows | **Medium** | The list of key terms per product type (Coupon, Call barrier, etc.) maps directly to the extractable PRISM fields for that model |

### 4b. Fields relevant for identifying an EDGAR filing

| Field | Relevance | Reason |
|-------|-----------|--------|
| `ISIN` (row_0) | **Low–Medium** | EDGAR filings use CUSIPs, not ISINs. Some European-issued products filed in EDGAR carry both; the ISIN can be cross-referenced via a mapping service. Not directly usable as a lookup key. |
| `How the investment works` | **High** | EDGAR 424B2 filings contain equivalent prose in "Payments at Maturity" and "General Terms" sections. The SP_MasterFile narratives serve as pattern templates. |
| `Level 1–4` taxonomy | **High** | The taxonomy terms ("Worst of", "Memory coupon", "European DIP Barrier") appear verbatim or near-verbatim in EDGAR filing text. Usable as feature indicators in the classificationHints prompt. |
| `EUSIPA-code` | **Low** | Rarely appears in EDGAR filings directly; appears in prospectuses for European issuers filed with the SEC. |
| Internal codes (JIRA) | **None** | Issuer-internal tracking; not in EDGAR filings. |

---

## 5. Relationship to Payout_to_Features.xlsx — Overlap and Cross-Reference

The two files describe overlapping product universes from different institutional perspectives:

| | Payout_to_Features.xlsx | SP_MasterFile.xlsx |
|-|------------------------|-------------------|
| Orientation | Row = payout type, Col = feature | Col = payout type, Row = feature |
| Count | 196 payout types | ~188 payout type examples |
| Coverage | US-centric structured products (EDGAR/PRISM) | European structured products (Swedish, Finnish, Danish, Norwegian ISINs; some XS) |
| Identifier | Named types (no ISIN/CUSIP) | ISIN per example |
| Feature encoding | Boolean + categorical matrix (22 dimensions) | Hierarchical taxonomy + narrative prose |
| Taxonomy anchor | PRODUCT_SUB_TYPE (GROWTH/YIELD/PROTECTION) + CALL_TYPE + DOWNSIDE | Level 1–4 hierarchy |
| Classification anchor | PRISM model (pending mapping) | EUSIPA code |

**Would the overlap be detected today?** No. The system currently has no mechanism to compare product definitions across files. A filing that matches an autocall product in Payout_to_Features and a "Flat coupon Autocall" in SP_MasterFile would be processed as if the two files were unrelated.

**Should the overlap be detected?** Yes, for two reasons:

1. **Consistency:** If the two files disagree about a product's characteristics, any filing of that type is structurally ambiguous. The system should surface this as a conflict rather than silently accepting one file's definition.

2. **Confidence boost:** If both files agree on the feature set of a product type, that agreement is a confidence signal. A classification confirmed by two independent reference sources is more reliable than one confirmed by only one.

---

## 6. How Multiple Definition Files Should Be Treated in the Tool

### The core problem

Multiple definition files will accumulate over time, in varying structures, with different naming conventions, different identifier systems (ISIN, CUSIP, internal codes), and partial overlap. A naive approach — load each file independently, treat each as authoritative — will produce silent conflicts and duplicated effort.

### Proposed approach: canonical feature vector as the reconciliation key

The 22-dimension feature vector from Payout_to_Features.xlsx (COUPON_TYPE, CALL_TYPE, DOWNSIDE_PROTECTION_TYPE, HAS_COUPON_BARRIER, etc.) is a natural canonical representation. It was designed exactly for this: to describe any structured product payout type in a language-neutral, file-neutral way.

Every definition file, regardless of its structure, should be converted to this canonical representation before being compared or merged. The conversion process:

1. **Parse the file** — extract the features it encodes (taxonomy levels, narrative descriptions, payoff formulas)
2. **Map to the 22 canonical dimensions** — either manually (a one-time exercise per file type) or via LLM extraction from the narrative "How the investment works" field
3. **Compare by feature vector** — entries that produce the same (or closely matching) feature vector are the same product type, regardless of what file they came from

### Overlap detection rules

| Situation | Action |
|-----------|--------|
| Two files produce identical feature vectors for what appear to be different payout types | Flag as potential duplicate — confirm by narrative comparison |
| Two files produce identical feature vectors and agree on the PRISM model | Confidence boost; use both as `classificationHints` examples |
| Two files produce identical feature vectors but disagree on a feature value | Surface as conflict; require human adjudication before either is used |
| A new file introduces a feature vector not found in any existing file | Candidate for a new PRISM model — flag for schema team |

### Practical implication for SP_MasterFile

The EUSIPA code is the bridge. A mapping of EUSIPA codes to the 22-feature canonical vector would allow:

- Any product in SP_MasterFile to be mapped to its canonical feature vector via its EUSIPA code
- Any EDGAR filing that references an EUSIPA code (European issuers sometimes include it) to be pre-classified from the code alone
- Cross-file overlap detection by comparing EUSIPA → feature vector against the Payout_to_Features feature matrix

This EUSIPA → feature vector mapping does not yet exist but would be a high-value one-time exercise (~half day). The SP_MasterFile provides the raw material for it.

### What "the tool" should eventually do with multiple definition files

1. Ingest any definition file → extract feature vectors per payout type → store in a canonical registry
2. When a new file is loaded, compute feature vectors and compare against the registry
3. Surface overlaps, conflicts, and gaps before any data from the new file affects the classifier
4. The classifier consumes the registry, not the raw files

The raw files become source material; the canonical registry becomes the single source of truth. New models added to PRISM are automatically matched against the registry to validate that the feature vector is unique and consistent with existing entries.

---

## 7. Summary of Actionable Outputs

| Output | Status |
|--------|--------|
| `files/sp_masterfile_extracted.json` | Written — all 12 active sheets, every column and row |
| EUSIPA code inventory | Available in JSON; can be extracted as a reference list |
| "How the investment works" narratives | Available per product — directly usable as classificationHints input |
| Feature vector mapping (SP_MasterFile → 22-dim canonical) | Not yet done — requires mapping exercise |
| Overlap detection vs. Payout_to_Features.xlsx | Not yet done — requires canonical vector mapping first |
