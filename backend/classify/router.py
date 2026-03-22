"""
Classification API routes.

POST /api/classify/{filing_id}         — classify a filing into a PRISM payout type
POST /api/classify/{filing_id}/confirm — human confirmation of needs_classification_review
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import config
import database
import schema_loader
from classify.classifier import classify_filing

log = logging.getLogger(__name__)
router = APIRouter(tags=["classify"])


class ClassifyResponse(BaseModel):
    filing_id: str
    payout_type_id: str
    confidence_score: float
    matched_schema_version: str
    classification_timestamp: str
    status: str
    low_confidence: bool
    title_excerpt: str | None = None
    product_features: dict | None = None
    classification_stage: int = 1


class ConfirmClassificationRequest(BaseModel):
    confirmed_by: str = "reviewer"
    payout_type_id: str | None = None   # None → confirm the existing model unchanged


class ConfirmClassificationResponse(BaseModel):
    filing_id: str
    payout_type_id: str
    status: str
    confirmed_by: str


@router.get("/classify/models")
def list_prism_models():
    """Return the list of known PRISM payout_type_id values from the current schema."""
    models = schema_loader.list_models()
    return {"models": models}


@router.post("/classify/{filing_id}", response_model=ClassifyResponse)
def classify(filing_id: str):
    """
    Classify a filing.  The filing must already be ingested (status = 'ingested').
    If the CUSIP is known in the mapping table, it is used as a classification hint.
    """
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if not filing.raw_html_path:
            raise HTTPException(status_code=422, detail="Filing has no raw HTML — ingest first")
        raw_html_path = filing.raw_html_path
        cusip = filing.cusip

    # Check CUSIP mapping for a hint.
    # Always forward the hint — even when the mapped model is not in the current
    # schema — so Claude knows to return "unknown" rather than force a wrong match.
    cusip_hint: str | None = None
    cusip_hint_in_schema: bool = False
    if cusip:
        mapping = schema_loader.load_cusip_mapping()
        entry = mapping.get(cusip.upper())
        if entry:
            cusip_hint = entry.payout_type_id
            cusip_hint_in_schema = cusip_hint in schema_loader.list_models()

    try:
        result = classify_filing(
            filing_id=filing_id,
            raw_html_path=raw_html_path,
            cusip_hint=cusip_hint,
            cusip_hint_in_schema=cusip_hint_in_schema,
        )
    except Exception as exc:
        log.exception("Classification failed for filing %s", filing_id)
        raise HTTPException(status_code=500, detail=str(exc))

    # Fetch updated status
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        status = filing.status if filing else "unknown"

    return ClassifyResponse(
        filing_id=filing_id,
        payout_type_id=result.payout_type_id,
        confidence_score=result.confidence_score,
        matched_schema_version=result.matched_schema_version,
        classification_timestamp=result.classification_timestamp,
        status=status,
        low_confidence=result.confidence_score < config.CLASSIFICATION_CONFIDENCE_THRESHOLD,
        title_excerpt=result.title_excerpt or None,
        product_features=result.product_features or None,
        classification_stage=result.stage,
    )


@router.post("/classify/{filing_id}/confirm", response_model=ConfirmClassificationResponse)
def confirm_classification(filing_id: str, body: ConfirmClassificationRequest):
    """
    Human confirmation of a needs_classification_review filing.
    Promotes it to 'classified' (confidence set to 1.0).
    Optionally accepts a corrected payout_type_id; if omitted, confirms the existing model.
    Records a ClassificationFeedback entry for the few-shot feedback loop.
    """
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise HTTPException(status_code=404, detail="Filing not found")
        if filing.status != "needs_classification_review":
            raise HTTPException(
                status_code=422,
                detail=f"Filing status is '{filing.status}', expected 'needs_classification_review'",
            )

        known_models = schema_loader.list_models()
        original_model = filing.payout_type_id or "unknown"
        confirmed_model = body.payout_type_id or original_model

        if confirmed_model not in known_models and confirmed_model != "unknown":
            raise HTTPException(status_code=422, detail=f"Unknown PRISM model: '{confirmed_model}'")

        now = datetime.now(timezone.utc).isoformat()
        filing.payout_type_id = confirmed_model
        filing.classification_confidence = 1.0
        filing.status = "classified"
        filing.classified_at = now

        feedback = database.ClassificationFeedback(
            id=str(uuid.uuid4()),
            filing_id=filing_id,
            original_payout_type=original_model,
            corrected_payout_type=confirmed_model,
            correction_reason="human confirmation via classification review gate",
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
