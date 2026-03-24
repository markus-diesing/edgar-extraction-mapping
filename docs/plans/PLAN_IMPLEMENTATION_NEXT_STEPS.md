# Implementation Plan — Three-State Classification, classificationHints Infrastructure, CUSIP Demotion

**Author:** Markus / Claude Code
**Date:** 2026-03-22
**Status:** Ready for execution — no further design decisions required
**Demo constraint:** The full ingest → classify → extract → approve → export flow must remain unbroken at every stage of these changes.

---

## Overview of Changes

Four distinct work items, fully mapped to source files and line numbers:

| ID | Work item | Files touched | Effort |
|----|-----------|--------------|--------|
| W1 | Three-state classification status | `classifier.py`, `database.py` | ~30 min |
| W2 | Confirm endpoint | `classify/router.py`, `api.js` | ~45 min |
| W3 | classificationHints infrastructure in classifier | `classifier.py` | ~45 min |
| W4 | CUSIP demotion to optional enrichment | `classifier.py` | ~15 min |
| W5 | Frontend: new status + confirm UI | `StatusBadge.jsx`, `FilingList.jsx`, `FilingDetail.jsx` | ~60 min |

**Recommended execution order:** W1 → W3 → W4 → W2 → W5

W1 must come before W5 (frontend needs backend status to exist). W3 and W4 are independent and can be done in any order relative to each other. W2 is a net-new endpoint with no dependencies on the others but is needed before W5's confirm button can wire up.

---

## W1 — Three-State Classification Status

### What changes and why

`_persist()` in `classify/classifier.py` currently maps to one of two statuses. The new mapping is:

```
unknown  OR  confidence < 0.60  →  needs_review           (unchanged)
0.60 ≤ confidence < 0.80        →  needs_classification_review  (NEW)
confidence ≥ 0.80               →  classified             (unchanged)
```

`CLASSIFICATION_GATE_CONFIDENCE = 0.80` already exists in `config.py` (line 88) but is unused. `CLASSIFICATION_MIN_CONFIDENCE = 0.60` (line 87) already correctly marks the floor below which `payout_type_id` is forced to `"unknown"` in `_parse_classification_response()`.

The two existing thresholds therefore already define the three bands — no new config values needed.

### Exact changes

**`backend/classify/classifier.py` — `_persist()` (lines 513–537)**

Replace lines 515–519:
```python
# CURRENT
new_status = (
    "classified"
    if result.confidence_score >= config.CLASSIFICATION_CONFIDENCE_THRESHOLD
    and result.payout_type_id != "unknown"
    else "needs_review"
)
```

With:
```python
# NEW
if result.payout_type_id == "unknown":
    new_status = "needs_review"
elif result.confidence_score >= config.CLASSIFICATION_GATE_CONFIDENCE:
    new_status = "classified"
else:
    new_status = "needs_classification_review"
```

Note: `payout_type_id == "unknown"` already implies `confidence < 0.60` (enforced in `_parse_classification_response()`), so no double-check needed.

**`backend/database.py` — comment on line 81**

Update the status comment from:
```python
# ingested | classified | extracted | needs_review | approved | exported
```
to:
```python
# ingested | classified | needs_classification_review | extracted | needs_review | approved | exported
```

No SQLite migration required — `status` is a plain `TEXT` column with no enum constraint.

### Demo-safety

`needs_classification_review` is a new string value — it cannot break any existing filing record. Filings already in the database stay in their current status. New filings with ≥0.80 confidence continue to receive `classified` exactly as before. Only the medium-confidence band (0.60–0.80) lands in the new state.

---

## W2 — Confirm Classification Endpoint

### What it does

`POST /api/classify/{filing_id}/confirm` provides a human sign-off path for filings in `needs_classification_review`. It can optionally accept a corrected model (acting as a lightweight override), or simply confirm the existing model as correct.

On success:
1. Sets `status = "classified"`
2. Sets `classification_confidence = 1.0` (human-confirmed, overrides classifier score)
3. Creates a `ClassificationFeedback` record (feeds the few-shot feedback loop)

### Exact changes

**`backend/classify/router.py`** — add after the existing `classify()` endpoint:

New request model:
```python
class ConfirmClassificationRequest(BaseModel):
    confirmed_by: str = "reviewer"
    payout_type_id: str | None = None   # None → confirm the existing model unchanged
```

New response model:
```python
class ConfirmClassificationResponse(BaseModel):
    filing_id: str
    payout_type_id: str
    status: str
    confirmed_by: str
```

