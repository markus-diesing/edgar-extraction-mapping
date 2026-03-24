# PRISM Model Classification — Analysis & Improvement Roadmap

*Generated: 2026-03-18 | Reference document — do not delete*

---

## Part 1 — Why Classification Changes Between Search and Extraction

### Observed behaviour
| CUSIP | Shown at search | After Classify | Change |
|-------|----------------|---------------|--------|
| 48136G4V9 | `yieldEnhancementAutocallBufferCoupon` | `yieldEnhancementAutocallBarrierCoupon` | Buffer → Barrier |
| 06376F7C7 | `participationBufferDigital` | `yieldEnhancementBarrierCoupon` | Completely different family |

### Root cause 1 — Schema coverage gap
`prism-v1.schema.json` contains exactly 9 models. The CUSIP mapping spreadsheet
(`CUSIP_PRISM_Mapping.xlsx`) references 4 model names, 2 of which do not exist in the schema:

| Model in mapping | In schema? |
|-----------------|-----------|
| `yieldEnhancementAutocallBarrierCoupon` | ✓ |
| `yieldEnhancementBarrierCoupon` | ✓ |
| `yieldEnhancementAutocallBufferCoupon` | **✗ missing** |
| `participationBufferDigital` | **✗ missing** |

### Root cause 2 — Hint silently discarded for unknown models
In `classify/router.py` the CUSIP hint is only forwarded to Claude when the mapped
model exists in the schema. For the two missing models the hint is dropped entirely,
Claude receives no guidance, and picks the closest of the 9 available options.

### Root cause 3 — No "unknown" escape valve
The prompt lists 9 models. Claude's RLHF training biases it toward giving an answer
rather than saying "none of these fit". Without an explicit `unknown` option + rules
for when to use it, Claude always forces a match.

### Root cause 4 — Schema model descriptions are thin
`yieldEnhancementCoupon` has **no description at all**. Others have one-liners about
product mechanics but nothing that maps PRISM terminology to the vocabulary used in
actual 424B2 filings (e.g. "Auto Callable Contingent Interest Notes").

### Which classification is more accurate?
| CUSIP | Mapping value | Classifier output | Verdict |
|-------|--------------|-------------------|---------|
| 48136G4V9 | `yieldEnhancement Autocall**Buffer**Coupon` | `yieldEnhancement Autocall**Barrier**Coupon` | **Mapping is more accurate.** Buffer ≠ Barrier structurally; both in same family, but different downside mechanic |
| 06376F7C7 | `participationBufferDigital` | `yieldEnhancementBarrierCoupon` | **Mapping is correct, classifier is wrong.** Participation/digital is a completely different payoff family |

---

## Part 2 — Improvement Roadmap

### Tier 1 — Quick wins (no schema changes)

**A. Add `unknown` to allowed model list with confidence floor**
The `unknown` option must appear in the model list (not just as a prose note) with an
explicit rule: *"If confidence is below 0.60, return 'unknown' rather than a low-confidence
guess."* 95%+ model selection accuracy requires honest abstention over a forced wrong match.

**B. Pass out-of-schema CUSIP hints to Claude with explanation**
Instead of silently dropping unknown model hints, forward them with context:
> *"The CUSIP lookup suggests this product is a 'participationBufferDigital'. That model
> does not exist in the current schema. If the filing is clearly a participation or digital
> payoff product — not a yield enhancement / reverse convertible — return 'unknown'."*

**C. Classify from the cover page only (new `CLASSIFICATION_CHARS` config ~4,000)**
The product type is determined by the first 20–30 lines of a 424B2. Sending 60K chars:
- costs ~20× more than necessary
- adds noise (risk factors, legal boilerplate) that can mislead the model
- actually *reduces* precision for nuanced distinctions

**Fallback strategy for exotic/complex products** (long coupon tables, basket underlyings
defined at the end of the document): if stage-1 confidence from the cover page falls below
the threshold, a targeted second pass extracts the key discriminating sections by searching
for structural headers (`BARRIER`, `TRIGGER`, `COUPON`, `AUTOCALL`, `BUFFER`, `DIGITAL`,
`PARTICIPATION`, `UNDERLYING`, `BASKET`) and feeds 1,500 chars around each match back to
the classifier alongside the cover page. This is far cheaper than sending the full document
and specifically reaches the information that matters for model disambiguation.

**D. Require `title_excerpt` in classification response**
Add a `title_excerpt` field to the classifier response JSON. Claude must quote the exact
product title from page 1. This: forces evidential grounding, provides a full audit trail,
and makes wrong classifications visible at a glance without opening the filing.

### Tier 2 — Glossary / keyword bridge (high value, low effort)

