"""
Label Map management API routes.

Surfaces the hybrid-extraction label map (cross-issuer baseline + user-added
entries) and the miss log (labels seen in filings without a mapping) so that
the Expert Settings UI can display and maintain them without manual YAML edits.

Routes
------
GET  /api/admin/label-map/entries         — all entries (cross-issuer + user)
POST /api/admin/label-map/entries         — add/overwrite a user entry
DELETE /api/admin/label-map/entries       — remove a user entry (by label_norm)

GET  /api/admin/label-map/misses          — unresolved labels from extraction runs
POST /api/admin/label-map/misses/{id}/resolve  — add mapping + mark miss resolved
DELETE /api/admin/label-map/misses/{id}        — dismiss miss (without adding mapping)
DELETE /api/admin/label-map/misses             — bulk-dismiss all active misses

GET  /api/admin/label-map/field-paths     — list of known PRISM field paths (for dropdown)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import database
from extract.label_mapper import (
    add_user_entry,
    remove_user_entry,
    list_user_entries,
    list_cross_entries,
    LABEL_MAP_USER_PATH,
)
from extract.field_parsers import FIELD_PARSERS

log = logging.getLogger(__name__)
router = APIRouter(tags=["label-map"])


# ---------------------------------------------------------------------------
# Response / request models
# ---------------------------------------------------------------------------

class LabelEntryOut(BaseModel):
    label:       str
    label_norm:  str
    field_path:  str
    source:      str   # "cross_issuer" | "user"


class AddEntryRequest(BaseModel):
    label:      str
    field_path: str


class RemoveEntryRequest(BaseModel):
    label_norm: str


class ResolveMissRequest(BaseModel):
    field_path: str


class LabelMissOut(BaseModel):
    id:               str
    label_raw:        str
    label_norm:       str
    sample_value:     str | None
    issuer_name:      str | None
    filing_id:        str | None
    occurrence_count: int
    first_seen_at:    str
    last_seen_at:     str


# ---------------------------------------------------------------------------
# Entries
# ---------------------------------------------------------------------------

@router.get("/admin/label-map/entries", response_model=list[LabelEntryOut])
def get_entries():
    """
    Return all label map entries: cross-issuer baseline + user-added.
    User entries override cross-issuer entries of the same normalized label.
    """
    cross = {e["label_norm"]: e for e in list_cross_entries()}
    user  = {e["label_norm"]: e for e in list_user_entries()}
    # Merge: user overrides cross
    merged = {**cross, **user}
    return [
        LabelEntryOut(
            label=e["label"],
            label_norm=e["label_norm"],
            field_path=e["field_path"],
            source=e["source"],
        )
        for e in sorted(merged.values(), key=lambda x: x["label_norm"])
    ]


@router.post("/admin/label-map/entries", status_code=201)
def add_entry(req: AddEntryRequest):
    """Add or overwrite a user label mapping and persist to label_map_user.yaml."""
    if not req.label.strip():
        raise HTTPException(status_code=422, detail="label must not be empty")
    if not req.field_path.strip():
        raise HTTPException(status_code=422, detail="field_path must not be empty")
    add_user_entry(req.label, req.field_path)
    return {"label": req.label, "field_path": req.field_path, "source": "user"}


@router.delete("/admin/label-map/entries", status_code=200)
def remove_entry(req: RemoveEntryRequest):
    """Remove a user-added label mapping by normalized label."""
    removed = remove_user_entry(req.label_norm)
    if not removed:
        raise HTTPException(
            status_code=404,
            detail=f"No user entry found for normalized label '{req.label_norm}' "
                   "(cross-issuer baseline entries cannot be removed via the UI — "
                   "edit files/label_map_cross_issuer.yaml directly)",
        )
    return {"removed": True, "label_norm": req.label_norm}


# ---------------------------------------------------------------------------
# Miss log
# ---------------------------------------------------------------------------

@router.get("/admin/label-map/misses", response_model=list[LabelMissOut])
def get_misses(include_dismissed: bool = False):
    """
    Return labels seen during HTML extraction that had no mapping.
    Sorted by occurrence_count descending (most frequent gaps first).
    """
    with database.get_session() as session:
        q = session.query(database.LabelMissLog)
        if not include_dismissed:
            q = q.filter(database.LabelMissLog.dismissed == 0)
        rows = q.order_by(database.LabelMissLog.occurrence_count.desc()).all()
        return [
            LabelMissOut(
                id=r.id,
                label_raw=r.label_raw,
                label_norm=r.label_norm,
                sample_value=r.sample_value,
                issuer_name=r.issuer_name,
                filing_id=r.filing_id,
                occurrence_count=r.occurrence_count or 1,
                first_seen_at=r.first_seen_at,
                last_seen_at=r.last_seen_at,
            )
            for r in rows
        ]


@router.post("/admin/label-map/misses/{miss_id}/resolve", status_code=200)
def resolve_miss(miss_id: str, req: ResolveMissRequest):
    """
    Add a label mapping for this miss entry and mark it as dismissed.
    The label_raw from the miss is used as the label key in label_map_user.yaml.
    """
    if not req.field_path.strip():
        raise HTTPException(status_code=422, detail="field_path must not be empty")

    with database.get_session() as session:
        row = session.get(database.LabelMissLog, miss_id)
        if not row:
            raise HTTPException(status_code=404, detail="Miss entry not found")
        label_raw = row.label_raw
        row.dismissed = 1
        session.commit()

    add_user_entry(label_raw, req.field_path)
    log.info("Resolved label miss %r → %s", label_raw, req.field_path)
    return {"resolved": True, "label": label_raw, "field_path": req.field_path}


@router.delete("/admin/label-map/misses/{miss_id}", status_code=200)
def dismiss_miss(miss_id: str):
    """Dismiss a miss entry without adding a mapping (e.g. known non-PRISM label)."""
    with database.get_session() as session:
        row = session.get(database.LabelMissLog, miss_id)
        if not row:
            raise HTTPException(status_code=404, detail="Miss entry not found")
        row.dismissed = 1
        session.commit()
    return {"dismissed": True, "id": miss_id}


@router.delete("/admin/label-map/misses", status_code=200)
def dismiss_all_misses():
    """Bulk-dismiss all currently active (non-dismissed) miss entries."""
    with database.get_session() as session:
        count = (
            session.query(database.LabelMissLog)
            .filter(database.LabelMissLog.dismissed == 0)
            .update({"dismissed": 1})
        )
        session.commit()
    return {"dismissed_count": count}


# ---------------------------------------------------------------------------
# Known field paths — for the dropdown in the UI
# ---------------------------------------------------------------------------

@router.get("/admin/label-map/field-paths", response_model=list[str])
def get_field_paths():
    """
    Return the list of PRISM field paths for which typed parsers exist.
    Used to populate the 'Map to field' dropdown in the UI.
    """
    return sorted(FIELD_PARSERS.keys())
