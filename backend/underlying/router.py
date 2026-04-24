"""
Underlying Data Module — FastAPI Router.

Mounts at ``/api/underlying`` (registered in main.py).

Endpoints
---------
GET    /api/underlying/resolve              Resolve an identifier (UI picker)
POST   /api/underlying/ingest              Start an ingest job
POST   /api/underlying/ingest/csv          Bulk ingest from CSV upload
GET    /api/underlying/jobs/{job_id}        Poll job status
GET    /api/underlying/field-config         Get field configuration
PUT    /api/underlying/field-config         Update field configuration
GET    /api/underlying/export               Bulk export (approved securities)
GET    /api/underlying/                     List securities (paginated)
GET    /api/underlying/{id}                 Get one security (full detail)
PUT    /api/underlying/{id}/fields/{name}   Update / review one field
POST   /api/underlying/{id}/approve        Approve a security
POST   /api/underlying/{id}/refetch        Re-queue data refresh
DELETE /api/underlying/{id}                Archive a security
GET    /api/underlying/{id}/export         Export one security as JSON
POST   /api/underlying/{id}/links          Link to a 424B2 filing
DELETE /api/underlying/{id}/links/{fid}    Unlink from a filing
"""
from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import config
import database as db
from database import (
    Filing,
    UnderlyingEditLog,
    UnderlyingFieldResult,
    UnderlyingJob,
    UnderlyingLink,
    UnderlyingSecurity,
)
from underlying import field_config as fc_module
from underlying.background import create_job, run_ingest_job
from underlying.identifier_resolver import resolve as resolve_identifier

log = logging.getLogger(__name__)
router = APIRouter(tags=["underlying"])

_MAX_CSV_ROWS = config.UNDERLYING_INGEST_MAX_CSV_ROWS


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

_MAX_IDENTIFIER_LEN = 100   # characters; anything longer is definitely not a valid identifier


class IngestRequest(BaseModel):
    identifiers: list[str] = Field(..., min_length=1,
        description="List of tickers, ISINs, CUSIPs, CIKs, or company names")
    fetch_market: bool = Field(True, description="Fetch Tier 3 market data (yfinance)")
    run_llm: bool = Field(True, description="Run Tier 2 LLM extraction on 10-K text")

    @field_validator("identifiers")
    @classmethod
    def validate_identifiers(cls, v: list[str]) -> list[str]:
        """Reject empty or excessively long identifier strings."""
        for ident in v:
            if not ident.strip():
                raise ValueError("Identifier cannot be empty or whitespace-only")
            if len(ident) > _MAX_IDENTIFIER_LEN:
                raise ValueError(
                    f"Identifier too long ({len(ident)} chars, max {_MAX_IDENTIFIER_LEN}): "
                    f"{ident[:40]!r}…"
                )
        return v


class FieldUpdate(BaseModel):
    value: Any = Field(..., description="New field value (any JSON-serialisable type)")
    action: str = Field("edited", description="Action tag: edited | accepted | rejected")


class LinkRequest(BaseModel):
    filing_id: str


