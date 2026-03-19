"""
Export logic — generates PRISM-compatible JSON and CSV for approved filings.

Output format follows DATA_MODEL.md section 4.
Filename convention: {cusip}_{payout_type_id}_{approved_date}.json / .csv
"""
from __future__ import annotations

import csv
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import config
import database
import schema_loader

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class ExportResult:
    filing_id: str
    json_path: str   # relative to project root
    csv_path: str    # relative to project root
    missing_required: list[str]


# ---------------------------------------------------------------------------
# Main export
# ---------------------------------------------------------------------------

def export_filing(filing_id: str) -> ExportResult:
    """
    Generate JSON + CSV export for an approved filing.
    Raises ValueError if required fields are null.
    Updates filing status to 'exported' on success.
    """
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise ValueError("Filing not found")
        if filing.status != "approved":
            raise ValueError(f"Filing must be approved before export (status: {filing.status})")

        er = (
            session.query(database.ExtractionResult)
            .filter_by(filing_id=filing_id)
            .order_by(database.ExtractionResult.extracted_at.desc())
            .first()
        )
        if not er:
            raise ValueError("No extraction results found")

        model_name    = er.prism_model_id
        model_version = er.prism_model_version

        # Build field value dict — prefer reviewed_value, fall back to extracted_value
        field_values: dict[str, Any] = {}
        field_statuses: dict[str, str] = {}
        for fr in er.field_results:
            val_str = fr.reviewed_value if fr.reviewed_value is not None else fr.extracted_value
            try:
                val = json.loads(val_str) if val_str is not None else None
            except Exception:
                val = val_str
            # Skip rejected fields
            if fr.review_status == "rejected":
                val = None
            field_values[fr.field_name] = val
            field_statuses[fr.field_name] = fr.review_status or "accepted"

        cusip        = filing.cusip or "UNKNOWN"
        issuer_name  = filing.issuer_name or ""
        filing_date  = filing.filing_date or ""
        acc_no       = filing.accession_number
        edgar_url    = filing.edgar_filing_url or ""

    # Validate required fields
    descriptors = schema_loader.get_field_descriptors(model_name)
    required_paths = {d.path for d in descriptors if d.required}
    missing = [p for p in required_paths if not field_values.get(p)]
    if missing:
        raise ValueError(
            f"Export blocked — required fields are null: {', '.join(sorted(missing))}"
        )

    # Reconstruct nested PRISM object from flat dot-paths
    prism_fields = _unflatten(field_values)

    # Add model discriminator
    prism_fields["model"] = model_name

    now = datetime.now(timezone.utc).isoformat()
    approved_date = now[:10]  # YYYY-MM-DD

    export_doc = {
        "export_metadata": {
            "cusip":                   cusip,
            "accession_number":        acc_no,
            "issuer_name":             issuer_name,
            "filing_date":             filing_date,
            "edgar_filing_url":        edgar_url,
            "payout_type_id":          model_name,
            "prism_schema_version":    model_version,
            "extracted_at":            er.extracted_at,
            "approved_at":             now,
            "export_generated_at":     now,
        },
        "prism": prism_fields,
        "field_review_status": field_statuses,
    }

    # Write files
    safe_cusip   = re.sub(r"[^A-Za-z0-9]", "", cusip)
    safe_model   = re.sub(r"[^A-Za-z0-9_]", "_", model_name)
    base_name    = f"{safe_cusip}_{safe_model}_{approved_date}"

    config.EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = config.EXPORTS_DIR / f"{base_name}.json"
    csv_path  = config.EXPORTS_DIR / f"{base_name}.csv"

    json_path.write_text(json.dumps(export_doc, indent=2, ensure_ascii=False), encoding="utf-8")
    _write_csv(csv_path, cusip, model_name, model_version, filing_date, field_values)

    # Update filing status
    with database.get_session() as session:
        filing_obj = session.get(database.Filing, filing_id)
        if filing_obj:
            filing_obj.status = "exported"
        log_entry = database.EditLog(
            id=str(uuid.uuid4()),
            filing_id=filing_id,
            field_name="__filing__",
            old_value="approved",
            new_value="exported",
            action="exported",
        )
        session.add(log_entry)
        session.commit()

    rel_json = str(json_path.relative_to(config.PROJECT_ROOT))
    rel_csv  = str(csv_path.relative_to(config.PROJECT_ROOT))

    log.info("Export complete: filing=%s  json=%s  csv=%s", filing_id, rel_json, rel_csv)
    return ExportResult(
        filing_id=filing_id,
        json_path=rel_json,
        csv_path=rel_csv,
        missing_required=[],
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unflatten(flat: dict[str, Any]) -> dict[str, Any]:
    """Convert dot-path keys back to a nested dict."""
    result: dict[str, Any] = {}
    for key, value in flat.items():
        if value is None:
            continue
        parts = key.split(".")
        node = result
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return result


def _write_csv(
    path: Path,
    cusip: str,
    model_name: str,
    model_version: str,
    filing_date: str,
    field_values: dict[str, Any],
) -> None:
    """Write a flat CSV with one row per filing."""
    # Sort field names for stable column order
    sorted_fields = sorted(field_values.keys())
    headers = ["cusip", "payout_type_id", "schema_version", "filing_date"] + sorted_fields

    row: dict[str, Any] = {
        "cusip":           cusip,
        "payout_type_id":  model_name,
        "schema_version":  model_version,
        "filing_date":     filing_date,
    }
    for k in sorted_fields:
        v = field_values[k]
        row[k] = json.dumps(v) if isinstance(v, (dict, list)) else (v if v is not None else "")

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        writer.writerow(row)
