"""
Extraction and review API routes.

POST /api/extract/{filing_id}                    — run extraction
GET  /api/extract/{filing_id}/results            — get extraction results for a filing
PATCH /api/extract/{filing_id}/fields/{field_id} — update a field (inline review edit)
POST /api/extract/{filing_id}/approve            — approve the whole filing
POST /api/extract/{filing_id}/reextract          — re-run extraction
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
import database
from extract.extractor import extract_filing

log = logging.getLogger(__name__)
router = APIRouter(tags=["extract"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class FieldResultOut(BaseModel):
    id: str
    field_name: str
    extracted_value: Any
    confidence_score: float | None
    source_excerpt: str | None
    not_found: bool
    reviewed_value: Any
    review_status: str
    low_confidence: bool
    validation_error: str | None = None   # set when the extracted value violates a schema constraint


class ExtractionSummary(BaseModel):
    extraction_id: str
    filing_id: str
    prism_model_id: str
    prism_model_version: str
    extracted_at: str
    field_count: int | None
    fields_found: int | None
    fields_null: int | None
    fields: list[FieldResultOut]


class FieldUpdateRequest(BaseModel):
    reviewed_value: Any = None
    review_status: str  # accepted | corrected | rejected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _decode_value(json_str: str | None) -> Any:
    if json_str is None:
        return None
    try:
        return json.loads(json_str)
    except Exception:
        return json_str


def _row_to_out(row: database.FieldResult) -> FieldResultOut:
    return FieldResultOut(
        id=row.id,
        field_name=row.field_name,
        extracted_value=_decode_value(row.extracted_value),
        confidence_score=row.confidence_score,
        source_excerpt=row.source_excerpt,
        not_found=bool(row.not_found),
        reviewed_value=_decode_value(row.reviewed_value),
        review_status=row.review_status or "pending",
        low_confidence=(row.confidence_score or 1.0) < config.EXTRACTION_CONFIDENCE_THRESHOLD,
        validation_error=row.validation_error,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/extract/{filing_id}", response_model=ExtractionSummary)
def run_extraction(filing_id: str):
    """Run field extraction on a classified filing."""
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if filing.status not in ("classified", "needs_review", "extracted"):
            # "extracting" means a concurrent request is already running the LLM
            if filing.status == "extracting":
                raise HTTPException(
                    status_code=409,
                    detail="Extraction already in progress for this filing.",
                )
            raise HTTPException(
                status_code=422,
                detail=f"Filing must be classified first (current status: {filing.status})",
            )
        # Classification gate: block extraction when confidence is below gate threshold.
        # Prevents wasting extraction budget on uncertain or wrong product type assignments.
        conf = filing.classification_confidence or 0.0
        if conf < config.CLASSIFICATION_GATE_CONFIDENCE and filing.status != "extracted":
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Classification confidence {conf:.2f} is below gate threshold "
                    f"{config.CLASSIFICATION_GATE_CONFIDENCE}. "
                    "Review and confirm the classification in the UI before running extraction "
                    "(set status to 'classified' via POST /api/classify/{filing_id}/confirm)."
                ),
            )
        # TOCTOU guard: set an in-flight marker atomically before releasing the session.
        # A concurrent POST /extract/{id} will see status="extracting" and return 409,
        # preventing a duplicate LLM call (and duplicate API spend) on the same filing.
        if filing.status != "extracting":
            filing.status = "extracting"
            session.commit()

    try:
        result = extract_filing(filing_id)
    except Exception as exc:
        # Revert the in-flight marker so the filing can be re-tried
        try:
            with database.get_session() as rollback_session:
                f = rollback_session.get(database.Filing, filing_id)
                if f and f.status == "extracting":
                    f.status = "classified"
                    rollback_session.commit()
        except Exception:
            pass
        log.exception("Extraction failed for filing %s", filing_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return _get_extraction_summary(filing_id)


@router.post("/extract/{filing_id}/reextract", response_model=ExtractionSummary)
def reextract(filing_id: str):
    """Delete existing extraction results and re-run extraction."""
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        # Delete existing extraction results (cascades to field_results)
        for er in list(filing.extraction_results):
            session.delete(er)
        filing.status = "classified"
        session.commit()

    return run_extraction(filing_id)


@router.get("/extract/{filing_id}/results", response_model=ExtractionSummary)
def get_extraction_results(filing_id: str):
    """Return the latest extraction results for a filing."""
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if filing.status not in ("extracted", "approved", "exported"):
            raise HTTPException(status_code=404, detail="No extraction results yet")

    return _get_extraction_summary(filing_id)


@router.patch("/extract/{filing_id}/fields/{field_id}", response_model=FieldResultOut)
def update_field(filing_id: str, field_id: str, update: FieldUpdateRequest):
    """
    Inline review: update a field's reviewed value and status.
    Logs the edit to edit_log.
    """
    if update.review_status not in ("accepted", "corrected", "rejected"):
        raise HTTPException(status_code=422, detail="review_status must be accepted | corrected | rejected")

    with database.get_session() as session:
        row = session.get(database.FieldResult, field_id)
        if not row or row.filing_id != filing_id:
            raise HTTPException(status_code=404, detail="Field result not found")

        old_value = row.reviewed_value

        new_value_json = json.dumps(update.reviewed_value) if update.reviewed_value is not None else row.extracted_value
        row.reviewed_value = new_value_json
        row.review_status  = update.review_status
        row.reviewed_at    = datetime.now(timezone.utc).isoformat()

        log_entry = database.EditLog(
            id=str(uuid.uuid4()),
            filing_id=filing_id,
            field_name=row.field_name,
            old_value=old_value,
            new_value=new_value_json,
            action="corrected" if update.review_status == "corrected" else update.review_status,
        )
        session.add(log_entry)
        session.commit()
        session.refresh(row)
        return _row_to_out(row)


@router.post("/extract/{filing_id}/approve", status_code=200)
def approve_filing(filing_id: str):
    """
    Mark the filing as approved.
    All fields without explicit review_status are auto-accepted.
    """
    now = datetime.now(timezone.utc).isoformat()

    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if filing.status not in ("extracted", "needs_review"):
            raise HTTPException(
                status_code=422,
                detail=f"Filing must be in 'extracted' status (current: {filing.status})",
            )

        # Auto-accept any still-pending fields
        latest_er = (
            session.query(database.ExtractionResult)
            .filter_by(filing_id=filing_id)
            .order_by(database.ExtractionResult.extracted_at.desc())
            .first()
        )
        if latest_er:
            for fr in latest_er.field_results:
                if fr.review_status == "pending":
                    fr.review_status = "accepted"
                    fr.reviewed_at   = now

        filing.status = "approved"
        log_entry = database.EditLog(
            id=str(uuid.uuid4()),
            filing_id=filing_id,
            field_name="__filing__",
            old_value="extracted",
            new_value="approved",
            action="approved",
        )
        session.add(log_entry)
        session.commit()

    return {"filing_id": filing_id, "status": "approved"}


@router.post("/extract/{filing_id}/unapprove", status_code=200)
def unapprove_filing(filing_id: str):
    """Return an approved filing to 'extracted' status (requires explicit action per FR-5.3)."""
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if filing.status != "approved":
            raise HTTPException(status_code=422, detail="Filing is not approved")
        filing.status = "extracted"
        log_entry = database.EditLog(
            id=str(uuid.uuid4()),
            filing_id=filing_id,
            field_name="__filing__",
            old_value="approved",
            new_value="extracted",
            action="unapproved",
        )
        session.add(log_entry)
        session.commit()
    return {"filing_id": filing_id, "status": "extracted"}


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _get_extraction_summary(filing_id: str) -> ExtractionSummary:
    with database.get_session() as session:
        er = (
            session.query(database.ExtractionResult)
            .filter_by(filing_id=filing_id)
            .order_by(database.ExtractionResult.extracted_at.desc())
            .first()
        )
        if not er:
            raise HTTPException(status_code=404, detail="No extraction results found")

        fields_out = [_row_to_out(fr) for fr in er.field_results]
        return ExtractionSummary(
            extraction_id=er.id,
            filing_id=filing_id,
            prism_model_id=er.prism_model_id,
            prism_model_version=er.prism_model_version,
            extracted_at=er.extracted_at,
            field_count=er.field_count,
            fields_found=er.fields_found,
            fields_null=er.fields_null,
            fields=fields_out,
        )
