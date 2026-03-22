# Open Tasks

**Last updated:** 2026-03-22 (post-implementation update — commit 48202e5)
**Source:** Requirements audit + session review + strategic planning

Tasks are grouped by priority. Each entry notes its source document and estimated effort.

---

## 🔴 A — Critical (blocks accuracy or core workflow)

### A1 — Define `classificationHints` format spec → team discussion
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md`, `SPEC_CLASSIFICATION_HINTS_FORMAT.md`
**Effort:** Spec drafted ✅ — team meeting TBD
**What:** `SPEC_CLASSIFICATION_HINTS_FORMAT.md` is the ready deliverable. Bring to the PRISM schema team so they adopt the format as they add models at weekly cadence.
**Infrastructure ready:** `_get_model_descriptions()` in `classifier.py` already reads `classificationHints` and formats it into the prompt. When the team adds the block to any model, the classifier picks it up automatically — no code change required.
**Blocked on:** Team discussion / agreement on format.

### A2 — Dynamic schema loading ✅ (already in place)
**Resolution:** `list_models()` and `_get_model_descriptions()` in `schema_loader.py` and `classifier.py` are already fully dynamic — they read the current schema at classify-time. New models added to `prism-v1.schema.json` are automatically picked up. No action needed beyond ensuring the team follows the schema update workflow (fetch → diff → activate via Admin panel).

---

## 🟠 B — High Priority (completes partially-specified workflow)

### B1 — Three-state classification status ✅ DONE (commit 48202e5)
Three-state `_persist()` logic implemented in `classifier.py`:
- `≥ 0.80` → `classified`
- `0.60–0.79` → `needs_classification_review`
- `unknown` → `needs_review`

### B2 — `POST /api/classify/{id}/confirm` endpoint ✅ DONE (commit 48202e5)
New route in `classify/router.py`. Promotes `needs_classification_review` → `classified`, sets confidence to 1.0, creates `ClassificationFeedback` record. Returns 422 if filing is in wrong state.

### B3 — Frontend: confirmation UI and status wiring ✅ DONE (commit 48202e5)
- `StatusBadge.jsx` — amber/orange style for `needs_classification_review`; fixed underscore replacement for multi-word labels
- `FilingList.jsx` — new status in filter dropdown
- `FilingDetail.jsx` — confirm banner, `doConfirm` handler, `canExtract` includes new state, status bar message and colour
- `api.js` — `confirmClassification()` method

---

## 🟡 C — Medium Priority (strategic / scaling)

### C1 — CUSIP xlsx demotion to optional enrichment ✅ DONE (commit 48202e5)
Prompt language in both stage-1 and stage-2 prompts changed to treat CUSIP hint as "supplementary reference only — base classification on document content." No structural change; CUSIP lookup still happens but no longer anchors the classifier.

### C2 — Stage 1 feature extraction prompt (22-dimension vector)
**Source:** `NOTE_LLM_FUZZY_PRISM_MATCHING.md`, `files/payout_features.json`
**Effort:** ~2 h
**What:** Write and integrate a structured prompt that extracts the 22-dimension feature vector (COUPON_TYPE, CALL_TYPE, DOWNSIDE_PROTECTION_TYPE, all HAS_* flags) from any filing as JSON. Becomes stable intermediate representation + audit trail.
**Status:** Not yet started. Independent of schema content.

### C3 — Few-shot product title examples per model
**Source:** `PLAN_MODEL_SCALING_STRATEGY.md` Option 3, `SPEC_CLASSIFICATION_HINTS_FORMAT.md`
**Effort:** ~1 h content
**What:** Add `title_keywords` and representative example titles to each model's `classificationHints` block. Infrastructure to consume them is already in place (the `title_keywords` field is read by `_get_model_descriptions()`).
**Dependency:** A1 team discussion complete.

### C4 — Export validation messaging improvement
**Source:** `REQUIREMENTS.md` FR-6.5
**Effort:** ~1 h
**What:** Surface schema validation errors more clearly in the export response and FilingDetail export action feedback.

---

## 🟢 D — Admin / Documentation

### D1 — Commit `docs/` directory to git ✅ (committed in 1dfa89f)

### D2 — Update `README.md`
**Effort:** ~1 h
**What:** Missing: three-state classification gate, classificationHints infrastructure, CUSIP demotion, confirm endpoint, new status values.

### D3 — Remove or archive old `files/architecture.drawio`
**Effort:** 5 min
**What:** `architecture_260322.drawio` supersedes `architecture.drawio`. Remove to avoid confusion.

---

## ✅ Closed / Resolved

| Item | Resolution |
|------|-----------|
| M6 — rename detection scope | False positive; already per-model in `schema_diff.py` |
| M7 — sections_store reload | Already implemented; `section_loader.py` has mtime-cache |
| PLAN_SECTION_BY_SECTION_EXTRACTION.md | Fully implemented and feature-flagged |
| All HIGH + MEDIUM code quality items | Executed in session 2026-03-22 (commit `177552f`) |
| C1 old — answer Q1–Q6 scaling questions | Resolved in conversation 2026-03-22 |
| A2 old — add 2 missing models to schema | Subsumed by PRISM team's ongoing weekly expansion |
| B1 — three-state classification status | Implemented (commit 48202e5) |
| B2 — confirm endpoint | Implemented (commit 48202e5) |
| B3 — frontend status + confirm UI | Implemented (commit 48202e5) |
| C1 — CUSIP demotion | Implemented as W4 (commit 48202e5) |
| A2 — dynamic schema loading | Already in place — schema_loader.py is fully dynamic |
| D1 — commit docs/ | Done (commit 1dfa89f) |

---

## Priority Order for Next Session

1. **A1** — classificationHints format spec to team meeting (spec ready, action is scheduling)
2. **C2** — Stage 1 feature extraction prompt (22-dimension vector, unblocked)
3. **D2** — README update (reflects current state)
4. **D3** — Remove old drawio file (5 min)
5. **C3** — Few-shot examples (after A1 team agreement)
6. **C4** — Export validation messaging
