# Plan: Classification Review Gate + Workflow

*Status: Planning — partially implemented*
*Author: Architecture session 2026-03-18*
*Based on: Motive AI insight #6 — "classification review gate before extraction"*

---

## Section 1: Current State vs Target State

### Current State

After `classify_filing()` runs, `_persist()` (in `backend/classify/classifier.py`, lines 412–436) sets the filing status to either `"classified"` or `"needs_review"`:

- `"classified"` — confidence >= `CLASSIFICATION_CONFIDENCE_THRESHOLD` (0.75) AND model != "unknown"
- `"needs_review"` — everything else (confidence < 0.75, or model = "unknown")

In `backend/extract/router.py`, the `POST /api/extract/{filing_id}` endpoint (lines 93–126) allows extraction when `filing.status in ("classified", "needs_review", "extracted")`. This means a filing can proceed to extraction even if confidence is below the gate threshold, **unless** the confidence is also below `CLASSIFICATION_GATE_CONFIDENCE = 0.80`.

**What is already implemented (as of 2026-03-18):**
- `config.CLASSIFICATION_GATE_CONFIDENCE = 0.80` exists in `backend/config.py` (line 48).
- The extraction gate check is live in `backend/extract/router.py` lines 105–117: if `classification_confidence < 0.80` AND status is not already `"extracted"`, the endpoint returns HTTP 400 with an error message directing the user to `POST /api/classify/{filing_id}/confirm`.

**What is NOT yet implemented:**
1. The `POST /api/classify/{filing_id}/confirm` endpoint does not exist in `backend/classify/router.py`.
2. The `"needs_classification_review"` status is referenced in the error message but never set — `_persist()` only sets `"classified"` or `"needs_review"`.
3. There is no frontend UI for the review/confirmation flow.
4. The `FilingList.jsx` `STATUSES` constant does not include `"needs_classification_review"`.
5. `StatusBadge.jsx` has no style for `"needs_classification_review"`.

### Target State

```
classify_filing() runs
        ↓
    confidence >= 0.80  ──────────────→  status = "classified"  → extraction allowed immediately
        ↓
    confidence 0.60–0.79                 status = "needs_classification_review"
        ↓                                        ↓
    (human reviews in UI)       POST /api/classify/{id}/confirm
        ↓                                        ↓
    confirm correct model       ────────→  status = "classified"  → extraction allowed
        ↓
    correct model selection     ────────→  ClassificationFeedback row written
                                           status = "classified"  → extraction allowed
```

The extraction gate in `extract/router.py` remains as-is (already implemented). The missing piece is everything upstream: setting the correct status, providing the confirm endpoint, and building the UI.

---

## Section 2: Status Machine Changes

### Current Status Values (in `database.py` line 80 comment)

```
ingested → classified | needs_review → extracted → approved → exported
```

### Updated Status Values

```
ingested
  → classified                    (confidence >= 0.80, model != "unknown")
  → needs_classification_review   (confidence 0.60–0.79, model != "unknown")
  → needs_review                  (model = "unknown", or confidence < 0.60)

needs_classification_review
  → classified                    (via POST /api/classify/{id}/confirm with same or corrected model)

classified
  → extracted                     (via POST /api/extract/{id})
  → needs_classification_review   (if re-classify drops confidence; rare)

extracted → approved → exported   (unchanged)
```

### Full Updated Status Transition Diagram

```
                    ┌─────────────────────────────────────────────────────────────────┐
                    │                     INGESTED                                    │
                    │  POST /api/classify/{id}                                        │
                    └─────────────┬─────────────┬─────────────────────────────────────┘
                                  │             │                          │
                            conf >= 0.80    conf 0.60–0.79           conf < 0.60
                            model known     model known               or unknown
                                  │             │                          │
                                  ▼             ▼                          ▼
                           CLASSIFIED   NEEDS_CLASSIFICATION_REVIEW   NEEDS_REVIEW
                                  │             │                          │
                           (extract          POST /api/classify/{id}/confirm
                           allowed)          (human confirms or corrects)
                                  │             │
                                  │             ▼
                                  │         CLASSIFIED ─────────────────────────────┐
                                  │                                                  │
                                  └──────────────────────────────────────────────────┤
                                                                                     │
                                                                                     ▼
                                                                               EXTRACTED
                                                                                     │
                                                                                     ▼
                                                                               APPROVED
                                                                                     │
                                                                                     ▼
                                                                               EXPORTED
```

### Status Meaning Reference

