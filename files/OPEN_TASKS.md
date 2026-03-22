# Open Tasks

**Last updated:** 2026-03-22
**Source:** Requirements audit + session review + strategic planning

Tasks are grouped by priority. Each entry notes its source document and estimated effort.

---

## 🔴 A — Critical (blocks accuracy or core workflow)

### A1 — Add `classificationHints` to `prism-v1.schema.json`
**Source:** `CLASSIFICATION_HINTS_SPEC.md` (full spec), `CLASSIFICATION_ANALYSIS_AND_ROADMAP.md` item 5, `PLAN_MODEL_SCALING_STRATEGY.md`
**Effort:** ~2 h (schema editing, no code changes)
**What:** Add a `classificationHints` block to each of the 9 existing models in the schema's `oneOf` array. The spec in `CLASSIFICATION_HINTS_SPEC.md` defines the exact structure and provides draft content for every model. Once populated, the classifier prompt is built from schema knowledge rather than external files.
**Why it matters:** Single highest-leverage change available. Renders the CUSIP xlsx unnecessary for classification of known models. Foundation for adding new models cleanly.

### A2 — Add two missing PRISM payout models to schema
**Source:** `CLASSIFICATION_ANALYSIS_AND_ROADMAP.md` item 6
**Effort:** ~2 h (schema + hints content for both models)
**What:** Add `yieldEnhancementAutocallBufferCoupon` and `participationBufferDigital` to `prism-v1.schema.json`. Both are referenced in `CUSIP_PRISM_Mapping.xlsx` but absent from the schema. Filings of these types currently misclassify into nearest neighbours.
**Dependency:** A1 should be done first so the new models include classificationHints from the start.

---

## 🟠 B — High Priority (completes partially-specified workflow)

### B1 — Three-state classification status machine (backend)
**Source:** `PLAN_CLASSIFICATION_REVIEW_GATE.md` tasks 1–5
**Effort:** ~2 h
**What:** Update `classifier.py` `_persist()` (lines 515–537) to produce three outcomes instead of two:
- `classified` — confidence ≥ 0.80 (`CLASSIFICATION_GATE_CONFIDENCE`)
- `needs_classification_review` — confidence 0.60–0.79 (human confirmation required)
- `needs_review` — confidence < 0.60 or model = "unknown"

The config constant `CLASSIFICATION_GATE_CONFIDENCE = 0.80` already exists but is unused in persist logic. Also update status comment in `database.py` and status enum in `classify/router.py`.

### B2 — `POST /api/classify/{id}/confirm` endpoint
**Source:** `PLAN_CLASSIFICATION_REVIEW_GATE.md` task 3
**Effort:** ~1 h
**What:** New route in `classify/router.py`. Accepts `{ payout_type_id, confirmed_by }`. Sets status to `classified`, writes `ClassificationFeedback` record. Without this, filings in `needs_classification_review` have no exit path.

### B3 — Frontend: confirmation modal and status wiring (5 touch-points)
**Source:** `PLAN_CLASSIFICATION_REVIEW_GATE.md` tasks 6–14
**Effort:** ~5 h
**What:** Five components need updating or creation:
1. `StatusBadge.jsx` — add style for `needs_classification_review`
2. `FilingList.jsx` — add filter option for new status
3. `FilingDetail.jsx` — add warning banner when status is `needs_classification_review`
4. `ConfirmClassificationModal.jsx` — new component; model selector + confirm button
5. `api.js` — add `confirmClassification(filingId, payoutTypeId)` method

---

## 🟡 C — Medium Priority (strategic / scaling)

### C1 — Model scaling strategy: answer open questions and choose implementation path
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` (Q1–Q6)
**Effort:** Discussion + decision (no code until questions answered)
**What:** Six open questions determine the implementation shape for sustainable model onboarding. See `PLAN_MODEL_SCALING_STRATEGY.md` for the full list. Key questions:
- Does PRISM documentation accompany new schemas? (determines annotation effort per new model)
- Is zero-annotation the goal, or is 15 min/model acceptable?
- What frequency are new models expected?
- What is the fallback when no model matches?

### C2 — Demote CUSIP xlsx to optional enrichment
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 4
**Effort:** ~1 h
**What:** Make CUSIP mapping lookup a confidence *booster* rather than a hard gate. Classifier proceeds on document evidence alone when a CUSIP is not in the mapping. Xlsx contribution fades naturally as classificationHints mature. Prerequisite: A1 complete.

### C3 — Feature matrix per model (discriminating logic)
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 2
**Effort:** ~2 h (schema + classifier prompt update)
**What:** Add a boolean `features` block to each model (has_autocall, has_conditional_coupon, has_barrier, etc.). Used as a second-stage disambiguator when two models score similarly on Stage 1. Particularly useful for new models that share vocabulary with existing ones.

### C4 — Few-shot product title examples per model
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 3
**Effort:** ~1 h (content, no code)
**What:** Add 2–3 representative product title examples to each model's classificationHints block. Drawn from real approved filings. Very effective because filing vocabulary matches the examples directly.
**Dependency:** A1 (classificationHints block must exist first).

### C5 — Export validation messaging improvement
**Source:** `REQUIREMENTS.md` FR-6.5 (partially implemented)
**Effort:** ~1 h
**What:** Current export validates against schema but error surface in UI is limited. Surface validation errors more clearly in the export result response and in the FilingDetail export action feedback.

---

## 🟢 D — Admin / Documentation

### D1 — Commit `docs/` directory to git
**Source:** Session review
**Effort:** 10 min
**What:** `docs/architecture.html`, `docs/user_manual.html`, `docs/tech_handbook.html` are on disk but untracked. Add and commit.

### D2 — Update `README.md`
**Source:** Session review
**Effort:** ~1 h
**What:** README last updated 2026-03-19, before current session changes. Missing: three-tier extraction description, schema manager, label map editor, sectioned extraction flag, new Claude models (sonnet-4-6), `.env.example` reference.

### D3 — Remove or archive old `files/architecture.drawio`
**Source:** Session review
**Effort:** 5 min
**What:** `architecture_260322.drawio` supersedes `architecture.drawio`. Old file should be removed to avoid confusion. Git history preserves it.

---

## ✅ Closed / Confirmed Not Needed

| Item | Resolution |
|------|-----------|
| M6 — rename detection scope | False positive; already per-model in `schema_diff.py` |
| M7 — sections_store reload | Already implemented; `section_loader.py` has mtime-cache (lines 14, 21–30) |
| PLAN_SECTION_BY_SECTION_EXTRACTION.md | Fully implemented and feature-flagged (`SECTIONED_EXTRACTION`) |
| All HIGH + MEDIUM code quality items | Executed in session 2026-03-22 (commit `177552f`) |

---

## Priority Order for Next Session

1. Answer C1 open questions (Q1–Q6 in `PLAN_MODEL_SCALING_STRATEGY.md`) — no code needed, shapes all downstream work
2. A1 — classificationHints in schema
3. A2 — add missing models
4. B1 + B2 — three-state backend (can be done in parallel with A1/A2)
5. B3 — confirmation modal UI
6. D1 + D3 — quick admin tasks (10–15 min total)
7. D2 — README update
8. C2 + C4 — demote xlsx, add few-shot examples (after A1 validated)
9. C3 + C5 — feature matrix, export messaging
