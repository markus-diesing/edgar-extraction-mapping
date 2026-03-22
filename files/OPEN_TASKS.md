# Open Tasks

**Last updated:** 2026-03-22 (revised after PRISM expansion cadence clarification)
**Source:** Requirements audit + session review + strategic planning

Tasks are grouped by priority. Each entry notes its source document and estimated effort.

---

## 🔴 A — Critical (blocks accuracy or core workflow)

### A1 — Define `classificationHints` format spec and bring to team discussion
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 1, `CLASSIFICATION_HINTS_SPEC.md`
**Effort:** ~2 h (format design + 2 worked examples from existing models)
**What:** Draft the exact JSON structure for the `classificationHints` block — description, title_keywords, feature_indicators (drawn from 22-dimension Payout_to_Features vocabulary), discriminating_fields, counter_indicators. Provide worked examples for 1–2 existing models. Bring to the PRISM schema team so they adopt the format as they expand models weekly.
**Why this sequencing matters:** The PRISM team is adding models at ~weekly cadence. Every model added *before* the format is agreed needs to be retrofitted. The sooner the format is locked, the less backfill is needed.
**Note:** We draft the spec; the PRISM team populates it per model when they author each schema. ~15 min/model on their side.

### A2 — Dynamic schema loading in `classifier.py`
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` (consequences of weekly expansion cadence)
**Effort:** ~3 h
**What:** Refactor `classifier.py` so model names, descriptions, and classificationHints are read from `prism-v1.schema.json` at classify-time rather than being hardcoded. The classification prompt is built dynamically from whatever models the schema currently contains. A new model added to the schema is picked up automatically on the next run — no code change, no redeploy required.
**Why critical:** Without this, every weekly model addition requires a code change. With it, the pipeline absorbs new models for free.

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
**Note:** `needs_review` is also the output for filings of product types not yet covered by the schema — important during weekly expansion period.

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

### C1 — Stage 1 feature extraction prompt
**Source:** `NOTE_LLM_FUZZY_PRISM_MATCHING.md`, `files/payout_features.json`
**Effort:** ~2 h (prompt engineering + integration)
**What:** Write and integrate a structured prompt that extracts the 22-dimension feature vector from any EDGAR filing — the same dimensions as `Payout_to_Features.xlsx` (COUPON_TYPE, CALL_TYPE, DOWNSIDE_PROTECTION_TYPE, all HAS_* flags). The output is a structured JSON dict. This becomes the stable intermediate representation fed into Stage 2 (PRISM model matching), and doubles as an audit trail for every classification decision.
**Why medium (not critical):** The current two-stage classifier works without it. This replaces Stage 1 with a more principled, inspectable signal — a quality improvement, not a bug fix. Can be added after B1/B2 without disrupting the existing flow.
**Schema independence:** This prompt is entirely independent of how many PRISM models exist. It runs the same regardless of weekly schema changes.

### C2 — Demote CUSIP xlsx to optional enrichment
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 4
**Effort:** ~1 h
**What:** Make CUSIP mapping lookup a confidence *booster* rather than a hard gate. Classifier proceeds on document evidence alone when a CUSIP is not in the mapping. Xlsx contribution fades naturally as classificationHints mature.
**Dependency:** A2 (dynamic schema loading) should be complete first so the classifier is already schema-driven before the xlsx is demoted.

### C3 — Few-shot product title examples per model
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 3
**Effort:** ~1 h (content, no code)
**What:** Add 2–3 representative product title strings to each model's classificationHints block. Drawn from real approved filings. Effective because filing vocabulary matches directly.
**Dependency:** classificationHints format must be agreed (A1) and team must be onboarded to populate this field per model.

### C4 — Export validation messaging improvement
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
| C1 old — answer Q1–Q6 scaling questions | Resolved in conversation 2026-03-22; see `PLAN_MODEL_SCALING_STRATEGY.md` |
| A2 old — add 2 missing models to schema | Subsumed by PRISM team's ongoing weekly expansion; not our task |

---

## Priority Order for Next Session

1. **A1** — classificationHints format spec → bring to PRISM team discussion (2 h; highest leverage because it shapes every model added from here)
2. **A2** — dynamic schema loading in classifier.py (3 h; makes pipeline absorb weekly additions automatically)
3. **B1 + B2** — three-state backend, can run in parallel with A1/A2 (3 h combined)
4. **B3** — confirmation modal UI (5 h; follows B1+B2)
5. **C1** — Stage 1 feature extraction prompt (2 h; after B1/B2 so it feeds into a functional three-state flow)
6. **D1 + D3** — quick admin tasks (15 min total)
7. **D2** — README update (1 h)
8. **C2** — demote xlsx (1 h; after A2)
9. **C3 + C4** — few-shot examples, export messaging (after team onboarded to hints format)