| Status | Meaning | Extraction Allowed? |
|---|---|---|
| `ingested` | HTML downloaded, not yet classified | No |
| `classified` | Classified with confidence >= 0.80 | Yes |
| `needs_classification_review` | Classified but confidence 0.60–0.79; awaits human confirmation | No (blocked by gate) |
| `needs_review` | Unknown model or confidence < 0.60; requires investigation | No (blocked by gate) |
| `extracted` | Fields extracted; awaiting expert review | Re-extract only |
| `approved` | Expert review complete | Export only |
| `exported` | JSON exported | Done |

---

## Section 3: Required Code Changes

### `backend/classify/classifier.py` — `_persist()` function (lines 412–436)

**Current logic (lines 415–419):**
```python
new_status = (
    "classified"
    if result.confidence_score >= config.CLASSIFICATION_CONFIDENCE_THRESHOLD
    and result.payout_type_id != "unknown"
    else "needs_review"
)
```

**Replacement logic:**

```python
if result.payout_type_id == "unknown" or result.confidence_score < config.CLASSIFICATION_MIN_CONFIDENCE:
    new_status = "needs_review"
elif result.confidence_score >= config.CLASSIFICATION_GATE_CONFIDENCE:
    new_status = "classified"
else:
    # confidence is between CLASSIFICATION_MIN_CONFIDENCE (0.60) and
    # CLASSIFICATION_GATE_CONFIDENCE (0.80) — requires human confirmation
    new_status = "needs_classification_review"
```

This uses two existing constants from `config.py`:
- `CLASSIFICATION_MIN_CONFIDENCE = 0.60` (line 47) — below this → `needs_review`
- `CLASSIFICATION_GATE_CONFIDENCE = 0.80` (line 48) — at or above this → `classified`
- Between 0.60 and 0.80 → `needs_classification_review`

**Important**: `CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.75` (line 46) controls the stage-1 → stage-2 fallback trigger and is unrelated to the status assignment. Do not change that logic.

### `backend/classify/router.py` — new `POST /api/classify/{filing_id}/confirm` endpoint

Add after the existing `classify` endpoint (current line 34):

```python
class ConfirmClassificationRequest(BaseModel):
    confirmed_payout_type_id: str  # the model the reviewer agrees is correct
    correction_reason: str | None = None  # required when correcting, optional when confirming

class ConfirmClassificationResponse(BaseModel):
    filing_id: str
    payout_type_id: str
    status: str
    feedback_recorded: bool

@router.post("/classify/{filing_id}/confirm", response_model=ConfirmClassificationResponse)
def confirm_classification(filing_id: str, body: ConfirmClassificationRequest):
    """
    Human-confirms (or corrects) the classification of a filing
    that is in 'needs_classification_review' status.

    - If body.confirmed_payout_type_id matches the existing payout_type_id:
      Records no ClassificationFeedback row (no correction). Sets status to 'classified'.
    - If body.confirmed_payout_type_id differs:
      Records a ClassificationFeedback row with the correction.
      Updates filing.payout_type_id to the confirmed value.
      Sets status to 'classified'.
    """
```

**Implementation steps inside the endpoint:**

1. Load the `Filing` row. Validate `filing.status == "needs_classification_review"` — raise HTTP 422 otherwise (guard against double-confirm).
2. Validate `body.confirmed_payout_type_id` is in `schema_loader.list_models()` — raise HTTP 422 if not.
3. Open a session:
   a. If `body.confirmed_payout_type_id != filing.payout_type_id`:
      - Create a `database.ClassificationFeedback` row:
        - `original_payout_type = filing.payout_type_id`
        - `corrected_payout_type = body.confirmed_payout_type_id`
        - `correction_reason = body.correction_reason`
        - `corrected_by = "manual_review"` (placeholder until auth is added)
      - Update `filing.payout_type_id = body.confirmed_payout_type_id`
      - `feedback_recorded = True`
   b. In all cases: `filing.status = "classified"`
   c. `session.commit()`
4. Return `ConfirmClassificationResponse`.

### `backend/extract/router.py` — gate logic (already implemented)

The gate check at lines 105–117 is complete. No code changes needed here.

One documentation note: update the `status not in (...)` check at line 100 to include `"needs_classification_review"` in the list of statuses that receive the gate message rather than the generic "must be classified first" message:

```python
if filing.status not in ("classified", "needs_review", "needs_classification_review", "extracted"):
    raise HTTPException(
        status_code=422,
        detail=f"Filing must be classified first (current status: {filing.status})",
    )
```