Product names in 424B2 filings follow highly consistent conventions. A vocabulary
bridge from filing language to PRISM features dramatically improves classification
and is the single most impactful change within the current 9-model constraint.

**Filing vocabulary → PRISM feature matrix:**

| Filing vocabulary | PRISM structural feature | Models it narrows to |
|---|---|---|
| Auto Call / Auto Callable / Autocall | `autocall` object | `yieldEnhancementAutocall*` |
| Contingent Interest / Conditional Coupon | coupon tied to a barrier level | `*AutocallBarrierCoupon`, `*BarrierCoupon` |
| Contingent Coupon (no barrier) | periodic coupon | `yieldEnhancementAutocallCoupon` |
| Barrier / Trigger / Knock-In / KI | hard barrier (full loss below) | `*BarrierCoupon` |
| Buffer / Soft Protection / Partial Protection | percentage buffer (absorbs first X% loss) | **not in schema yet** |
| Digital / Binary / Fixed Return | binary payoff | **not in schema yet** |
| Participation / Leveraged Upside | upside tracking above strike | **not in schema yet** |
| Accumulator / Decumulator / Knock-Out Forward | scheduled exchanges + KO | `forwardKoStripEquity` |
| Market Linked CD / Certificate of Deposit | capital protected | **not in schema yet** |
| Reverse Convertible (no autocall mention) | vanilla RC | `yieldEnhancementBarrierCoupon` or `yieldEnhancementCoupon` |

Implementation: add a `classificationHints` block to each model entry in
`prism-v1.schema.json` (see Part 3 and the dedicated specification document
`docs/specs/SPEC_CLASSIFICATION_HINTS_FORMAT.md`).

### Tier 3 — Schema completeness (prerequisite for structural correctness)

The two confirmed missing models from the CUSIP test set:

| Missing model | Description | Closest current model |
|---|---|---|
| `yieldEnhancementAutocallBufferCoupon` | Autocall + coupon + *buffer* downside protection | `yieldEnhancementAutocallBarrierCoupon` |
| `participationBufferDigital` | Participation (upside tracking) + buffer protection + digital/binary payout | none — forced to wrong family |

Until these are added, classification is structurally broken for any CUSIP in those
product families regardless of prompt quality. Use `CUSIP_PRISM_Mapping.xlsx` as the
canonical feature request list: every model name in the mapping not present in the
schema is a gap requiring a new schema entry.

### Tier 4 — Feedback loop (highest long-term ROI)

**Per-CUSIP confidence over time:**
- Store `title_excerpt` per classification for audit trail
- Frontend "correct this classification" button writes to `classification_feedback` table
- On future classifications: pull 2–3 approved corrections as few-shot examples in the prompt

**Per-datapoint confidence:**
Add `_confidence` map to extraction (already partially implemented). Scoring convention:
- 1.0 = value verbatim in filing, quoted in `_excerpts`
- 0.7 = inferred from surrounding context, inference clause in `_excerpts`
- 0.4 = estimated / typical for this product type
Display in expert review view alongside the excerpt status indicator.

**Schema validation:**
Post-extraction: validate every extracted value against the field's `enum` constraints
from the schema. Fields with invalid values (e.g. `triggerEffect = "knockIn"` where
valid values are only `["default", "payment"]`) should be flagged with
`review_status = "schema_error"` and `confidence_score = 0.0` for mandatory human review.

---

## Part 3 — Prioritised Action List

| Priority | Action | Effort | Impact |
|---|---|---|---|
| 1 | Add `unknown` to model list with confidence floor (≥ 0.60 required) | 15 min | Stops wrong forced matches |
| 2 | Pass out-of-schema CUSIP hint with explanation | 30 min | Fixes `participationBufferDigital` case |
| 3 | `CLASSIFICATION_CHARS = 4_000` + targeted fallback for complex products | 1 hr | ~20× cheaper, higher accuracy for most products |
| 4 | Require `title_excerpt` in classification response | 30 min | Full audit trail |
| 5 | Add `classificationHints` to schema JSON (keyword glossary per model) | 2–3 hrs | Largest accuracy gain within current 9 models |
| 6 | Add missing models to `prism-v1.schema.json` | 1–2 days | Required for structural correctness |
| 7 | Frontend: "correct classification" button + corrections table | 2 hrs | Enables feedback loop |
| 8 | Post-extraction enum validation | 1 hr | Catches schema violations like triggerEffect="knockIn" |
| 9 | Add `_confidence` per-field scoring (explicit 0.4 / 0.7 / 1.0 scale) | 1 hr | Per-datapoint quality signal |

---

*End of document. See also:*
- `docs/specs/SPEC_CLASSIFICATION_HINTS_FORMAT.md` — specification for model creation group
- `IMPROVEMENTS_TODO.md` — actionable task backlog