class FieldConfigUpdate(BaseModel):
    fields: list[dict[str, Any]] = Field(
        ..., description="List of {name, display_name, enabled} update dicts"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _security_to_dict(row: UnderlyingSecurity, include_fields: bool = False) -> dict[str, Any]:
    """Serialise one ``UnderlyingSecurity`` row to a plain dict."""
    d: dict[str, Any] = {
        "id":                     row.id,
        "cik":                    row.cik,
        "ticker":                 row.ticker,
        "ticker_bb":              row.ticker_bb,
        "source_identifier":      row.source_identifier,
        "source_identifier_type": row.source_identifier_type,
        "company_name":           row.company_name,
        "share_class_name":       row.share_class_name,
        "share_type":             row.share_type,
        "reporting_form":         row.reporting_form,
        "filer_category":         row.filer_category,
        "fiscal_year_end":        row.fiscal_year_end,
        "exchange":               row.exchange,
        "sic_code":               row.sic_code,
        "sic_description":        row.sic_description,
        "state_of_incorporation": row.state_of_incorporation,
        "entity_type":            row.entity_type,
        "adr_flag":               row.adr_flag,
        # filing refs
        "last_10k_accession":     row.last_10k_accession,
        "last_10k_filed":         row.last_10k_filed,
        "last_10k_period":        row.last_10k_period,
        "last_10q_accession":     row.last_10q_accession,
        "last_10q_filed":         row.last_10q_filed,
        "last_10q_period":        row.last_10q_period,
        # currentness
        "current_status":         row.current_status,
        "nt_flag":                row.nt_flag,
        "next_expected_filing":   row.next_expected_filing,
        "next_expected_form":     row.next_expected_form,
        # XBRL
        "shares_outstanding":     row.shares_outstanding,
        "shares_outstanding_date":row.shares_outstanding_date,
        "public_float_usd":       row.public_float_usd,
        "public_float_date":      row.public_float_date,
        # market data
        "closing_value":          row.closing_value,
        "closing_value_date":     row.closing_value_date,
        "initial_value":          row.initial_value,
        "initial_value_date":     row.initial_value_date,
        "hist_data_series":       _parse_json_field(row.hist_data_series),
        "market_data_source":     row.market_data_source,
        "market_data_fetched_at": row.market_data_fetched_at,
        # lifecycle
        "status":                 row.status,
        "ingest_timestamp":       row.ingest_timestamp,
        "last_fetched_at":        row.last_fetched_at,
        "field_config_version":   row.field_config_version,
        "fetch_error":            row.fetch_error,
    }
    if include_fields:
        d["field_results"] = [_field_result_to_dict(fr) for fr in row.field_results]
        d["links"] = [_link_to_dict(lnk) for lnk in row.links]
    return d


def _field_result_to_dict(fr: UnderlyingFieldResult) -> dict[str, Any]:
    return {
        "id":                  fr.id,
        "field_name":          fr.field_name,
        "extracted_value":     _parse_json_field(fr.extracted_value),
        "confidence_score":    fr.confidence_score,
        "source_excerpt":      fr.source_excerpt,
        "source_type":         fr.source_type,
        "is_approximate":      fr.is_approximate,
        "review_status":       fr.review_status,
        "reviewed_value":      _parse_json_field(fr.reviewed_value),
        "reviewed_at":         fr.reviewed_at,
        "field_config_version":fr.field_config_version,
    }


def _link_to_dict(lnk: UnderlyingLink) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id":           lnk.id,
        "filing_id":    lnk.filing_id,
        "linked_at":    lnk.linked_at,
        "link_source":  lnk.link_source,
    }
    # Include summary fields from the linked Filing if eagerly loaded
    if lnk.filing:
        d["filing_cusip"]        = lnk.filing.cusip
        d["filing_issuer_name"]  = lnk.filing.issuer_name
        d["filing_date"]         = lnk.filing.filing_date
        d["filing_accession"]    = lnk.filing.accession_number
        d["filing_status"]       = lnk.filing.status
    return d


