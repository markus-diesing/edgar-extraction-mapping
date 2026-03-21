"""
hints_loader.py — Load and cache extraction hints from YAML files.

Replaces direct reads of files/issuer_extraction_hints.json.  Hints are
stored as human-editable YAML files in files/hints/:

  files/hints/cross_issuer_field_hints.yaml   → field_level_hints section
  files/hints/issuer_<Name>.yaml              → per-issuer entries

The module caches the merged dict and reloads automatically when any YAML
file's modification time changes.

Usage
-----
    from hints_loader import get_hints

    hints = get_hints()   # returns dict identical to the old JSON structure
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml  # PyYAML — already in venv

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
HINTS_DIR = config.PROJECT_ROOT / "files" / "hints"

# Well-known YAML file names and their roles in the hints structure
_CROSS_ISSUER_FILE  = "cross_issuer_field_hints.yaml"  # → field_level_hints
_SCHEMA_GUIDE_FILE  = "prism_schema_guide.yaml"         # → schema_guide (injected as context)


# ---------------------------------------------------------------------------
# Internal cache
# ---------------------------------------------------------------------------
_cache: dict[str, Any] | None = None
_cache_mtimes: dict[str, float] = {}   # filename → mtime


def _yaml_files() -> list[Path]:
    """Return all *.yaml files in HINTS_DIR, sorted for determinism."""
    if not HINTS_DIR.exists():
        return []
    return sorted(HINTS_DIR.glob("*.yaml"))


def _mtimes_changed() -> bool:
    """Return True if any YAML file has been added, removed, or modified."""
    files = _yaml_files()
    current: dict[str, float] = {str(f): f.stat().st_mtime for f in files}
    return current != _cache_mtimes


def _load_yaml(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:
        log.warning("Could not load %s: %s", path, exc)
        return {}


def _build_hints() -> dict:
    """
    Merge all YAML files into a dict matching the original JSON structure:

    {
        "_version": "1.0",
        "_description": "...",
        "issuers": { <issuer_key>: { ... }, ... },
        "field_level_hints": { <field_path>: { ... }, ... },
    }
    """
    result: dict[str, Any] = {
        "_version": "1.0",
        "_description": (
            "Per-issuer extraction hints for the PRISM extractor (loaded from YAML). "
            "Each issuer entry contains section headings, field aliases (PRISM dot-path "
            "→ list of synonyms found in that issuer's filings), and notes."
        ),
        "issuers": {},
        "field_level_hints": {},
        "schema_guide": {},     # loaded from prism_schema_guide.yaml — structural patterns
    }

    files = _yaml_files()
    if not files:
        log.warning("No YAML hint files found in %s — returning empty hints", HINTS_DIR)
        return result

    for path in files:
        data = _load_yaml(path)
        if not data:
            continue

        name = path.name

        if name == _CROSS_ISSUER_FILE:
            # Cross-issuer field rules — everything except _description becomes field_level_hints
            for k, v in data.items():
                if k == "_description":
                    result["field_level_hints"]["_description"] = v
                else:
                    result["field_level_hints"][k] = v

        elif name == _SCHEMA_GUIDE_FILE:
            # PRISM schema structural guide — loaded as schema_guide for use in prompts
            result["schema_guide"] = data
            log.debug("Loaded PRISM schema guide from %s", path.name)

        elif name.startswith("issuer_"):
            # Per-issuer file: the 'issuer_key' field names the dict key
            issuer_key = data.get("issuer_key")
            if not issuer_key:
                log.warning("No 'issuer_key' in %s — skipping", path)
                continue

            # Build the per-issuer block (strip loader-internal fields)
            block: dict[str, Any] = {}
            for k, v in data.items():
                if k == "issuer_key":
                    continue
                block[k] = v

            result["issuers"][issuer_key] = block
            log.debug("Loaded issuer hints: %s → %s", name, issuer_key)

    log.info(
        "Loaded hints from %d YAML files — %d issuers, %d cross-issuer fields, schema_guide=%s",
        len(files),
        len(result["issuers"]),
        len([k for k in result["field_level_hints"] if not k.startswith("_")]),
        "loaded" if result["schema_guide"] else "missing",
    )
    return result


def _refresh_cache() -> dict:
    global _cache, _cache_mtimes
    files = _yaml_files()
    _cache_mtimes = {str(f): f.stat().st_mtime for f in files}
    _cache = _build_hints()
    return _cache


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_hints() -> dict:
    """
    Return the merged hints dict, reloading from disk if any YAML file changed.
    Thread-safety note: this module is used in a single-threaded FastAPI context
    (one worker), so no locking is needed.
    """
    global _cache
    if _cache is None or _mtimes_changed():
        _refresh_cache()
    return _cache  # type: ignore[return-value]


def reload_hints() -> dict:
    """Force a cache refresh, ignoring mtime check."""
    return _refresh_cache()


# ---------------------------------------------------------------------------
# Slug ↔ issuer-key mapping helpers
# ---------------------------------------------------------------------------

def _slugify(name: str) -> str:
    """Convert an issuer key (e.g. 'JPMorgan Chase Financial Company LLC') to a URL slug."""
    slug = name.lower()
    # Replace non-alphanumeric sequences with underscore
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    # Strip leading/trailing underscores
    slug = slug.strip("_")
    return slug


def list_issuers() -> list[dict]:
    """
    Return a list of {slug, name, file} for all loaded issuers, sorted by name.
    """
    hints = get_hints()
    result = []
    for issuer_key, data in hints.get("issuers", {}).items():
        slug = _slugify(issuer_key)
        # Find matching YAML file
        file_path = None
        for path in _yaml_files():
            if path.name.startswith("issuer_"):
                loaded = _load_yaml(path)
                if loaded.get("issuer_key") == issuer_key:
                    file_path = path
                    break
        result.append({
            "slug": slug,
            "name": issuer_key,
            "file": file_path.name if file_path else None,
            "file_path": str(file_path) if file_path else None,
        })
    return sorted(result, key=lambda x: x["name"])


def slug_to_issuer_key(slug: str) -> str | None:
    """Resolve a URL slug back to the original issuer key."""
    hints = get_hints()
    for issuer_key in hints.get("issuers", {}):
        if _slugify(issuer_key) == slug:
            return issuer_key
    return None


def issuer_yaml_path(issuer_key: str) -> Path | None:
    """Return the Path of the YAML file for the given issuer_key, or None."""
    for path in _yaml_files():
        if path.name.startswith("issuer_"):
            data = _load_yaml(path)
            if data.get("issuer_key") == issuer_key:
                return path
    return None
