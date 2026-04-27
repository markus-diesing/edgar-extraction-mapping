"""
Underlying Data Module — Field Configuration Manager.

Reads, validates and writes ``files/underlying_field_config.yaml``.
Provides a thread-safe in-process cache with invalidation on write so the
router always serves fresh data without hitting disk on every request.

Public API
----------
load()              → FieldConfig
save(cfg)           → None
get_enabled_fields() → list[FieldDef]
toggle_field(name, enabled) → FieldConfig
reorder_fields(names) → FieldConfig
get_field(name)     → FieldDef | None
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FieldDef:
    """Definition of one configurable field."""
    name: str
    display_name: str
    enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "enabled": self.enabled,
        }


@dataclass
class FieldConfig:
    """Full field configuration loaded from YAML."""
    version: str
    fields: list[FieldDef] = field(default_factory=list)

    # ── Convenience accessors ──────────────────────────────────────────────

    @property
    def enabled_fields(self) -> list[FieldDef]:
        """Return only the enabled fields, preserving display order."""
        return [f for f in self.fields if f.enabled]

    @property
    def field_names(self) -> list[str]:
        """Return all field names (enabled and disabled)."""
        return [f.name for f in self.fields]

    def get(self, name: str) -> FieldDef | None:
        """Look up a field by name. Returns ``None`` if not found."""
        for f in self.fields:
            if f.name == name:
                return f
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "fields": [f.to_dict() for f in self.fields],
        }


# ---------------------------------------------------------------------------
# In-process cache (module-level, thread-safe)
# ---------------------------------------------------------------------------

_cache: FieldConfig | None = None
_cache_lock = threading.Lock()


def _invalidate_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


# ---------------------------------------------------------------------------
# YAML I/O
# ---------------------------------------------------------------------------

def _config_path() -> Path:
    return config.UNDERLYING_FIELD_CONFIG_FILE


def _parse_yaml(raw: dict[str, Any]) -> FieldConfig:
    """Parse the raw YAML dict into a :class:`FieldConfig`."""
    version = str(raw.get("version", "1"))
    fields_raw = raw.get("fields", [])
    if not isinstance(fields_raw, list):
        raise ValueError("underlying_field_config.yaml: 'fields' must be a list")

    fields: list[FieldDef] = []
    seen: set[str] = set()
    for i, entry in enumerate(fields_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Field entry #{i} is not a mapping")
        name = str(entry.get("name", "")).strip()
        if not name:
            raise ValueError(f"Field entry #{i} has no 'name'")
        if name in seen:
            raise ValueError(f"Duplicate field name: {name!r}")
        seen.add(name)
        fields.append(FieldDef(
            name=name,
            display_name=str(entry.get("display_name", name)),
            enabled=bool(entry.get("enabled", True)),
        ))

    return FieldConfig(version=version, fields=fields)


def _dump_yaml(cfg: FieldConfig) -> str:
    """Serialise a :class:`FieldConfig` to YAML text."""
    data: dict[str, Any] = {
        "version": cfg.version,
        "fields": [f.to_dict() for f in cfg.fields],
    }
    return yaml.dump(data, default_flow_style=False, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load() -> FieldConfig:
    """Load the field configuration from disk (or in-process cache).

    Raises
    ------
    FileNotFoundError
        If the config YAML does not exist.
    ValueError
        If the YAML is malformed.
    """
    global _cache
    with _cache_lock:
        if _cache is not None:
            return _cache

    path = _config_path()
    if not path.exists():
        raise FileNotFoundError(f"Field config not found: {path}")

    raw_text = path.read_text(encoding="utf-8")
    try:
        raw = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise ValueError(
            f"underlying_field_config.yaml contains invalid YAML: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise ValueError(
            f"underlying_field_config.yaml: expected a YAML mapping at the top level, "
            f"got {type(raw).__name__}"
        )

    cfg = _parse_yaml(raw)
    log.debug("Loaded field config v%s (%d fields)", cfg.version, len(cfg.fields))

    with _cache_lock:
        _cache = cfg
    return cfg


def save(cfg: FieldConfig) -> None:
    """Persist a :class:`FieldConfig` to disk and invalidate the cache.

    The version is bumped to ``str(int(version) + 1)`` if it is purely numeric.
    If the version is not numeric the caller is expected to have updated it.

    Parameters
    ----------
    cfg:
        The configuration to persist.  The object is mutated in-place to
        reflect the bumped version number.
    """
    # Bump version
    try:
        cfg.version = str(int(cfg.version) + 1)
    except ValueError:
        pass   # non-numeric version — leave as-is

    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_yaml(cfg), encoding="utf-8")
    log.info("Saved field config v%s to %s", cfg.version, path)

    _invalidate_cache()


def get_enabled_fields() -> list[FieldDef]:
    """Return only the currently enabled fields in display order."""
    return load().enabled_fields


def get_field(name: str) -> FieldDef | None:
    """Look up one field definition by name."""
    return load().get(name)


def toggle_field(name: str, enabled: bool) -> FieldConfig:
    """Enable or disable a named field and persist the change.

    Parameters
    ----------
    name:
        The field name as it appears in the YAML.
    enabled:
        New enabled state.

    Returns
    -------
    FieldConfig
        The updated config (already saved to disk).

    Raises
    ------
    KeyError
        If *name* is not found in the config.
    """
    cfg = load()
    fdef = cfg.get(name)
    if fdef is None:
        raise KeyError(f"Unknown field: {name!r}")
    fdef.enabled = enabled
    save(cfg)
    return cfg


def reorder_fields(names: list[str]) -> FieldConfig:
    """Reorder the field list to match *names* and persist.

    Fields present in the config but missing from *names* are appended at
    the end of the list to prevent silent data loss.  Extra names in *names*
    that are not in the config are ignored.

    Parameters
    ----------
    names:
        Desired display order — list of field name strings.

    Returns
    -------
    FieldConfig
        The updated config (already saved to disk).
    """
    cfg = load()
    name_to_def: dict[str, FieldDef] = {f.name: f for f in cfg.fields}

    # Build ordered list from names, then append any remainder
    reordered: list[FieldDef] = []
    seen: set[str] = set()
    for n in names:
        if n in name_to_def and n not in seen:
            reordered.append(name_to_def[n])
            seen.add(n)

    # Append fields that were not in names (preserves unknown fields)
    for fdef in cfg.fields:
        if fdef.name not in seen:
            reordered.append(fdef)

    cfg.fields = reordered
    save(cfg)
    return cfg


def update_fields(updates: list[dict[str, Any]]) -> FieldConfig:
    """Apply a batch of field updates (name, display_name, enabled) and persist.

    Only fields that exist in the config are updated; unknown names are
    silently skipped.  Field *order* is updated to match the order of
    *updates* for those fields, remaining fields are appended in their
    current order.

    Parameters
    ----------
    updates:
        List of dicts, each with at minimum a ``"name"`` key.  Optional keys:
        ``"display_name"`` and ``"enabled"``.

    Returns
    -------
    FieldConfig
        The updated config (already saved to disk).
    """
    cfg = load()
    name_to_def: dict[str, FieldDef] = {f.name: f for f in cfg.fields}

    updated_names: list[str] = []
    for upd in updates:
        n = upd.get("name", "")
        fdef = name_to_def.get(n)
        if fdef is None:
            log.debug("update_fields: ignoring unknown field %r", n)
            continue
        if "display_name" in upd:
            fdef.display_name = str(upd["display_name"])
        if "enabled" in upd:
            fdef.enabled = bool(upd["enabled"])
        updated_names.append(n)

    # Re-order: updated fields first (in update order), then rest in original order
    seen = set(updated_names)
    reordered = [name_to_def[n] for n in updated_names if n in name_to_def]
    reordered += [f for f in cfg.fields if f.name not in seen]
    cfg.fields = reordered

    save(cfg)
    return cfg