This allows the gate check (lines 107–117) to apply to `needs_classification_review` filings and return the descriptive 400 error rather than a confusing 422.

### `database.py` — update status comment

Update the comment on line 80 from:
```python
# ingested | classified | extracted | needs_review | approved | exported
```
to:
```python
# ingested | classified | needs_classification_review | needs_review
# | extracted | approved | exported
```

No migration needed — the status column is a plain string and SQLite stores any value.

### `frontend/src/components/FilingDetail.jsx`

**Three changes required:**

**1. Update `canExtract` condition (line 172):**

```javascript
// Current:
const canExtract = ['classified', 'needs_review'].includes(status)

// Replace with:
const canExtract = ['classified', 'needs_review', 'needs_classification_review'].includes(status)
```

This allows the Extract button to appear for `needs_classification_review` filings. The backend gate will block the actual extraction with a descriptive error, which will be shown in the `error` state (existing `{error && ...}` block at lines 232–236). The user sees the error and knows to confirm classification first.

**Alternatively** (cleaner UX), hide the Extract button for `needs_classification_review` and instead show only a "Confirm Classification" button:

```javascript
const canExtract          = ['classified', 'needs_review'].includes(status)
const needsClassReview    = status === 'needs_classification_review'
const canConfirmClass     = needsClassReview
```

Then add in the action buttons section (after line 214):
```jsx
{canConfirmClass && (
  <ActionButton
    label={action === 'confirmClass' ? 'Confirming…' : 'Confirm Classification'}
    onClick={doConfirmClass}
    disabled={!!action}
    variant="warning"
  />
)}
```

**2. Add "Confirm Classification" button handler:**

In the `doXxx` function block (lines 135–145), add:

```javascript
const doConfirmClass = () => {
  // Opens the confirmation modal (see Section 4 for modal design)
  setShowConfirmModal(true)
}
```

Add `useState` for modal: `const [showConfirmModal, setShowConfirmModal] = useState(false)`.

**3. Add classification details display for `needs_classification_review` status:**

Below the existing `{filing.payout_type_id && ...}` line (line 203), add a warning block that shows when confirmation is needed:

```jsx
{status === 'needs_classification_review' && (
  <div className="mt-2 bg-amber-50 border border-amber-200 rounded px-3 py-2 text-xs text-amber-800">
    <strong>Classification requires confirmation</strong> — confidence{' '}
    {filing.classification_confidence != null
      ? `${(filing.classification_confidence * 100).toFixed(0)}%`
      : 'unknown'}{' '}
    is below the {Math.round(0.80 * 100)}% gate threshold.
    {filing.classification_title_excerpt && (
      <p className="mt-1 italic">"{filing.classification_title_excerpt}"</p>
    )}
  </div>
)}
```

### `frontend/src/components/FilingList.jsx`

**1. Add `needs_classification_review` to the STATUSES constant (line 4):**

```javascript
const STATUSES = [
  '', 'ingested', 'classified', 'needs_classification_review',
  'needs_review', 'extracted', 'approved', 'exported'
]
```

This makes the new status available in the status filter dropdown.

**2. No other changes** to `FilingList.jsx` — the `StatusBadge` component renders the status text, and `classification_confidence` is already shown as a percentage (line 130).

### `frontend/src/components/StatusBadge.jsx`

Add a new entry to `STATUS_STYLES` (after line 5):

```javascript
needs_classification_review: 'bg-orange-100 text-orange-800 border-orange-300',
```

The rendered text will be `"needs classification review"` (the `replace('_', ' ')` at line 20 handles the first underscore only — the second underscore will remain). To fix the display label, update line 20:

```javascript
{status?.replace(/_/g, ' ')}
```

This changes all underscores to spaces. Verify this doesn't break any existing status labels (`needs_review` becomes `"needs review"` — acceptable).

---

## Section 4: "Confirm Classification" UI Flow

### Where the Button Appears

The "Confirm Classification" button appears in the `FilingDetail` header action button row (the same `flex` div as Classify/Extract/Approve, lines 208–215) **only** when `filing.status === 'needs_classification_review'`.

The Extract button is hidden for this status — replaced entirely by "Confirm Classification". This prevents the user from accidentally hitting Extract and seeing the gate error.

### What the Confirmation Modal Shows

The modal is a simple overlay dialog rendered inside `FilingDetail`. It shows:

1. **Detected model** — `filing.payout_type_id` (e.g., `yieldEnhancementBarrierCoupon`)
2. **Confidence score** — e.g., `74%` (shown in amber because it is below the 80% gate)
3. **Product title excerpt** — `filing.classification_title_excerpt` (verbatim text from page 1, e.g., "Capped Barrier Notes Linked to the S&P 500 Index")
4. **Product features** — parsed from `filing.classification_product_features` (JSON string stored in DB):
   - `type`: e.g., `"autocall barrier note"`
   - `features`: e.g., `["barrier", "contingent coupon"]`
   - `underlyings`: e.g., `["S&P 500 Index"]`

### Modal Actions

The modal has three interactive elements:

**1. "Confirm: [model name]" button (green)**
- User agrees the detected model is correct.
- Calls `POST /api/classify/{filing_id}/confirm` with `{confirmed_payout_type_id: filing.payout_type_id}`.
- On success: closes modal, refreshes filing data — status becomes `classified`.
- The Extract button then becomes available.

**2. "Select a different model" dropdown + "Confirm correction" button**
- A `<select>` populated with all models from the PRISM schema (load via existing `GET /api/health` which returns `prism_models`, or add a `GET /api/models` endpoint).
- User selects the correct model.
- A text input for `correction_reason` (required when model differs).
- "Confirm correction" calls `POST /api/classify/{filing_id}/confirm` with `{confirmed_payout_type_id: selectedModel, correction_reason: reason}`.
- On success: closes modal, refreshes. A `ClassificationFeedback` row is written.

**3. "Cancel" button (ghost)**
- Closes the modal without any API call.
- Status remains `needs_classification_review`.

### API call from the modal

```javascript
const doConfirmSubmit = async (confirmedModel, reason) => {
  await api.confirmClassification(filingId, {
    confirmed_payout_type_id: confirmedModel,
    correction_reason: reason || null,
  })
  setShowConfirmModal(false)
  await load()
  onFilingUpdated()
}
```

Add `confirmClassification(filingId, body)` to `frontend/src/api.js` alongside the existing `classify()` method:

```javascript
confirmClassification: (id, body) =>
  post(`/classify/${id}/confirm`, body),
```

---

## Section 5: Batch Confirmation Workflow

### Context

With the expanded ~78-filing dataset, a significant fraction will land at confidence 0.60–0.79 (below the 0.80 gate). Based on the 24-CUSIP batch results, roughly 30–40% of filings fell into `needs_review` territory. With the new gate threshold, a portion of those will now be `needs_classification_review` (those with a non-unknown model and confidence 0.60–0.79) rather than `needs_review`.

Reviewing 20–30 filings one at a time via the modal is workable but slow. The following list-view workflow makes batch confirmation efficient.

### Filtered List View

In `FilingList.jsx`, the existing status filter dropdown (line 55) will now include `"needs_classification_review"` (added in Section 3). Selecting this filter shows only the filings awaiting confirmation.

The list item (lines 105–137) currently shows:
- CUSIP
- `issuer_name`
- `payout_type_id` (model)
- `StatusBadge`
- `classification_confidence` percentage

For `needs_classification_review` filings, add a third line below the model showing the `classification_title_excerpt` (truncated to ~60 chars). This lets the reviewer see the product name without clicking into the detail view:

```jsx
{f.status === 'needs_classification_review' && f.classification_title_excerpt && (
  <p className="text-xs text-amber-700 truncate mt-0.5 italic">
    {f.classification_title_excerpt}
  </p>
)}
```

Note: `classification_title_excerpt` is already returned by `GET /api/filings` — check whether the filings list endpoint exposes this field. If not, add it to the `FilingOut` response model in `backend/ingest/router.py` (or wherever the filings list endpoint lives).

### Quick Confirm/Reject in List (Optional Enhancement)

For even faster batch review, add inline quick-action buttons directly in each list item row for `needs_classification_review` filings. A "Quick Confirm" button that calls `POST /api/classify/{id}/confirm` with the existing `payout_type_id` without opening the modal.

```jsx
{f.status === 'needs_classification_review' && (
  <button
    onClick={(e) => { e.stopPropagation(); onQuickConfirm(f.id, f.payout_type_id) }}
    className="text-xs bg-green-100 text-green-700 border border-green-300 rounded px-1.5 py-0.5 hover:bg-green-200"
    title="Confirm this classification"
  >
    ✓
  </button>
)}
```

`onQuickConfirm` is a new prop passed down from `App.jsx` that:
1. Calls `api.confirmClassification(filingId, { confirmed_payout_type_id: payoutTypeId })`.
2. Calls `onRefresh()` to reload the filing list.

