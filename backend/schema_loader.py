"""
PRISM schema loader.

Reads prism-v1.schema.json (a JSON Schema oneOf document) at runtime and
provides:
  - list_models()        → all model names found in the oneOf array
  - get_model_schema()   → the resolved (de-ref'd) schema for one model
  - get_field_descriptors() → flat list of FieldDescriptor for extraction prompts
  - load_cusip_mapping() → dict mapping CUSIP → {payout_type_id, source_url}

The schema file is loaded once and cached.  Call reload() to refresh after
the file is updated.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import openpyxl

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FieldDescriptor:
    """A single extractable field from a PRISM model."""
    path: str          # dot-notation path, e.g. "barrier.triggerDetails.triggerLevelRelative"
    label: str         # human-readable label derived from the last path segment
    data_type: str     # "string" | "number" | "integer" | "boolean" | "object" | "array"
    description: str   # from JSON Schema "description" field, or empty
    required: bool
    enum_values: list[str] = field(default_factory=list)   # allowed values if enum/const


@dataclass
class CusipMapping:
    cusip: str
    payout_type_id: str
    source_url: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, Any] | None = None
_CUSIP_CACHE: dict[str, CusipMapping] | None = None


def _load_raw_schema() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        with open(config.PRISM_SCHEMA_FILE, encoding="utf-8") as fh:
            _SCHEMA_CACHE = json.load(fh)
    return _SCHEMA_CACHE


def reload() -> None:
    """Force re-read of the schema file and CUSIP mapping."""
    global _SCHEMA_CACHE, _CUSIP_CACHE
    _SCHEMA_CACHE = None
    _CUSIP_CACHE = None


def _resolve_ref(ref: str, root: dict[str, Any]) -> dict[str, Any]:
    """Resolve a JSON $ref like '#/$defs/Foo' against the root schema."""
    if not ref.startswith("#/"):
        return {}
    parts = ref[2:].split("/")
    node = root
    for part in parts:
        node = node.get(part, {})
    return node


def _resolve(schema_node: dict[str, Any], root: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively resolve all $ref entries in a schema node."""
    if depth > 10:
        return schema_node
    if "$ref" in schema_node:
        resolved = _resolve(_resolve_ref(schema_node["$ref"], root), root, depth + 1)
        # Merge any sibling keys alongside the $ref (rare but valid JSON Schema)
        merged = {k: v for k, v in schema_node.items() if k != "$ref"}
        merged.update(resolved)
        return merged
    result: dict[str, Any] = {}
    for k, v in schema_node.items():
        if isinstance(v, dict):
            result[k] = _resolve(v, root, depth + 1)
        elif isinstance(v, list):
            result[k] = [
                _resolve(item, root, depth + 1) if isinstance(item, dict) else item
                for item in v
            ]
        else:
            result[k] = v
    return result


def _camel_to_label(name: str) -> str:
    """Convert camelCase field name to 'Title Case' label."""
    s = re.sub(r"([A-Z])", r" \1", name)
    return s.strip().title()