New route:
```python
@router.post("/classify/{filing_id}/confirm", response_model=ConfirmClassificationResponse)
def confirm_classification(filing_id: str, body: ConfirmClassificationRequest):
    """
    Human confirmation of a needs_classification_review filing.
    Promotes it to 'classified'. Optionally corrects the payout_type_id.
    """
    from datetime import datetime, timezone
    import uuid

    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if filing.status != "needs_classification_review":
            raise HTTPException(
                status_code=422,
                detail=f"Filing is '{filing.status}', not 'needs_classification_review'"
            )

        original_model = filing.payout_type_id
        confirmed_model = body.payout_type_id or original_model
        now = datetime.now(timezone.utc).isoformat()

        # Validate against known models
        known = schema_loader.list_models()
        if confirmed_model not in known and confirmed_model != "unknown":
            raise HTTPException(status_code=422, detail=f"Unknown model: {confirmed_model}")

        filing.payout_type_id = confirmed_model
        filing.classification_confidence = 1.0
        filing.status = "classified"
        filing.classified_at = now

        feedback = database.ClassificationFeedback(
            id=str(uuid.uuid4()),
            filing_id=filing_id,
            original_payout_type=original_model or "unknown",
            corrected_payout_type=confirmed_model,
            correction_reason="human confirmation via review gate",
            corrected_by=body.confirmed_by,
            corrected_at=now,
            used_as_example=False,
        )
        session.add(feedback)
        session.commit()

    log.info(
        "Classification confirmed: filing=%s  model=%s  by=%s",
        filing_id, confirmed_model, body.confirmed_by,
    )
    return ConfirmClassificationResponse(
        filing_id=filing_id,
        payout_type_id=confirmed_model,
        status="classified",
        confirmed_by=body.confirmed_by,
    )
```

**`frontend/src/api.js`** — add one line to the `api` object:

```javascript
confirmClassification: (id, body) => call('POST', `/classify/${id}/confirm`, body),
```

### Demo-safety

This is a net-new endpoint. No existing code paths are touched. It can only be called by the new frontend confirm button, which only appears when status is `needs_classification_review`.

---

## W3 — classificationHints Infrastructure in Classifier

### What it does

`_get_model_descriptions()` in `classifier.py` currently reads only the top-level `description` field from each model entry. When a model has no `description`, the model list shows just its name with no context.

The change makes this function also read `classificationHints` and produce a richer, structured description for the prompt. If no `classificationHints` block exists (all current 9 models), it gracefully falls back to the existing `description` — zero regression.

When the PRISM team adds `classificationHints` to a model (after the format spec is agreed), the classifier automatically picks it up on the next schema load. No code change, no redeploy.

### Exact changes

**`backend/classify/classifier.py` — `_get_model_descriptions()` (lines 358–366)**

Replace the entire function:

```python
def _get_model_descriptions(schema: dict[str, Any]) -> dict[str, str]:
    """
    Return {model_name: description_text} for all models in the schema.

    If a model has a 'classificationHints' block, formats it into a structured
    description that includes discriminating features and counter-indicators.
    Falls back to the plain 'description' string for models without hints.
    """
    result: dict[str, str] = {}
    for entry in schema.get("oneOf", []):
        const = entry.get("properties", {}).get("model", {}).get("const")
        if not const:
            continue

        hints = entry.get("classificationHints")
        if hints:
            # Build structured description from hints block
            parts: list[str] = []

            if hints.get("description"):
                parts.append(hints["description"])

            features = hints.get("discriminating_features", [])
            if features:
                feat_lines = "; ".join(features[:4])   # cap at 4 to control prompt length
                parts.append(f"Key features: {feat_lines}.")

            counters = hints.get("counter_indicators", [])
            if counters:
                ctr_lines = "; ".join(counters[:3])    # cap at 3
                parts.append(f"Not this model if: {ctr_lines}.")

            keywords = hints.get("title_keywords", [])
            if keywords:
                parts.append(f"Typical title terms: {', '.join(keywords[:6])}.")

            result[const] = " | ".join(parts)
        else:
            # Fallback: use the plain schema description if present
            result[const] = entry.get("description", "")

    return result
```

No other function changes are needed. The descriptions dict flows unchanged into `_model_list_text()` and from there into both stage-1 and stage-2 prompts.

### Demo-safety

Pure additive. All 9 current models lack a `classificationHints` block, so they all take the `else` branch and behave identically to before. No prompt content changes for any currently classifiable filing.

When the PRISM team starts adding `classificationHints`, the enriched descriptions improve accuracy automatically — without any deployment cycle.

---

## W4 — CUSIP Demotion to Optional Enrichment

### What changes

The prompt language in both `_build_stage1_prompt()` and `_build_stage2_prompt()` is strengthened to make clear that the CUSIP mapping is a supplementary reference, not an authoritative prior.

