"""
label_mapper.py — YAML-backed label → PRISM field path mapper.

Loads the cross-issuer label map from:
    files/label_map_cross_issuer.yaml

Per-issuer overrides are supplied by the caller (from the issuer YAML
`table_labels` section loaded via hints_loader).

Matching is case-insensitive and strips leading/trailing whitespace.

Usage
-----
    from extract.label_mapper import build_label_map, resolve_label

    # Build the merged map (call once per extraction run)
    label_map = build_label_map(issuer_table_labels=issuer_hints.get("table_labels", {}))

    # Resolve a raw label cell value to a PRISM field path
    field_path = resolve_label("Maturity Date", label_map)
    # → "structuredProductsGeneric.maturityDate"
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

import config
from extract.field_parsers import FIELD_PARSERS, Callable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-issuer YAML — mtime-cached (same pattern as hints_loader)
# ---------------------------------------------------------------------------

_LABEL_MAP_PATH = config.PROJECT_ROOT / "files" / "label_map_cross_issuer.yaml"

_cross_cache: dict[str, Any] | None = None
_cross_mtime: float | None = None


def _load_cross_issuer_yaml() -> dict[str, str]:
    """Return the normalized cross-issuer label map, reloading if changed."""
    global _cross_cache, _cross_mtime

    if not _LABEL_MAP_PATH.exists():
        log.warning("label_map_cross_issuer.yaml not found at %s", _LABEL_MAP_PATH)
        return {}

    mtime = _LABEL_MAP_PATH.stat().st_mtime
    if _cross_cache is not None and mtime == _cross_mtime:
        return _cross_cache

    try:
        with _LABEL_MAP_PATH.open(encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except Exception as exc:
        log.error("Could not load label_map_cross_issuer.yaml: %s", exc)
        return _cross_cache or {}

    raw_labels: dict = data.get("labels", {})
    normalized = {_norm(k): v for k, v in raw_labels.items() if isinstance(k, str) and isinstance(v, str)}

    _cross_cache = normalized
    _cross_mtime = mtime
    log.info("Loaded cross-issuer label map: %d entries from %s", len(normalized), _LABEL_MAP_PATH.name)
    return _cross_cache


# ---------------------------------------------------------------------------
# Normalization helper
# ---------------------------------------------------------------------------

def _norm(label: str) -> str:
    """Normalize a label for lookup: strip, lowercase, collapse whitespace."""
    import re
    return re.sub(r"\s+", " ", label.strip().lower())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_label_map(issuer_table_labels: dict[str, str] | None = None) -> dict[str, str]:
    """
    Build a merged label → PRISM field path lookup dict.

    Merge order (later wins on conflict):
        1. Cross-issuer baseline (from label_map_cross_issuer.yaml)
        2. Per-issuer overrides  (from issuer YAML `table_labels` section)

    Both layers are normalized before merging so matching is case-insensitive.

    Args:
        issuer_table_labels:  The `table_labels` dict from the matched issuer
                              hints block, or None / {} if no issuer matched.

    Returns:
        dict mapping normalized label → PRISM field path
    """
    result: dict[str, str] = {}

    # Layer 1: cross-issuer baseline
    result.update(_load_cross_issuer_yaml())

    # Layer 2: per-issuer overrides
    if issuer_table_labels:
        overrides = {_norm(k): v for k, v in issuer_table_labels.items()
                     if isinstance(k, str) and isinstance(v, str)}
        if overrides:
            log.debug("Applying %d per-issuer label overrides", len(overrides))
        result.update(overrides)

    return result


def resolve_label(raw_label: str, label_map: dict[str, str]) -> str | None:
    """
    Resolve a raw table label to a PRISM field path.

    Returns None if no mapping is found.
    """
    return label_map.get(_norm(raw_label))


def get_parser(field_path: str) -> Callable | None:
    """
    Return the typed parser function for a PRISM field path, or None.

    For array paths (containing [*]), an exact match is tried first.
    Array paths like "underlyingTerms.underlyingAssets[*].name" are
    stored verbatim in FIELD_PARSERS and matched exactly.
    """
    return FIELD_PARSERS.get(field_path)