def _walk_properties(
    props: dict[str, Any],
    required_keys: list[str],
    root: dict[str, Any],
    prefix: str,
    out: list[FieldDescriptor],
    depth: int = 0,
) -> None:
    """Recursively walk resolved properties and emit FieldDescriptors."""
    if depth > 5:
        return
    for key, raw_val in props.items():
        if key == "model":
            continue   # skip the discriminator field
        val = _resolve(raw_val, root, 0) if "$ref" in raw_val else raw_val
        path = f"{prefix}.{key}" if prefix else key
        typ = val.get("type", "string")
        desc = val.get("description", "")
        is_required = key in required_keys

        # Collect enum/const values
        enums: list[str] = []
        if "enum" in val:
            enums = [str(e) for e in val["enum"]]
        elif "const" in val:
            enums = [str(val["const"])]
        # Handle oneOf with const entries (e.g. couponFrequency type discriminator)
        if "oneOf" in val:
            for choice in val["oneOf"]:
                if isinstance(choice, dict) and "const" in choice:
                    enums.append(str(choice["const"]))

        if typ == "object" and "properties" in val:
            _walk_properties(
                val["properties"],
                val.get("required", []),
                root,
                path,
                out,
                depth + 1,
            )
        elif typ == "object" and "patternProperties" in val:
            # e.g. figi — treat as opaque string map
            out.append(FieldDescriptor(
                path=path, label=_camel_to_label(key), data_type="object",
                description=desc, required=is_required, enum_values=enums,
            ))
        else:
            out.append(FieldDescriptor(
                path=path, label=_camel_to_label(key), data_type=typ,
                description=desc, required=is_required, enum_values=enums,
            ))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_models() -> list[str]:
    """Return all model names defined in the schema's oneOf array."""
    schema = _load_raw_schema()
    models = []
    for entry in schema.get("oneOf", []):
        model_const = (
            entry
            .get("properties", {})
            .get("model", {})
            .get("const")
        )
        if model_const:
            models.append(model_const)
    return models


def get_model_schema(model_name: str) -> dict[str, Any] | None:
    """Return the fully resolved JSON Schema for the given model, or None."""
    schema = _load_raw_schema()
    for entry in schema.get("oneOf", []):
        const = (
            entry
            .get("properties", {})
            .get("model", {})
            .get("const")
        )
        if const == model_name:
            return _resolve(entry, schema, 0)
    return None


def get_schema_version() -> str:
    """Return a version string derived from the schema $id."""
    schema = _load_raw_schema()
    sid = schema.get("$id", "unknown")
    # e.g. "https://www.l-p-a.com/prism.v1.schema.json" → "v1"
    match = re.search(r"\.(v\d+)\.", sid)
    return match.group(1) if match else "unknown"


def get_field_descriptors(model_name: str) -> list[FieldDescriptor]:
    """
    Return a flat list of extractable fields for the given model.
    Used to build the extraction prompt and to initialise field_results rows.
    """
    schema = _load_raw_schema()
    model_schema = get_model_schema(model_name)
    if model_schema is None:
        return []

    props = model_schema.get("properties", {})
    required_top = model_schema.get("required", [])
    out: list[FieldDescriptor] = []
    _walk_properties(props, required_top, schema, "", out, depth=0)
    return out


def load_cusip_mapping() -> dict[str, CusipMapping]:
    """
    Read CUSIP_PRISM_Mapping.xlsx and return a dict keyed by CUSIP.
    Returns empty dict if the file is missing or unreadable.
    """
    global _CUSIP_CACHE
    if _CUSIP_CACHE is not None:
        return _CUSIP_CACHE

    result: dict[str, CusipMapping] = {}
    path = config.CUSIP_MAPPING_FILE
    if not path.exists():
        _CUSIP_CACHE = result
        return result

    try:
        wb = openpyxl.load_workbook(str(path), read_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            _CUSIP_CACHE = result
            return result

        # Find column indices from header row
        header = [str(c).strip().lower() if c else "" for c in rows[0]]
        try:
            i_cusip  = header.index("cusip")
            i_model  = header.index("spectrum")
        except ValueError:
            _CUSIP_CACHE = result
            return result

        i_source = header.index("source") if "source" in header else -1

        for row in rows[1:]:
            if not row or row[i_cusip] is None:
                continue
            cusip = str(row[i_cusip]).strip()
            model = str(row[i_model]).strip() if row[i_model] else ""
            source = str(row[i_source]).strip() if i_source >= 0 and row[i_source] else ""
            if cusip and model:
                result[cusip] = CusipMapping(cusip=cusip, payout_type_id=model, source_url=source)
    except Exception as exc:
        log.warning("Failed to read CUSIP mapping from %s: %s", path, exc)

    _CUSIP_CACHE = result
    return result
