"""
section_loader.py — live-reload loader for files/sections/section_specs.yaml.
Returns raw dicts; section_router.py converts them to SectionSpec objects.
"""
import threading
import time
from pathlib import Path
import yaml

import config

_LOCK = threading.Lock()
_cache: dict | None = None
_mtime: float = 0.0

_SPECS_PATH = config.PROJECT_ROOT / "files" / "sections" / "section_specs.yaml"


def get_section_specs() -> dict[str, dict]:
    """Return all section specs as a dict. Reloads from YAML if file has changed."""
    global _cache, _mtime
    try:
        mtime = _SPECS_PATH.stat().st_mtime
    except FileNotFoundError:
        return {}
    with _LOCK:
        if _cache is None or mtime != _mtime:
            with open(_SPECS_PATH, encoding="utf-8") as f:
                _cache = yaml.safe_load(f) or {}
            _mtime = mtime
    return dict(_cache)


def save_section_spec(name: str, updates: dict) -> None:
    """Update a single section's spec in the YAML file."""
    with _LOCK:
        with open(_SPECS_PATH, encoding="utf-8") as f:
            all_specs = yaml.safe_load(f) or {}
        if name not in all_specs:
            all_specs[name] = {}
        # Only update provided keys
        for k, v in updates.items():
            all_specs[name][k] = v
        with open(_SPECS_PATH, "w", encoding="utf-8") as f:
            yaml.dump(all_specs, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        # Invalidate cache
        global _cache, _mtime
        _cache = None
        _mtime = 0.0