No structural code changes. The lookup in `classify/router.py` remains. The `load_cusip_mapping()` in `schema_loader.py` already handles a missing file gracefully (returns `{}`). The demotion is entirely in the prompt framing.

### Exact changes

**`backend/classify/classifier.py` — `_build_stage1_prompt()` (lines 195–208)**

Replace the `hint_section` block:

```python
# CURRENT
if cusip_hint and cusip_hint_in_schema:
    hint_section = (
        f"\nNote: The CUSIP lookup table suggests this may be a **{cusip_hint}** — "
        "treat this as a prior but verify independently.\n"
    )
elif cusip_hint and not cusip_hint_in_schema:
    hint_section = (
        f"\nNote: The CUSIP lookup table suggests this product is a "
        f"**{cusip_hint}**, but that model does not yet exist in the current schema. "
        "If the filing clearly belongs to that product family and no listed model "
        "fits well, return 'unknown' — do not force a wrong match.\n"
    )
```

```python
# NEW
if cusip_hint and cusip_hint_in_schema:
    hint_section = (
        f"\nSupplementary reference: A historical mapping file associates this CUSIP "
        f"with **{cusip_hint}**. Use this as weak background context only — "
        "base your classification on the document content, not on this reference. "
        "If the document evidence points to a different model, follow the document.\n"
    )
elif cusip_hint and not cusip_hint_in_schema:
    hint_section = (
        f"\nSupplementary reference: A historical mapping file associates this CUSIP "
        f"with **{cusip_hint}**, which is not in the current schema. "
        "Ignore this reference for classification purposes and use the document content only. "
        "Return 'unknown' only if no listed model fits the document evidence.\n"
    )
```

Apply the equivalent change to `_build_stage2_prompt()` (lines 252–260), same pattern.

### Demo-safety

The CUSIP hint was never a hard gate — the classifier always had full authority to override it. This change makes that explicit in the prompt, reducing the risk of CUSIP hints causing false-positive classifications when a product has been reclassified but the xlsx has not been updated. The change has no effect on filings that have no CUSIP, no mapping entry, or whose CUSIP maps correctly.

---

## W5 — Frontend Changes

### W5a — StatusBadge.jsx

Add one entry to `STATUS_STYLES`:

```javascript
needs_classification_review: 'bg-[#fff3e0] text-[#8a5c00] border-[#f59e0b]',
```

This uses an amber/orange tone — distinct from:
- `needs_review` (yellow-gold `#fef8e7` / `#7a5a00`) — same family, but visually different
- `classified` (blue `#e8eefe`) — clearly different intent

The `StatusBadge` renders the status string with underscores replaced by spaces — `needs classification review` — which is self-explanatory in the UI.

### W5b — FilingList.jsx

Add `'needs_classification_review'` to the `STATUSES` constant (line 4):

```javascript
// CURRENT
const STATUSES = ['', 'ingested', 'classified', 'needs_review', 'extracted', 'approved', 'exported']

// NEW
const STATUSES = ['', 'ingested', 'classified', 'needs_classification_review', 'needs_review', 'extracted', 'approved', 'exported']
```

No other changes needed — the filter select and list rendering are fully data-driven.

### W5c — FilingDetail.jsx

**Four changes within this file:**

**1. Extend `canExtract` and `canResetClassify` (lines 208–213)**

```javascript
// CURRENT
const canExtract       = ['classified', 'needs_review'].includes(status)
const canResetClassify = ['classified', 'needs_review'].includes(status)

// NEW
const canExtract       = ['classified', 'needs_classification_review', 'needs_review'].includes(status)
const canResetClassify = ['classified', 'needs_classification_review', 'needs_review'].includes(status)
```

This is the critical demo-safety line. `needs_classification_review` must allow extraction so the demo flow is never blocked.

**2. Add `doConfirm` handler** (add alongside the other `do*` handlers, around line 159):

```javascript
const doConfirm = () => run('confirm', () =>
  api.confirmClassification(filingId, { confirmed_by: 'reviewer' })
)
```

**3. Add confirm banner** (add inside the action bar block, after the override panel, around line 320):

```jsx
{status === 'needs_classification_review' && !showOverride && (
  <div className="mt-3 p-3 bg-amber-50 border border-amber-200 rounded flex items-start gap-3">
    <span className="text-amber-500 text-base mt-0.5">⚠</span>
    <div className="flex-1 min-w-0">
      <p className="text-xs font-semibold text-amber-800">
        Classification confidence is medium ({(filing.classification_confidence * 100).toFixed(0)}%)
      </p>
      <p className="text-xs text-amber-700 mt-0.5">
        The classifier identified this as <strong>{filing.payout_type_id}</strong> but with
        reduced confidence. Review the filing below, then confirm or correct the model.
      </p>
    </div>
    <div className="flex gap-2 shrink-0">
      <ActionButton
        label={action === 'confirm' ? 'Confirming…' : '✓ Confirm'}
        onClick={doConfirm}
        disabled={!!action}
        variant="warning"
        small
      />
    </div>
  </div>
)}
```

