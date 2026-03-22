"""
hints/router.py — FastAPI router for CRUD operations on extraction hints.

Routes
------
GET  /api/hints                                       list all issuer hint files
GET  /api/hints/cross-issuer                          get cross-issuer field_level_hints
PUT  /api/hints/cross-issuer                          save cross-issuer hints to YAML
GET  /api/hints/issuers/{issuer_slug}                 get full hints for one issuer
PUT  /api/hints/issuers/{issuer_slug}                 update/save issuer hints to YAML
GET  /api/hints/issuers/{issuer_slug}/fields/{field_path}  get one field hint
PUT  /api/hints/issuers/{issuer_slug}/fields/{field_path}  update one field hint
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import hints_loader

log = logging.getLogger(__name__)

router = APIRouter(prefix="/hints", tags=["hints"])


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class IssuerSummary(BaseModel):
    slug: str
    name: str
    file: str | None
    field_hints_count: int
    section_headings: list[str]
    last_modified: str | None


class FieldHintUpdate(BaseModel):
    """Partial update for a single field hint entry."""
    synonyms: list[str] | None = None
    label_in_doc: str | None = None
    format: str | None = None
    typical_location: str | None = None
    description: str | None = None
    common_synonyms: list[str] | None = None
    value_format: str | None = None
    caution: str | None = None
    issuer_specific: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _file_mtime_iso(path: Path) -> str | None:
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except OSError:
        return None


def _load_yaml_file(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        log.exception("Failed to read YAML file %s", path.name)
        raise HTTPException(status_code=500, detail=f"Failed to read {path.name}: {exc}")


def _save_yaml_file(path: Path, data: dict) -> None:
    try:
        with path.open("w", encoding="utf-8") as fh:
            yaml.dump(data, fh, allow_unicode=True, default_flow_style=False,
                      sort_keys=False, width=120)
        # Invalidate cache so next get_hints() reloads
        hints_loader.reload_hints()
    except Exception as exc:
        log.exception("Failed to write YAML file %s", path.name)
        raise HTTPException(status_code=500, detail=f"Failed to write {path.name}: {exc}")


def _resolve_issuer(slug: str) -> tuple[str, dict, Path]:
    """
    Resolve slug → (issuer_key, issuer_data, yaml_path).
    Raises 404 if not found.
    """
    issuer_key = hints_loader.slug_to_issuer_key(slug)
    if not issuer_key:
        raise HTTPException(status_code=404, detail=f"Issuer slug '{slug}' not found")
    hints = hints_loader.get_hints()
    issuer_data = hints["issuers"].get(issuer_key, {})
    yaml_path = hints_loader.issuer_yaml_path(issuer_key)
    if yaml_path is None:
        raise HTTPException(status_code=404, detail=f"YAML file not found for issuer '{issuer_key}'")
    return issuer_key, issuer_data, yaml_path


# ---------------------------------------------------------------------------
# GET /api/hints  — list all issuer files with metadata
# ---------------------------------------------------------------------------

@router.get("", response_model=list[IssuerSummary])
def list_hints():
    """List all issuer hint files with summary metadata."""
    hints = hints_loader.get_hints()
    result: list[IssuerSummary] = []

    for issuer_entry in hints_loader.list_issuers():
        issuer_key  = issuer_entry["name"]
        slug        = issuer_entry["slug"]
        file_name   = issuer_entry.get("file")
        file_path   = Path(issuer_entry["file_path"]) if issuer_entry.get("file_path") else None

        issuer_data     = hints["issuers"].get(issuer_key, {})
        field_hints     = issuer_data.get("field_hints", {})
        section_headings = issuer_data.get("section_headings", [])
        last_modified   = _file_mtime_iso(file_path) if file_path else None

        result.append(IssuerSummary(
            slug=slug,
            name=issuer_key,
            file=file_name,
            field_hints_count=len(field_hints),
            section_headings=section_headings,
            last_modified=last_modified,
        ))

    return result


# ---------------------------------------------------------------------------
# GET /api/hints/cross-issuer
# ---------------------------------------------------------------------------

@router.get("/cross-issuer")
def get_cross_issuer_hints():
    """Return all cross-issuer field_level_hints."""
    hints = hints_loader.get_hints()
    return hints.get("field_level_hints", {})


# ---------------------------------------------------------------------------
# PUT /api/hints/cross-issuer
# ---------------------------------------------------------------------------

@router.put("/cross-issuer")
def update_cross_issuer_hints(body: dict):
    """
    Overwrite the cross-issuer hints YAML with the supplied dict.
    The body should be the full field_level_hints mapping.
    """
    cross_path = hints_loader.HINTS_DIR / "cross_issuer_field_hints.yaml"
    if not cross_path.exists():
        raise HTTPException(status_code=404, detail="cross_issuer_field_hints.yaml not found")

    # Load existing to preserve top-level YAML comment header (best-effort)
    existing = _load_yaml_file(cross_path)

    # Merge: keep _description if not in body
    if "_description" not in body and "_description" in existing:
        body["_description"] = existing["_description"]

    _save_yaml_file(cross_path, body)
    return {"status": "saved", "file": cross_path.name}


# ---------------------------------------------------------------------------
# GET /api/hints/issuers/{issuer_slug}
# ---------------------------------------------------------------------------

@router.get("/issuers/{issuer_slug}")
def get_issuer_hints(issuer_slug: str):
    """Return full hints dict for one issuer."""
    issuer_key, issuer_data, _ = _resolve_issuer(issuer_slug)
    return {"issuer_key": issuer_key, "slug": issuer_slug, **issuer_data}


# ---------------------------------------------------------------------------
# PUT /api/hints/issuers/{issuer_slug}
# ---------------------------------------------------------------------------

@router.put("/issuers/{issuer_slug}")
def update_issuer_hints(issuer_slug: str, body: dict):
    """
    Overwrite the issuer hints YAML with the supplied dict.
    The body should be the full issuer hints object (without 'issuer_key'
    or 'slug' wrapper — those are set automatically).
    """
    issuer_key, _, yaml_path = _resolve_issuer(issuer_slug)

    # Load existing YAML to preserve issuer_key
    existing = _load_yaml_file(yaml_path)

    # Inject/preserve issuer_key
    body["issuer_key"] = issuer_key

    _save_yaml_file(yaml_path, body)
    return {"status": "saved", "file": yaml_path.name, "issuer_key": issuer_key}


# ---------------------------------------------------------------------------
# GET /api/hints/issuers/{issuer_slug}/fields/{field_path}
# ---------------------------------------------------------------------------

@router.get("/issuers/{issuer_slug}/fields/{field_path:path}")
def get_issuer_field_hint(issuer_slug: str, field_path: str):
    """Return the hint for a single field within an issuer."""
    _, issuer_data, _ = _resolve_issuer(issuer_slug)
    field_hints = issuer_data.get("field_hints", {})
    hint = field_hints.get(field_path)
    if hint is None:
        raise HTTPException(
            status_code=404,
            detail=f"Field '{field_path}' not found for issuer '{issuer_slug}'"
        )
    return {"field_path": field_path, **hint}


# ---------------------------------------------------------------------------
# PUT /api/hints/issuers/{issuer_slug}/fields/{field_path}
# ---------------------------------------------------------------------------

@router.put("/issuers/{issuer_slug}/fields/{field_path:path}")
def update_issuer_field_hint(issuer_slug: str, field_path: str, body: FieldHintUpdate):
    """
    Update a single field hint for one issuer.
    Only provided (non-None) fields are updated; others are preserved.
    """
    issuer_key, _, yaml_path = _resolve_issuer(issuer_slug)

    # Load full YAML so we can do a targeted update
    yaml_data = _load_yaml_file(yaml_path)

    field_hints = yaml_data.setdefault("field_hints", {})
    existing_hint = field_hints.get(field_path, {})

    # Apply partial update
    update_dict = body.model_dump(exclude_none=True)
    existing_hint.update(update_dict)
    field_hints[field_path] = existing_hint

    _save_yaml_file(yaml_path, yaml_data)
    return {"status": "saved", "field_path": field_path, "hint": existing_hint}


# ---------------------------------------------------------------------------
# PUT /api/hints/cross-issuer/fields/{field_path}
# ---------------------------------------------------------------------------

@router.put("/cross-issuer/fields/{field_path:path}")
def update_cross_issuer_field_hint(field_path: str, body: FieldHintUpdate):
    """
    Update a single field hint in the cross-issuer hints file.
    Only provided (non-None) fields are updated; others are preserved.
    """
    cross_path = hints_loader.HINTS_DIR / "cross_issuer_field_hints.yaml"
    if not cross_path.exists():
        raise HTTPException(status_code=404, detail="cross_issuer_field_hints.yaml not found")

    yaml_data = _load_yaml_file(cross_path)
    existing_hint = yaml_data.get(field_path, {})

    update_dict = body.model_dump(exclude_none=True)
    existing_hint.update(update_dict)
    yaml_data[field_path] = existing_hint

    _save_yaml_file(cross_path, yaml_data)
    return {"status": "saved", "field_path": field_path, "hint": existing_hint}