def _parse_json_field(raw: str | None) -> Any:
    """Silently parse a JSON-encoded column; return None on failure."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


def _get_or_404(session: Any, model: type, pk: str, label: str = "record") -> Any:
    row = session.get(model, pk)
    if row is None:
        raise HTTPException(status_code=404, detail=f"{label} not found: {pk}")
    return row


# ---------------------------------------------------------------------------
# Identifier resolution (UI picker)
# ---------------------------------------------------------------------------

@router.get("/underlying/resolve")
def api_resolve(identifier: str = Query(..., description="Raw identifier string")) -> dict:
    """Resolve an identifier to CIK + ticker candidates.

    Used by the frontend picker when the user types a search string.
    GET is appropriate here: the operation is read-only and idempotent, and the
    identifier is passed as a query parameter — not a request body.
    """
    result = resolve_identifier(identifier)
    if result.status == "error":
        raise HTTPException(status_code=502, detail=result.error or "Resolution error")

    response: dict[str, Any] = {"status": result.status}
    if result.resolved:
        response["resolved"] = {
            "cik": result.resolved.cik,
            "ticker": result.resolved.ticker,
            "company_name": result.resolved.company_name,
            "exchange": result.resolved.exchange,
        }
    if result.candidates:
        response["candidates"] = [
            {
                "cik": c.cik,
                "ticker": c.ticker,
                "company_name": c.company_name,
                "exchange": c.exchange,
            }
            for c in result.candidates
        ]
    return response


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

@router.post("/underlying/ingest", status_code=202)
def api_ingest(req: IngestRequest, bg: BackgroundTasks) -> dict:
    """Start an asynchronous ingest job for one or more identifiers."""
    if len(req.identifiers) > _MAX_CSV_ROWS:
        raise HTTPException(
            status_code=422,
            detail=f"Too many identifiers ({len(req.identifiers)} > {_MAX_CSV_ROWS})",
        )
    job_id = create_job(req.identifiers)
    bg.add_task(
        run_ingest_job, job_id, req.identifiers,
        fetch_market=req.fetch_market,
        run_llm=req.run_llm,
    )
    return {
        "job_id": job_id,
        "status": "pending",
        "total": len(req.identifiers),
        "poll_interval_seconds": config.UNDERLYING_JOB_POLL_INTERVAL,
    }


@router.post("/underlying/ingest/csv", status_code=202)
async def api_ingest_csv(file: UploadFile, bg: BackgroundTasks) -> dict:
    """Bulk ingest from a CSV file.

    Expected format: one column named ``identifier`` (header row required).
    Other columns are ignored.  Max ``UNDERLYING_INGEST_MAX_CSV_ROWS`` rows.
    """
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")   # handles UTF-8 with or without BOM
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422,
            detail=(
                "CSV file must be UTF-8 encoded.  "
                "Re-save the file as UTF-8 (with or without BOM) and try again."
            ),
        )

    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "identifier" not in reader.fieldnames:
        raise HTTPException(
            status_code=422,
            detail="CSV must have an 'identifier' column header"
        )

    identifiers: list[str] = []
    for row in reader:
        val = (row.get("identifier") or "").strip()
        if val:
            identifiers.append(val)
        if len(identifiers) >= _MAX_CSV_ROWS:
            break

    if not identifiers:
        raise HTTPException(status_code=422, detail="CSV contains no valid identifiers")

    job_id = create_job(identifiers)
    bg.add_task(run_ingest_job, job_id, identifiers)
    return {
        "job_id": job_id,
        "status": "pending",
        "total": len(identifiers),
        "poll_interval_seconds": config.UNDERLYING_JOB_POLL_INTERVAL,
    }


# ---------------------------------------------------------------------------
# Job status
# ---------------------------------------------------------------------------

@router.get("/underlying/jobs/{job_id}")
def api_job_status(job_id: str) -> dict:
    """Poll the status of an ingest job."""
    with db.get_session() as session:
        job = _get_or_404(session, UnderlyingJob, job_id, "Job")
        return {
            "id":         job.id,
            "status":     job.status,
            "total":      job.total,
            "done":       job.done,
            "success":    job.success,
            "errors":     job.errors,
            "results":    _parse_json_field(job.results),
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }


# ---------------------------------------------------------------------------
# Field configuration
# ---------------------------------------------------------------------------

@router.get("/underlying/field-config")
def api_get_field_config() -> dict:
    """Return the current underlying field configuration."""
    try:
        cfg = fc_module.load()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    return cfg.to_dict()


@router.put("/underlying/field-config")
def api_put_field_config(req: FieldConfigUpdate) -> dict:
    """Update field configuration (enable/disable, reorder, rename display labels)."""
    try:
        cfg = fc_module.update_fields(req.fields)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return cfg.to_dict()


# ---------------------------------------------------------------------------
# Bulk export
# ---------------------------------------------------------------------------

@router.get("/underlying/export")
def api_bulk_export(
    status: str = Query("approved", description="Filter by status"),
) -> JSONResponse:
    """Export all underlying securities matching *status* as a JSON array."""
    with db.get_session() as session:
        rows = session.query(UnderlyingSecurity).filter_by(status=status).all()
        data = [_security_to_dict(r, include_fields=True) for r in rows]
    return JSONResponse(content=data)


# ---------------------------------------------------------------------------
# List securities
# ---------------------------------------------------------------------------

@router.get("/underlying/")
def api_list(
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Partial match on company_name or ticker"),
) -> dict:
    """Return a paginated list of underlying securities."""
    with db.get_session() as session:
        q = session.query(UnderlyingSecurity)
        if status:
            q = q.filter_by(status=status)
        if search:
            like = f"%{search}%"
            q = q.filter(
                (UnderlyingSecurity.company_name.ilike(like)) |
                (UnderlyingSecurity.ticker.ilike(like))
            )
        total = q.count()
        offset = (page - 1) * page_size
        rows = q.order_by(UnderlyingSecurity.ingest_timestamp.desc()) \
                .offset(offset).limit(page_size).all()
        items = [_security_to_dict(r) for r in rows]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Single security
# ---------------------------------------------------------------------------

@router.get("/underlying/{id}")
def api_get(id: str) -> dict:
    """Return full detail for one underlying security including field results."""
    with db.get_session() as session:
        row = _get_or_404(session, UnderlyingSecurity, id, "Underlying security")
        return _security_to_dict(row, include_fields=True)


@router.put("/underlying/{id}/fields/{field_name}")
def api_update_field(id: str, field_name: str, req: FieldUpdate) -> dict:
    """Update a single field value (reviewer edit or acceptance)."""
    with db.get_session() as session:
        underlying = _get_or_404(session, UnderlyingSecurity, id, "Underlying security")

        # Log the edit
        fr = (
            session.query(UnderlyingFieldResult)
            .filter_by(underlying_id=id, field_name=field_name)
            .first()
        )
        old_value = (fr.reviewed_value or fr.extracted_value) if fr else None

        log_row = UnderlyingEditLog(
            underlying_id=id,
            field_name=field_name,
            old_value=old_value,
            new_value=json.dumps(req.value),
            action=req.action,
        )
        session.add(log_row)

        if fr is not None:
            fr.reviewed_value = json.dumps(req.value)
            fr.reviewed_at = _now()
            fr.review_status = "corrected" if req.action == "edited" else req.action
        else:
            # Create a manual field result if it doesn't exist
            fr = UnderlyingFieldResult(
                underlying_id=id,
                field_name=field_name,
                extracted_value=None,
                reviewed_value=json.dumps(req.value),
                reviewed_at=_now(),
                review_status="corrected",
                source_type="manual",
                confidence_score=1.0,
                field_config_version=underlying.field_config_version,
            )
            session.add(fr)

        # Mirror numeric/string fields directly onto the master record
        _mirror_field_to_security(underlying, field_name, req.value)

        session.commit()
        return {"ok": True, "field_name": field_name, "value": req.value}


@router.post("/underlying/{id}/approve")
def api_approve(id: str) -> dict:
    """Mark a security as approved (eligible for export and filing linkage)."""
    with db.get_session() as session:
        row = _get_or_404(session, UnderlyingSecurity, id, "Underlying security")
        old_status = row.status          # capture before mutation
        row.status = "approved"
        log_row = UnderlyingEditLog(
            underlying_id=id,
            field_name="status",
            old_value=old_status,
            new_value="approved",
            action="approved",
        )
        session.add(log_row)
        session.commit()
    return {"ok": True, "status": "approved"}


@router.post("/underlying/{id}/refetch")
def api_refetch(id: str, bg: BackgroundTasks) -> dict:
    """Re-queue a security for a full data refresh."""
    with db.get_session() as session:
        row = _get_or_404(session, UnderlyingSecurity, id, "Underlying security")
        identifier = row.source_identifier or row.ticker or row.cik
        row.status = "fetching"
        session.commit()

    job_id = create_job([identifier])
    bg.add_task(run_ingest_job, job_id, [identifier])
    return {"ok": True, "job_id": job_id}


@router.delete("/underlying/{id}")
def api_delete(id: str) -> dict:
    """Archive a security (soft-delete: set status to 'archived')."""
    with db.get_session() as session:
        row = _get_or_404(session, UnderlyingSecurity, id, "Underlying security")
        row.status = "archived"
        session.commit()
    return {"ok": True, "status": "archived"}


# ---------------------------------------------------------------------------
# Single export
# ---------------------------------------------------------------------------

@router.get("/underlying/{id}/export")
def api_export(id: str) -> JSONResponse:
    """Export one underlying security as a JSON object."""
    with db.get_session() as session:
        row = _get_or_404(session, UnderlyingSecurity, id, "Underlying security")
        data = _security_to_dict(row, include_fields=True)
    return JSONResponse(content=data)


# ---------------------------------------------------------------------------
# Filing links
# ---------------------------------------------------------------------------

@router.post("/underlying/{id}/links", status_code=201)
def api_link_filing(id: str, req: LinkRequest) -> dict:
    """Link this underlying security to a 424B2 filing."""
    with db.get_session() as session:
        _get_or_404(session, UnderlyingSecurity, id, "Underlying security")
        # Check filing exists
        _get_or_404(session, Filing, req.filing_id, "Filing")

        existing = (
            session.query(UnderlyingLink)
            .filter_by(filing_id=req.filing_id, underlying_id=id)
            .first()
        )
        if existing:
            return {"ok": True, "already_linked": True, "link_id": existing.id}

        link = UnderlyingLink(
            filing_id=req.filing_id,
            underlying_id=id,
            link_source="manual",
        )
        session.add(link)
        session.commit()
        return {"ok": True, "already_linked": False, "link_id": link.id}


@router.delete("/underlying/{id}/links/{filing_id}")
def api_unlink_filing(id: str, filing_id: str) -> dict:
    """Remove a link between this underlying security and a filing."""
    with db.get_session() as session:
        link = (
            session.query(UnderlyingLink)
            .filter_by(filing_id=filing_id, underlying_id=id)
            .first()
        )
        if link is None:
            raise HTTPException(status_code=404, detail="Link not found")
        session.delete(link)
        session.commit()
    return {"ok": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Fields that have a direct column on UnderlyingSecurity and should be
# mirrored back when a reviewer edits the field_result value.
_MIRRORED_FIELDS: frozenset[str] = frozenset({
    "company_name", "share_class_name", "share_type", "ticker_bb",
    "exchange", "sic_code", "sic_description", "state_of_incorporation",
    "adr_flag", "closing_value", "initial_value", "shares_outstanding",
    "public_float_usd",
})


def _mirror_field_to_security(row: UnderlyingSecurity, field_name: str, value: Any) -> None:
    """Copy a reviewed field value back onto the master ``UnderlyingSecurity`` columns."""
    if field_name in _MIRRORED_FIELDS and hasattr(row, field_name):
        setattr(row, field_name, value)
