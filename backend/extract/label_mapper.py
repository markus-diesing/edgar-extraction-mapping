"""
label_mapper.py — YAML-backed label → PRISM field path mapper.

Two source files are loaded and merged in priority order:

  Layer 1 (lowest)  files/label_map_cross_issuer.yaml  — hand-curated baseline
  Layer 2           files/label_map_user.yaml           — UI-added entries (written by label_map_router)
  Layer 3 (highest) issuer YAML  table_labels section   — per-issuer caller-supplied dict

Both YAML files are mtime-cached and reload on file change without a server
restart (same pattern as financial_glossary.md and hints_loader).

label_map_user.yaml is created on first programmatic write; safe to delete
(resets to cross-issuer baseline only).

Usage
-----
    from extract.label_mapper import build_label_map, resolve_label

    label_map = build_label_map(issuer_table_labels=issuer_hints.get("table_labels", {}))
    field_path = resolve_label("Maturity Date", label_map)
    # → "structuredProductsGeneric.maturityDate"
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

import config
from extract.field_parsers import FIELD_PARSERS, Callable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File paths (exported so the router can read/write without reimporting config)
# ---------------------------------------------------------------------------

LABEL_MAP_CROSS_PATH = config.PROJECT_ROOT / "files" / "label_map_cross_issuer.yaml"
LABEL_MAP_USER_PATH  = config.PROJECT_ROOT / "files" / "label_map_user.yaml"


# ---------------------------------------------------------------------------
# Normalization helper (also imported by html_extractor)
# ---------------------------------------------------------------------------

def _norm(label: str) -> str:
    """
    Normalize a label for lookup: strip, lowercase, collapse whitespace,
    and remove a trailing colon.

    Many issuers (Barclays, JPMorgan, BofA, …) suffix every Key Terms label
    with ':' in the HTML cell (e.g. "Reference Asset:").  The label map stores
    entries without the colon.  Stripping it here means the YAML never needs
    colon variants — any label matches whether or not it carries a trailing colon.
    Footnote markers (*, †, ‡) are also stripped for the same reason.
    """
    normalized = re.sub(r"\s+", " ", label.strip().lower())
    # Strip in this order so "Label: †" and "Label*(1):" all reduce cleanly:
    # 1. Footnote markers (* † ‡ § ¶) anywhere at the tail
    normalized = re.sub(r"[\s\*†‡§¶]+$", "", normalized).strip()
    # 2. Parenthesised numeric footnotes e.g. "(1)" "(2)"
    normalized = re.sub(r"\s*\(\d+\)$", "", normalized).strip()
    # 3. Trailing colon (now that markers are gone)
    normalized = normalized.rstrip(":").strip()
    return normalized


# ---------------------------------------------------------------------------
# Mtime-cached YAML loaders
# ---------------------------------------------------------------------------

_cross_cache: dict[str, str] | None = None
_cross_mtime: float | None = None

_user_cache:  dict[str, str] | None = None
_user_mtime:  float | None = None


def _load_yaml_labels(path: Path, cache_ref: list, mtime_ref: list) -> dict[str, str]:
    """
    Generic mtime-cached loader for a label-map YAML file.

    cache_ref / mtime_ref are single-element lists used as mutable cells
    (avoids global keyword inside a helper function).
    Returns a normalized {label_norm: field_path} dict.
    """
    if not path.exists():
        return {}

    mtime = path.stat().st_mtime
    if cache_ref[0] is not None and mtime == mtime_ref[0]:
        return cache_ref[0]

    try:
        with path.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.error("Could not load %s: %s", path.name, exc)
        return cache_ref[0] or {}

    raw_labels: dict = data.get("labels", {})
    normalized = {
        _norm(k): v
        for k, v in raw_labels.items()
        if isinstance(k, str) and isinstance(v, str)
    }
    cache_ref[0] = normalized
    mtime_ref[0]  = mtime
    log.info("Loaded label map: %d entries from %s", len(normalized), path.name)
    return normalized


# Mutable cells to hold cache state without needing global declarations
_cross_cell: list = [None]
_cross_mt:   list = [None]
_user_cell:  list = [None]
_user_mt:    list = [None]


def _load_cross_issuer() -> dict[str, str]:
    return _load_yaml_labels(LABEL_MAP_CROSS_PATH, _cross_cell, _cross_mt)


def _load_user() -> dict[str, str]:
    return _load_yaml_labels(LABEL_MAP_USER_PATH, _user_cell, _user_mt)


# ---------------------------------------------------------------------------
# User YAML write helpers (called by label_map_router)
# ---------------------------------------------------------------------------

def _read_user_raw() -> dict:
    """Return the raw parsed dict from label_map_user.yaml (or empty)."""
    if not LABEL_MAP_USER_PATH.exists():
        return {"_version": "1.0", "_description": "User-added label mappings (managed via UI)", "labels": {}}
    try:
        with LABEL_MAP_USER_PATH.open(encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception:
        return {"labels": {}}


def _write_user_raw(data: dict) -> None:
    """Serialise and write data to label_map_user.yaml; invalidate cache."""
    LABEL_MAP_USER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LABEL_MAP_USER_PATH.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=True, default_flow_style=False)
    # Invalidate cache so next build_label_map() picks up the change immediately
    _user_cell[0] = None
    _user_mt[0]   = None


def add_user_entry(label_raw: str, field_path: str) -> None:
    """Add or overwrite a user label mapping and persist to YAML."""
    data = _read_user_raw()
    labels: dict = data.setdefault("labels", {})
    # Store with the raw case the user typed (normalization happens at match time)
    labels[label_raw.strip()] = field_path.strip()
    _write_user_raw(data)
    log.info("Added user label mapping: %r → %s", label_raw, field_path)


def remove_user_entry(label_norm: str) -> bool:
    """
    Remove a user label mapping by normalized key.
    Returns True if removed, False if not found.
    """
    data = _read_user_raw()
    labels: dict = data.get("labels", {})
    # Find and remove matching key (normalize each key for comparison)
    to_remove = [k for k in labels if _norm(k) == label_norm]
    if not to_remove:
        return False
    for k in to_remove:
        del labels[k]
    _write_user_raw(data)
    log.info("Removed user label mapping: %r", label_norm)
    return True


def list_user_entries() -> list[dict]:
    """Return all user-added label entries as a list of {label, field_path, source}."""
    data = _read_user_raw()
    return [
        {"label": k, "label_norm": _norm(k), "field_path": v, "source": "user"}
        for k, v in data.get("labels", {}).items()
    ]


def list_cross_entries() -> list[dict]:
    """Return all cross-issuer baseline entries as a list of {label, field_path, source}."""
    if not LABEL_MAP_CROSS_PATH.exists():
        return []
    try:
        with LABEL_MAP_CROSS_PATH.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception:
        return []
    return [
        {"label": k, "label_norm": _norm(k), "field_path": v, "source": "cross_issuer"}
        for k, v in data.get("labels", {}).items()
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_label_map(issuer_table_labels: dict[str, str] | None = None) -> dict[str, str]:
    """
    Build a merged label → PRISM field path lookup dict.

    Merge order (later wins on conflict):
        1. Cross-issuer baseline  (label_map_cross_issuer.yaml — hand-curated)
        2. User-added entries     (label_map_user.yaml — via Expert UI)
        3. Per-issuer overrides   (issuer YAML table_labels — most specific)

    All layers are normalized before merging so matching is case-insensitive.
    """
    result: dict[str, str] = {}

    result.update(_load_cross_issuer())
    result.update(_load_user())

    if issuer_table_labels:
        overrides = {_norm(k): v for k, v in issuer_table_labels.items()
                     if isinstance(k, str) and isinstance(v, str)}
        if overrides:
            log.debug("Applying %d per-issuer label overrides", len(overrides))
        result.update(overrides)

    return result


def resolve_label(raw_label: str, label_map: dict[str, str]) -> str | None:
    """Resolve a raw table label to a PRISM field path, or None if not found."""
    return label_map.get(_norm(raw_label))


def get_parser(field_path: str) -> Callable | None:
    """Return the typed parser function for a PRISM field path, or None."""
    return FIELD_PARSERS.get(field_path)
