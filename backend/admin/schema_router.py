"""
schema_router.py — PRISM schema update management.

Endpoints:
  GET  /api/admin/schema/status
  POST /api/admin/schema/fetch
  GET  /api/admin/schema/pending/{fetch_id}
  POST /api/admin/schema/pending/{fetch_id}/activate
  DELETE /api/admin/schema/pending/{fetch_id}
"""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException

import config
import schema_loader
from schema_diff import compute_diff

log = logging.getLogger(__name__)
router = APIRouter(tags=["schema"])

PENDING_DIR = config.PRISM_SCHEMA_PENDING_DIR
ARCHIVE_DIR = config.PRISM_SCHEMA_ARCHIVE_DIR


def _ensure_dirs() -> None:
    PENDING_DIR.mkdir(parents=True, exist_ok=True)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _pending_schema_path(fetch_id: str) -> Path:
    return PENDING_DIR / f"{fetch_id}.schema.json"


def _pending_diff_path(fetch_id: str) -> Path:
    return PENDING_DIR / f"{fetch_id}.diff.json"


def _list_pending() -> list[dict]:
    """Return summary dicts for all pending fetches, newest first."""
    if not PENDING_DIR.exists():
        return []
    items = []
    for diff_file in sorted(PENDING_DIR.glob("*.diff.json"), reverse=True):
        try:
            diff = json.loads(diff_file.read_text(encoding="utf-8"))
            items.append({
                "fetch_id":          diff["fetch_id"],
                "fetched_at":        diff.get("fetched_at", ""),
                "new_schema_id":     diff.get("new_schema_id", ""),
                "new_content_hash":  diff.get("new_content_hash", ""),
                "same_content":      diff.get("same_content", True),
                "summary":           diff.get("summary", {}),
            })
        except Exception:
            pass
    return items


# ---------------------------------------------------------------------------
# GET /api/admin/schema/status
# ---------------------------------------------------------------------------

@router.get("/admin/schema/status")
def schema_status() -> dict:
    """Return active schema info and list of pending fetches."""
    active_path = config.PRISM_SCHEMA_FILE
    active_info: dict = {}
    if active_path.exists():
        try:
            raw = active_path.read_text(encoding="utf-8")
            schema = json.loads(raw)
            import hashlib, re
            content_hash = hashlib.sha256(
                json.dumps(schema, sort_keys=True).encode()
            ).hexdigest()[:16]
            sid = schema.get("$id", "")
            m = re.search(r"\.(v\d+)\.", sid)
            version = m.group(1) if m else "unknown"
            models = [
                e.get("properties", {}).get("model", {}).get("const")
                for e in schema.get("oneOf", [])
                if e.get("properties", {}).get("model", {}).get("const")
            ]
            stat = active_path.stat()
            active_info = {
                "schema_id":        sid,
                "version":          version,
                "content_hash":     content_hash,
                "path":             str(active_path.relative_to(config.PROJECT_ROOT)),
                "file_size_bytes":  stat.st_size,
                "last_modified":    datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc
                ).isoformat(),
                "models":           models,
            }
        except Exception as e:
            active_info = {"error": str(e)}

    return {
        "active":     active_info,
        "source_url": config.PRISM_SCHEMA_URL,
        "pending":    _list_pending(),
    }


# ---------------------------------------------------------------------------
# POST /api/admin/schema/fetch
# ---------------------------------------------------------------------------

@router.post("/admin/schema/fetch")
def fetch_schema() -> dict:
    """
    Fetch the latest schema from PRISM_SCHEMA_URL, store it in pending/,
    compute a full diff against the active schema, and return the diff.
    """
    _ensure_dirs()
    fetch_id = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    fetched_at = datetime.now(tz=timezone.utc).isoformat()

    # Fetch
    try:
        resp = httpx.get(config.PRISM_SCHEMA_URL, timeout=15.0)
        resp.raise_for_status()
        new_schema = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to fetch schema: {e}")

    # Validate minimal structure
    if "oneOf" not in new_schema or "$defs" not in new_schema:
        raise HTTPException(status_code=502, detail="Fetched JSON does not look like a PRISM schema")

    # Save pretty-printed (minified schemas become readable)
    pending_path = _pending_schema_path(fetch_id)
    pending_path.write_text(
        json.dumps(new_schema, indent=4, ensure_ascii=False),
        encoding="utf-8",
    )

    # Compute diff
    try:
        diff = compute_diff(
            current_path=config.PRISM_SCHEMA_FILE,
            new_path=pending_path,
            fetch_id=fetch_id,
            source_url=config.PRISM_SCHEMA_URL,
        )
    except Exception as e:
        pending_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"Diff computation failed: {e}")

    diff["fetched_at"] = fetched_at

    # Store diff
    diff_path = _pending_diff_path(fetch_id)
    diff_path.write_text(
        json.dumps(diff, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    log.info(
        "Schema fetched: fetch_id=%s  breaking=%d  caution=%d  safe=%d",
        fetch_id,
        diff["summary"]["breaking"],
        diff["summary"]["caution"],
        diff["summary"]["safe"],
    )
    return diff


# ---------------------------------------------------------------------------
# GET /api/admin/schema/pending/{fetch_id}
# ---------------------------------------------------------------------------

@router.get("/admin/schema/pending/{fetch_id}")
def get_pending_diff(fetch_id: str) -> dict:
    """Return the stored diff for a pending fetch."""
    diff_path = _pending_diff_path(fetch_id)
    if not diff_path.exists():
        raise HTTPException(status_code=404, detail="Pending diff not found")
    return json.loads(diff_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# POST /api/admin/schema/pending/{fetch_id}/activate
# ---------------------------------------------------------------------------

@router.post("/admin/schema/pending/{fetch_id}/activate")
def activate_schema(fetch_id: str) -> dict:
    """
    Activate a pending schema:
      1. Archive the current active schema.
      2. Copy the pending schema to the active path.
      3. Reload schema_loader cache.
      4. Remove the pending files.
    """
    pending_path = _pending_schema_path(fetch_id)
    if not pending_path.exists():
        raise HTTPException(status_code=404, detail="Pending schema not found")

    _ensure_dirs()

    # Archive current
    active_path = config.PRISM_SCHEMA_FILE
    archived_name = ""
    if active_path.exists():
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        archived_name = f"prism-archive-{ts}.schema.json"
        shutil.copy2(active_path, ARCHIVE_DIR / archived_name)
        log.info("Archived current schema as %s", archived_name)

    # Activate
    shutil.copy2(pending_path, active_path)
    schema_loader.reload()

    # Clean up pending files
    _pending_diff_path(fetch_id).unlink(missing_ok=True)
    pending_path.unlink(missing_ok=True)

    log.info("Schema activated from fetch_id=%s", fetch_id)
    return {
        "ok":          True,
        "fetch_id":    fetch_id,
        "archived_as": archived_name,
        "new_version": schema_loader.get_schema_version(),
        "models":      schema_loader.list_models(),
    }


# ---------------------------------------------------------------------------
# DELETE /api/admin/schema/pending/{fetch_id}
# ---------------------------------------------------------------------------

@router.delete("/admin/schema/pending/{fetch_id}")
def discard_pending(fetch_id: str) -> dict:
    """Discard a pending schema and its diff."""
    _pending_schema_path(fetch_id).unlink(missing_ok=True)
    _pending_diff_path(fetch_id).unlink(missing_ok=True)
    return {"ok": True, "fetch_id": fetch_id}
