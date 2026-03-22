"""
schema_diff.py — PRISM schema diff engine.

Compares two PRISM JSON Schema files at the FieldDescriptor level and
produces a structured SchemaDiff report covering:

  • New / removed / changed $defs
  • New / removed models
  • Per-model: added / removed / type-changed / enum-changed / required-changed fields
  • Dynamic (patternProperties) fields flagged separately
  • Severity classification per change: breaking / caution / safe
  • Cross-reference against FIELD_PARSERS, label maps, issuer YAMLs, and DB rows

Severity rules
--------------
  breaking : field removed, type changed, enum value removed,
             new field that is required (breaks existing extractions),
             existing field gains required=True
  caution  : existing required field becomes optional,
             description changed on a required field,
             $def removed (may be referenced elsewhere)
  safe     : new optional field, enum value added,
             description changed on optional field,
             new model, new $def
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Any

import yaml

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# $ref resolver (standalone — does not depend on schema_loader cache)
# ---------------------------------------------------------------------------

def _resolve(node: Any, root: dict, depth: int = 0) -> Any:
    if depth > 12 or not isinstance(node, dict):
        return node
    if "$ref" in node:
        ref = node["$ref"]
        if ref.startswith("#/$defs/"):
            key = ref[len("#/$defs/"):]
            defn = root.get("$defs", {}).get(key, {})
            resolved = _resolve(copy.deepcopy(defn), root, depth + 1)
            # merge sibling keys alongside $ref
            merged = {k: v for k, v in node.items() if k != "$ref"}
            merged.update(resolved)
            return merged
        return node
    return {k: _resolve(v, root, depth + 1) for k, v in node.items()}


# ---------------------------------------------------------------------------
# Field path extractor
# ---------------------------------------------------------------------------

def _extract_enums(val: dict) -> list[str]:
    enums: list[str] = []
    if "enum" in val:
        enums = [str(e) for e in val["enum"]]
    elif "const" in val:
        enums = [str(val["const"])]
    if "oneOf" in val:
        for opt in val["oneOf"]:
            if isinstance(opt, dict):
                if "const" in opt:
                    enums.append(str(opt["const"]))
                elif "properties" in opt:
                    t = opt["properties"].get("$type", {})
                    if "const" in t:
                        enums.append(str(t["const"]))
    return enums


def _walk(node: dict, root: dict, prefix: str = "",
          parent_required: set | None = None) -> dict[str, dict]:
    """
    Walk a schema node and return {path: field_info} for every leaf field.

    field_info keys: type, description, required, enum_values, is_dynamic
    """
    results: dict[str, dict] = {}
    if parent_required is None:
        parent_required = set()

    node = _resolve(node, root)
    props: dict = node.get("properties", {})
    required_here: set = set(node.get("required", []))

    for key, raw_val in props.items():
        if key == "model":
            continue
        path = f"{prefix}.{key}" if prefix else key
        val = _resolve(raw_val, root)
        dtype = val.get("type", "")
        desc = val.get("description", raw_val.get("description", ""))
        is_required = key in required_here

        if "patternProperties" in val and not val.get("properties"):
            # Dynamic-key object (e.g. Portfolios) — flag but don't recurse
            results[path] = {
                "type": "object(dynamic)",
                "description": desc,
                "required": is_required,
                "enum_values": [],
                "is_dynamic": True,
            }
        elif dtype == "object" or "properties" in val:
            results.update(_walk(val, root, path, required_here))
        elif dtype == "array":
            items = _resolve(val.get("items", {}), root)
            if "properties" in items:
                results.update(_walk(items, root, path + "[*]", set()))
            else:
                results[path] = {
                    "type": "array",
                    "description": desc,
                    "required": is_required,
                    "enum_values": _extract_enums(items),
                    "is_dynamic": False,
                }
        else:
            results[path] = {
                "type": dtype or "any",
                "description": desc,
                "required": is_required,
                "enum_values": _extract_enums(val),
                "is_dynamic": False,
            }

    return results


def _model_fields(schema: dict) -> dict[str, dict[str, dict]]:
    """Return {model_name: {field_path: field_info}} for every model."""
    out: dict[str, dict] = {}
    for model_def in schema.get("oneOf", []):
        name = model_def.get("properties", {}).get("model", {}).get("const")
        if name:
            out[name] = _walk(model_def, schema)
    return out


# ---------------------------------------------------------------------------
# Rename detection heuristic
# ---------------------------------------------------------------------------

def _word_overlap(a: str, b: str) -> float:
    """0–1 similarity based on shared words (lowercased)."""
    wa = set(re.findall(r"\w+", a.lower()))
    wb = set(re.findall(r"\w+", b.lower()))
    if not wa and not wb:
        return 1.0
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def _detect_renames(
    removed: dict[str, dict],
    added: dict[str, dict],
) -> list[dict]:
    """
    Return likely rename suggestions: 1-to-1 removed→added pairs
    within the same model where type matches and descriptions are similar.
    Only suggests when confidence ≥ 0.5.
    """
    suggestions = []
    used_added: set[str] = set()
    for old_path, old_info in removed.items():
        candidates = []
        for new_path, new_info in added.items():
            if new_path in used_added:
                continue
            if old_info["type"] != new_info["type"]:
                continue
            desc_sim = _word_overlap(old_info["description"], new_info["description"])
            # Boost if path suffix (last segment) is similar
            old_seg = old_path.rsplit(".", 1)[-1]
            new_seg = new_path.rsplit(".", 1)[-1]
            seg_sim = _word_overlap(old_seg, new_seg)
            confidence = round(0.5 * desc_sim + 0.5 * seg_sim, 2)
            if confidence >= 0.5:
                candidates.append((confidence, new_path, new_info))
        if candidates:
            candidates.sort(reverse=True, key=lambda x: x[0])
            best_conf, best_path, best_info = candidates[0]
            suggestions.append({
                "old_path": old_path,
                "new_path": best_path,
                "confidence": best_conf,
                "type": old_info["type"],
                "old_description": old_info["description"][:120],
                "new_description": best_info["description"][:120],
            })
            used_added.add(best_path)
    return suggestions


# ---------------------------------------------------------------------------
# Severity classifier
# ---------------------------------------------------------------------------

def _severity(change: str, field_info: dict | None = None) -> str:
    if change == "removed":
        return "breaking"
    if change == "type_changed":
        return "breaking"
    if change == "enum_removed":
        return "breaking"
    if change == "required_added":
        return "breaking"
    if change == "added":
        if field_info and field_info.get("required"):
            return "breaking"
        return "safe"
    if change == "required_removed":
        return "caution"
    if change == "enum_added":
        return "safe"
    if change == "desc_changed":
        # caution if the field is required, safe otherwise
        if field_info and field_info.get("required"):
            return "caution"
        return "safe"
    return "safe"


# ---------------------------------------------------------------------------
# Cross-reference helpers
# ---------------------------------------------------------------------------

def _load_parsers() -> set[str]:
    try:
        from extract.field_parsers import FIELD_PARSERS
        return set(FIELD_PARSERS.keys())
    except Exception:
        return set()


def _load_label_map_paths() -> dict[str, list[str]]:
    """Return {field_path: [label_strings]} from cross-issuer + user label maps."""
    path_to_labels: dict[str, list[str]] = {}

    def _load_yaml(yaml_path: Path) -> None:
        if not yaml_path.exists():
            return
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            for label, fp in data.get("labels", {}).items():
                if isinstance(fp, str):
                    path_to_labels.setdefault(fp, []).append(label)
        except Exception:
            pass

    _load_yaml(config.PROJECT_ROOT / "files" / "label_map_cross_issuer.yaml")
    _load_yaml(config.PROJECT_ROOT / "files" / "label_map_user.yaml")
    return path_to_labels


def _load_issuer_yaml_paths() -> dict[str, list[str]]:
    """Return {field_path: [issuer_slugs]} from all issuer_*.yaml table_labels."""
    path_to_issuers: dict[str, list[str]] = {}
    for yaml_path in sorted((config.PROJECT_ROOT / "files").glob("issuer_*.yaml")):
        try:
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            slug = yaml_path.stem  # e.g. "issuer_barclays"
            for _label, fp in data.get("table_labels", {}).items():
                if isinstance(fp, str):
                    path_to_issuers.setdefault(fp, []).append(slug)
        except Exception:
            pass
    return path_to_issuers


def _db_field_counts() -> dict[str, int]:
    """Return {field_name: row_count} from field_results table."""
    try:
        con = sqlite3.connect(str(config.DB_PATH))
        cur = con.execute(
            "SELECT field_name, COUNT(*) FROM field_results "
            "WHERE not_found=0 GROUP BY field_name"
        )
        result = {row[0]: row[1] for row in cur.fetchall()}
        con.close()
        return result
    except Exception:
        return {}


def _db_active_models() -> dict[str, int]:
    """Return {payout_type_id: count} for classified filings."""
    try:
        con = sqlite3.connect(str(config.DB_PATH))
        cur = con.execute(
            "SELECT payout_type_id, COUNT(*) FROM filings "
            "WHERE payout_type_id IS NOT NULL AND payout_type_id != 'unknown' "
            "GROUP BY payout_type_id"
        )
        result = {row[0]: row[1] for row in cur.fetchall()}
        con.close()
        return result
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Main diff function
# ---------------------------------------------------------------------------

def compute_diff(
    current_path: Path,
    new_path: Path,
    fetch_id: str,
    source_url: str,
) -> dict:
    """
    Compare two PRISM schema files and return a structured diff dict.
    The result is JSON-serialisable and stored alongside the pending schema.
    """
    with current_path.open(encoding="utf-8") as f:
        current_raw = f.read()
        current = json.loads(current_raw)

    with new_path.open(encoding="utf-8") as f:
        new_raw = f.read()
        new = json.loads(new_raw)

    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    def _canonical_hash(obj: dict) -> str:
        return hashlib.sha256(
            json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()[:16]

    current_hash = _canonical_hash(current)
    new_hash = _canonical_hash(new)

    # ── $defs diff ──────────────────────────────────────────────────────────
    cur_defs = set(current.get("$defs", {}).keys())
    new_defs = set(new.get("$defs", {}).keys())

    def_changes = []
    for name in sorted(cur_defs - new_defs):
        def_changes.append({"name": name, "status": "removed", "severity": "caution"})
    for name in sorted(new_defs - cur_defs):
        def_changes.append({"name": name, "status": "added", "severity": "safe"})
    for name in sorted(cur_defs & new_defs):
        c_h = _canonical_hash(current["$defs"][name])
        n_h = _canonical_hash(new["$defs"][name])
        if c_h != n_h:
            def_changes.append({"name": name, "status": "changed", "severity": "caution"})

    # ── Model-level diff ─────────────────────────────────────────────────────
    cur_models = _model_fields(current)
    new_models = _model_fields(new)

    cur_model_names = set(cur_models.keys())
    new_model_names = set(new_models.keys())

    model_changes = []

    for name in sorted(cur_model_names - new_model_names):
        model_changes.append({
            "model": name, "status": "removed",
            "severity": "breaking", "field_changes": [],
            "rename_suggestions": [],
        })

    for name in sorted(new_model_names - cur_model_names):
        fields = new_models[name]
        model_changes.append({
            "model": name, "status": "new",
            "severity": "safe",
            "field_changes": [
                {"path": p, "change": "added", "severity": "safe",
                 "new_type": fi["type"], "new_description": fi["description"][:120],
                 "new_required": fi["required"], "new_enum_values": fi["enum_values"],
                 "is_dynamic": fi.get("is_dynamic", False),
                 "has_parser": False, "label_map_entries": [],
                 "issuer_yaml_entries": [], "db_row_count": 0}
                for p, fi in sorted(fields.items())
            ],
            "rename_suggestions": [],
        })

    # Load cross-reference data once
    parsers       = _load_parsers()
    label_map     = _load_label_map_paths()
    issuer_map    = _load_issuer_yaml_paths()
    db_counts     = _db_field_counts()
    active_models = _db_active_models()

    for name in sorted(cur_model_names & new_model_names):
        cur_f = cur_models[name]
        new_f = new_models[name]

        added_paths   = {p: new_f[p] for p in new_f if p not in cur_f}
        removed_paths = {p: cur_f[p] for p in cur_f if p not in new_f}
        field_changes = []

        def _xref(path: str) -> dict:
            return {
                "has_parser":          path in parsers,
                "label_map_entries":   label_map.get(path, []),
                "issuer_yaml_entries": issuer_map.get(path, []),
                "db_row_count":        db_counts.get(path, 0),
            }

        for p, fi in sorted(added_paths.items()):
            sev = _severity("added", fi)
            field_changes.append({
                "path": p, "change": "added", "severity": sev,
                "new_type": fi["type"], "new_description": fi["description"][:120],
                "new_required": fi["required"], "new_enum_values": fi["enum_values"],
                "is_dynamic": fi.get("is_dynamic", False),
                **_xref(p),
            })

        for p, fi in sorted(removed_paths.items()):
            field_changes.append({
                "path": p, "change": "removed", "severity": "breaking",
                "old_type": fi["type"], "old_description": fi["description"][:120],
                "old_required": fi["required"],
                **_xref(p),
            })

        for p in sorted(set(cur_f) & set(new_f)):
            cf, nf = cur_f[p], new_f[p]
            sub_changes = []

            if cf["type"] != nf["type"]:
                sub_changes.append({
                    "path": p, "change": "type_changed", "severity": "breaking",
                    "old_type": cf["type"], "new_type": nf["type"],
                    **_xref(p),
                })

            c_enum = sorted(cf["enum_values"])
            n_enum = sorted(nf["enum_values"])
            if c_enum != n_enum:
                added_e   = sorted(set(n_enum) - set(c_enum))
                removed_e = sorted(set(c_enum) - set(n_enum))
                if removed_e:
                    sub_changes.append({
                        "path": p, "change": "enum_removed", "severity": "breaking",
                        "removed_values": removed_e, **_xref(p),
                    })
                if added_e:
                    sub_changes.append({
                        "path": p, "change": "enum_added", "severity": "safe",
                        "added_values": added_e, **_xref(p),
                    })

            if cf["required"] != nf["required"]:
                change = "required_added" if nf["required"] else "required_removed"
                sub_changes.append({
                    "path": p, "change": change,
                    "severity": _severity(change),
                    **_xref(p),
                })

            if cf["description"] != nf["description"]:
                sub_changes.append({
                    "path": p, "change": "desc_changed",
                    "severity": _severity("desc_changed", nf),
                    "old_description": cf["description"][:120],
                    "new_description": nf["description"][:120],
                    **_xref(p),
                })

            field_changes.extend(sub_changes)

        rename_suggestions = _detect_renames(removed_paths, added_paths)

        if field_changes or rename_suggestions:
            worst = "safe"
            for fc in field_changes:
                if fc["severity"] == "breaking":
                    worst = "breaking"
                    break
                if fc["severity"] == "caution":
                    worst = "caution"
            model_changes.append({
                "model": name,
                "status": "changed",
                "severity": worst,
                "field_changes": field_changes,
                "rename_suggestions": rename_suggestions,
            })

    # ── Summary ──────────────────────────────────────────────────────────────
    all_field_changes = [
        fc
        for mc in model_changes
        for fc in mc.get("field_changes", [])
    ]
    breaking = sum(1 for fc in all_field_changes if fc["severity"] == "breaking")
    caution  = sum(1 for fc in all_field_changes if fc["severity"] == "caution")
    safe     = sum(1 for fc in all_field_changes if fc["severity"] == "safe")
    # Add def-level severities
    breaking += sum(1 for dc in def_changes if dc["severity"] == "breaking")
    caution  += sum(1 for dc in def_changes if dc["severity"] == "caution")
    safe     += sum(1 for dc in def_changes if dc["severity"] == "safe")

    # Impact
    at_risk_parsers = sorted({
        fc["path"] for fc in all_field_changes
        if fc.get("has_parser") and fc["change"] in ("removed", "type_changed", "enum_removed")
    })
    at_risk_labels = sorted({
        label
        for fc in all_field_changes
        if fc["change"] in ("removed", "type_changed") and fc.get("label_map_entries")
        for label in fc["label_map_entries"]
    })
    at_risk_issuers = sorted({
        issuer
        for fc in all_field_changes
        if fc["change"] in ("removed", "type_changed") and fc.get("issuer_yaml_entries")
        for issuer in fc["issuer_yaml_entries"]
    })
    db_affected = sum(
        fc.get("db_row_count", 0) for fc in all_field_changes
        if fc["change"] in ("removed", "type_changed")
    )
    affected_active_models = sorted({
        mc["model"] for mc in model_changes
        if mc["status"] in ("changed", "removed") and mc["model"] in active_models
    })

    return {
        "fetch_id":            fetch_id,
        "source_url":          source_url,
        "active_schema_id":    current.get("$id", ""),
        "new_schema_id":       new.get("$id", ""),
        "active_content_hash": current_hash,
        "new_content_hash":    new_hash,
        "same_content":        current_hash == new_hash,
        "summary": {
            "breaking":       breaking,
            "caution":        caution,
            "safe":           safe,
            "models_added":   sum(1 for mc in model_changes if mc["status"] == "new"),
            "models_removed": sum(1 for mc in model_changes if mc["status"] == "removed"),
            "fields_added":   sum(1 for fc in all_field_changes if fc["change"] == "added"),
            "fields_removed": sum(1 for fc in all_field_changes if fc["change"] == "removed"),
            "type_changes":   sum(1 for fc in all_field_changes if fc["change"] == "type_changed"),
            "enum_changes":   sum(1 for fc in all_field_changes if fc["change"] in ("enum_added", "enum_removed")),
            "defs_added":     sum(1 for dc in def_changes if dc["status"] == "added"),
            "defs_removed":   sum(1 for dc in def_changes if dc["status"] == "removed"),
            "defs_changed":   sum(1 for dc in def_changes if dc["status"] == "changed"),
        },
        "impact": {
            "parsers_at_risk":          at_risk_parsers,
            "label_map_entries_at_risk": at_risk_labels,
            "issuer_yaml_at_risk":       at_risk_issuers,
            "db_rows_affected":          db_affected,
            "active_models_affected":    affected_active_models,
            "active_model_filing_counts": {
                m: active_models.get(m, 0) for m in affected_active_models
            },
        },
        "def_changes":    def_changes,
        "model_changes":  model_changes,
    }
