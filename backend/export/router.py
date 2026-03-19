"""
Export API routes.

POST /api/export/{filing_id}   — export one approved filing
POST /api/export/batch         — export all approved filings
GET  /api/export/list          — list available export files
GET  /api/usage                — Claude API usage summary
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import config
import database
from export.exporter import export_filing

log = logging.getLogger(__name__)
router = APIRouter(tags=["export"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ExportResponse(BaseModel):
    filing_id: str
    json_path: str
    csv_path: str
    status: str


class BatchExportResponse(BaseModel):
    exported: list[str]
    failed: dict[str, str]   # filing_id → error message


class ExportFileEntry(BaseModel):
    filename: str
    size_bytes: int
    modified_at: str


class UsageRecord(BaseModel):
    call_type: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    called_at: str
    filing_id: str | None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/export/{filing_id}", response_model=ExportResponse)
def export_one(filing_id: str):
    """Export a single approved filing to JSON + CSV."""
    try:
        result = export_filing(filing_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        log.exception("Export failed for filing %s", filing_id)
        raise HTTPException(status_code=500, detail=str(exc))

    return ExportResponse(
        filing_id=filing_id,
        json_path=result.json_path,
        csv_path=result.csv_path,
        status="exported",
    )


@router.post("/export/batch", response_model=BatchExportResponse)
def export_batch():
    """Export all approved filings that have not yet been exported."""
    with database.get_session() as session:
        approved = (
            session.query(database.Filing)
            .filter(database.Filing.status == "approved")
            .all()
        )
        filing_ids = [f.id for f in approved]

    exported: list[str] = []
    failed: dict[str, str] = {}

    for fid in filing_ids:
        try:
            export_filing(fid)
            exported.append(fid)
        except Exception as exc:
            failed[fid] = str(exc)
            log.warning("Batch export failed for %s: %s", fid, exc)

    return BatchExportResponse(exported=exported, failed=failed)


@router.get("/export/list", response_model=list[ExportFileEntry])
def list_exports():
    """List all files in the exports directory."""
    entries: list[ExportFileEntry] = []
    exports_dir = config.EXPORTS_DIR
    if not exports_dir.exists():
        return entries
    for f in sorted(exports_dir.iterdir()):
        if f.is_file():
            stat = f.stat()
            from datetime import datetime, timezone
            entries.append(ExportFileEntry(
                filename=f.name,
                size_bytes=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            ))
    return entries


@router.get("/export/download/{filename}")
def download_export(filename: str):
    """Download an export file by filename."""
    # Security: prevent path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = config.EXPORTS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path=str(path), filename=filename)


@router.get("/usage", response_model=list[UsageRecord])
def get_api_usage(limit: int = 100):
    """Return recent Claude API usage log for budget awareness (NFR-6)."""
    with database.get_session() as session:
        rows = (
            session.query(database.ApiUsageLog)
            .order_by(database.ApiUsageLog.called_at.desc())
            .limit(limit)
            .all()
        )
        return [
            UsageRecord(
                call_type=r.call_type,
                model=r.model,
                prompt_tokens=r.prompt_tokens,
                completion_tokens=r.completion_tokens,
                called_at=r.called_at,
                filing_id=r.filing_id,
            )
            for r in rows
        ]