**4. Add status bar message for `needs_classification_review` (lines 415–422)**

Add a new branch in the status bar text block:

```javascript
// add after the 'classified' branch and before 'needs_review'
: status === 'needs_classification_review'
? `Classified as ${filing.payout_type_id} with medium confidence (${(filing.classification_confidence * 100).toFixed(0)}%) — confirm or override before extraction.`
```

Full updated block (excerpt):
```javascript
status === 'ingested'
  ? 'Raw filing preview — click Classify above to identify the PRISM model.'
  : status === 'classified'
  ? `Classified as ${filing.payout_type_id} (${(filing.classification_confidence * 100).toFixed(0)}% conf.) — click Extract to pull all PRISM fields.`
  : status === 'needs_classification_review'
  ? `Classified as ${filing.payout_type_id} with medium confidence (${(filing.classification_confidence * 100).toFixed(0)}%) — confirm or override before extraction.`
  : status === 'needs_review'
  ? 'Low-confidence classification — review the filing below, then use "Set Model" to override or click Extract.'
  : status === 'exported'
  ? 'Filing has been exported.'
  : ''
```

---

## Dependency Graph and Execution Order

```
W1 (three-state _persist)
  └── required before W5 (frontend needs the status to exist in DB)

W3 (classificationHints infra)
  └── independent — can run any time

W4 (CUSIP demotion)
  └── independent — pure prompt text change

W2 (confirm endpoint + api.js)
  └── required before W5c's confirm button can wire up

W5 (frontend)
  └── requires W1 (status value) and W2 (confirm endpoint)
  └── W5a, W5b, W5c are independent of each other within W5
```

Suggested execution order within a single session:
1. W3 (classifier hints infra) — pure additive, zero risk, validate first
2. W4 (CUSIP demotion) — two string changes, zero risk
3. W1 (three-state persist) — backend logic, test with a classify call
4. W2 (confirm endpoint + api.js) — net-new route, test directly
5. W5 (all frontend changes) — test full UI flow

---

## Demo-Safety Checklist

The following must hold true after all changes are applied. Each item maps to the primary risk point:

| Check | Risk point | How it holds |
|-------|-----------|-------------|
| High-confidence filing → `classified` → Extract works | W1 three-state logic | `≥ 0.80` → `classified` unchanged |
| Medium-confidence filing → Extract still works (demo flow) | W5c `canExtract` | Added `needs_classification_review` to the list |
| Low-confidence / unknown → `needs_review` → Extract still works | W1 + W5c | Both paths preserved |
| Existing DB filings unaffected | W1 DB migration | No migration, no data change, status column is plain TEXT |
| CUSIP-less filings unaffected | W4 CUSIP demotion | `cusip_hint` is `None` → hint_section is `""` → no change |
| Models without `classificationHints` prompt unchanged | W3 hints infra | `else` branch returns `entry.get("description", "")` — identical to current |
| Confirm button only appears in the right state | W5c | Gated on `status === 'needs_classification_review'` |
| Confirm endpoint rejects wrong-state filings | W2 | Returns 422 if status is not `needs_classification_review` |

---

## What This Does Not Change

- `schema_loader.py` — no changes. Schema loading is already dynamic.
- `extract/` — no changes. Extraction is triggered from the UI independently of classification gate.
- `export/` — no changes.
- `config.py` — no changes. `CLASSIFICATION_GATE_CONFIDENCE = 0.80` is already defined.
- `database.py` structure — no migration. The status column is free-text.
- Any existing filing records — untouched.
- The `classify-override` endpoint — retained as-is. The new confirm endpoint is additive.

---

## After Execution: What Improves

**Immediately (with current 9 models, no schema changes):**
- Filings in the 0.60–0.80 confidence band get a visible, actionable status instead of silently landing in `needs_review`
- The CUSIP mapping no longer anchors the classifier to potentially stale entries
- The confirm button provides a lightweight review path distinct from the heavier `Set Model` override

**Automatically, as the PRISM team adds `classificationHints` to models:**
- The classification prompt gets richer, structured context for each model — no code deployment needed
- Classification accuracy improves for models with full hints blocks
- Counter-indicators reduce false positives between structurally similar models

**Automatically, as new models are added to the schema:**
- New models appear in the classifier's model list without code changes (already the case — confirmed by reading `list_models()` which is fully dynamic)
- If the new model has `classificationHints`, full prompt enrichment is immediate