This allows the reviewer to scan through all `needs_classification_review` filings, read the product title excerpt and model name, and click ✓ to confirm without navigating away from the list — expected throughput: ~20–30 filings in under 5 minutes if the classifications are correct.

### Handling the `correction_reason` Requirement

The `POST /api/classify/{id}/confirm` endpoint does not require `correction_reason` when the confirmed model matches the detected model (pure confirmation). It is required only when a different model is selected (correction case).

For the quick-confirm button, no reason is needed — the reviewer is confirming the existing model.

For corrections, the reviewer must open the full FilingDetail view and use the modal (where the correction reason text input is present).

### Tracking Confirmation Progress

The `FilingList.jsx` footer already shows the count of filtered vs total filings (line 140–142). When the reviewer has confirmed all `needs_classification_review` filings, the count drops to 0. No additional tracking UI is needed for the POC scale.

---

## Section 6: Effort Estimate and Task List

| # | Task | Effort | File(s) |
|---|---|---|---|
| 1 | Update `_persist()` in `classifier.py` to set `"needs_classification_review"` when confidence is 0.60–0.79 | 0.5 h | `backend/classify/classifier.py` lines 415–419 |
| 2 | Add `ConfirmClassificationRequest` and `ConfirmClassificationResponse` Pydantic models to `classify/router.py` | 0.5 h | `backend/classify/router.py` |
| 3 | Implement `POST /api/classify/{filing_id}/confirm` endpoint — status update + `ClassificationFeedback` row write | 2 h | `backend/classify/router.py` |
| 4 | Update `POST /api/extract/{filing_id}` to include `"needs_classification_review"` in the status check guard (single line change) | 0.25 h | `backend/extract/router.py` line 100 |
| 5 | Update status comment in `database.py` line 80 | 0.1 h | `backend/database.py` |
| 6 | Add `needs_classification_review` to `STATUSES` in `FilingList.jsx` | 0.1 h | `frontend/src/components/FilingList.jsx` line 4 |
| 7 | Add `needs_classification_review` style to `StatusBadge.jsx`; fix `replace('_', ' ')` to use regex `/g` flag | 0.25 h | `frontend/src/components/StatusBadge.jsx` |
| 8 | Add `canConfirmClass` state variable and warning banner to `FilingDetail.jsx` | 1 h | `frontend/src/components/FilingDetail.jsx` |
| 9 | Build `ConfirmClassificationModal` component — shows model, confidence, title excerpt, product features; confirm/correct/cancel actions | 3 h | `frontend/src/components/ConfirmClassificationModal.jsx` (new file) |
| 10 | Wire modal into `FilingDetail.jsx` — state, open/close, submit handler | 1 h | `frontend/src/components/FilingDetail.jsx` |
| 11 | Add `confirmClassification()` method to `frontend/src/api.js` | 0.25 h | `frontend/src/api.js` |
| 12 | Ensure `classification_title_excerpt` and `classification_product_features` are included in the filings list API response (check `FilingOut` model in ingest router) | 0.5 h | `backend/ingest/router.py` or equivalent |
| 13 | Add `classification_title_excerpt` display to `FilingList.jsx` list items for `needs_classification_review` filings | 0.5 h | `frontend/src/components/FilingList.jsx` |
| 14 | Add quick-confirm inline button to `FilingList.jsx` list items | 1 h | `frontend/src/components/FilingList.jsx` |
| 15 | End-to-end test: classify a low-confidence filing, verify it lands in `needs_classification_review`, confirm it, verify extraction proceeds | 1 h | Manual test |
| 16 | End-to-end test: correct a classification, verify `ClassificationFeedback` row is written, verify extraction uses corrected model | 1 h | Manual test |

**Total estimate: ~12.5 hours (~1.5 developer days)**

**Priority order for implementation:**

1. Tasks 1–5 first (backend only) — these unblock the gate and make the status machine correct. Deployable as a standalone backend change.
2. Tasks 6–8 next (minimal frontend) — make the new status visible in the UI.
3. Tasks 9–14 (full review workflow) — batch confirmation capability.
4. Tasks 15–16 (testing) — validate end-to-end before the ~78-filing batch run.

**Note on the existing 28 filings:** After task 1 is deployed, re-classifying any existing `"needs_review"` filing that was near the confidence boundary (0.60–0.79) will produce `"needs_classification_review"` instead. The existing `"needs_review"` filings are not automatically migrated — they stay as `"needs_review"` until re-classified. This is the correct behavior: `"needs_review"` filings (unknown model or very low confidence) still require investigation, not just a quick confirmation click.
