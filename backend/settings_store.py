"""
settings_store.py — live-reload loader for files/runtime_settings.yaml.

Provides get_settings() and update_settings() for runtime-configurable
overrides of config.py defaults. Changes are persisted to the YAML file
and take effect on the next request (mtime-checked cache).

Usage in extractor.py:
    from settings_store import get_settings
    if get_settings().get("sectioned_extraction", config.SECTIONED_EXTRACTION):
        ...
"""
import threading
from pathlib import Path

import yaml
import config

_LOCK = threading.Lock()
_cache: dict | None = None
_mtime: float = 0.0

_SETTINGS_PATH: Path = config.PROJECT_ROOT / "files" / "runtime_settings.yaml"

# Defaults mirror config.py so the store is always self-consistent
_DEFAULTS: dict = {
    "sectioned_extraction": config.SECTIONED_EXTRACTION,
    "section_merge_confidence_delta": config.SECTION_MERGE_CONFIDENCE_DELTA,
    "classification_gate_confidence": config.CLASSIFICATION_GATE_CONFIDENCE,
}


def get_settings() -> dict:
    """Return current runtime settings dict. Reloads from YAML if file changed."""
    global _cache, _mtime
    try:
        mtime = _SETTINGS_PATH.stat().st_mtime
    except FileNotFoundError:
        return dict(_DEFAULTS)
    with _LOCK:
        if _cache is None or mtime != _mtime:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            # Merge with defaults so missing keys always return a value
            _cache = {**_DEFAULTS, **loaded}
            _mtime = mtime
    return dict(_cache)


def update_settings(updates: dict) -> dict:
    """Persist updated keys to the YAML file and invalidate cache."""
    global _cache, _mtime
    with _LOCK:
        # Read current file (or defaults if missing)
        try:
            with open(_SETTINGS_PATH, encoding="utf-8") as f:
                current = yaml.safe_load(f) or {}
        except FileNotFoundError:
            current = {}
        current.update(updates)
        _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_SETTINGS_PATH, "w", encoding="utf-8") as f:
            yaml.dump(current, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        _cache = None
        _mtime = 0.0
    return get_settings()
