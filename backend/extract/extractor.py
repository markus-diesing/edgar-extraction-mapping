"""
PRISM field extractor.

For a classified filing, sends the filing text and the model's JSON Schema
to Claude, which returns a populated PRISM JSON object.

The output is then:
  1. Flattened into (field_path → value) pairs stored in field_results
  2. An ExtractionResult summary row is written

Design notes:
  - The prompt includes the full resolved schema for the classified model
    so Claude can understand nested structure and enum constraints.
  - We ask Claude to produce the PRISM JSON directly (not a flat dict),
    giving it the model examples from the wiki as structural reference.
  - Each field gets a confidence_score derived from Claude's self-reported
    confidence array in a second JSON key.
  - Every field defined in the schema produces a result — either a value
    or explicit null with not_found=1.
  - When issuer_extraction_hints.json is present, per-issuer field synonyms
    and cross-issuer field-level rules are prepended to the extraction prompt
    to improve fill rate (see files/issuer_extraction_hints.json).
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import anthropic

import config
import database
import hints_loader

# ---------------------------------------------------------------------------
# Module-level Anthropic client — instantiated once so the constructor cost
# (env-var reads, connection wiring) is not repeated on every extraction call.
# The client is thread-safe and can be shared across concurrent requests.
# ---------------------------------------------------------------------------
_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    """Return the shared Anthropic client, creating it on first use."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client
import schema_loader
import settings_store
from ingest.edgar_client import strip_html
from extract.section_router import SectionSpec, get_sections_for_model
from extract.html_extractor import extract_registry_fields, extract_from_html
from extract.label_mapper import build_label_map
import sections.section_loader  # noqa — ensure sections package is importable

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label miss-log persistence
# ---------------------------------------------------------------------------

def _clamp_conf(raw: Any, path: str = "", default: float = 0.5) -> float:
    """Parse *raw* as a float confidence and clamp to [0.0, 1.0].

    *raw* may be a float, int, or numeric string as Claude returns.
    Non-numeric values (e.g. ``"high"``, ``"0.85 (estimated)"``) fall back
    to *default* and emit a warning when *path* is provided.
    """
    try:
        return max(0.0, min(1.0, float(raw)))
    except (ValueError, TypeError):
        if path:
            log.warning(
                "Non-numeric confidence value for %s: %r — defaulting to %.1f",
                path, raw, default,
            )
        return default


def _persist_label_misses(
    misses: list,
    filing_id: str,
    issuer_name: str | None,
) -> None:
    """
    Upsert LabelMissLog rows for labels that html_extractor could not resolve.
    Existing rows are incremented (occurrence_count + 1, last_seen_at updated).
    Already-dismissed rows are not resurrected by new occurrences.
    """
    if not misses:
        return
    now = datetime.now(timezone.utc).isoformat()
    try:
        with database.get_session() as session:
            for miss in misses:
                existing = (
                    session.query(database.LabelMissLog)
                    .filter_by(label_norm=miss.label_norm)
                    .first()
                )
                if existing:
                    existing.occurrence_count = (existing.occurrence_count or 0) + 1
                    existing.last_seen_at = now
                    existing.issuer_name  = issuer_name
                    existing.filing_id    = filing_id
                    if miss.sample_value and not existing.sample_value:
                        existing.sample_value = miss.sample_value
                else:
                    session.add(database.LabelMissLog(
                        id=str(uuid.uuid4()),
                        label_norm=miss.label_norm,
                        label_raw=miss.label_raw,
                        sample_value=miss.sample_value,
                        issuer_name=issuer_name,
                        filing_id=filing_id,
                        occurrence_count=1,
                        first_seen_at=now,
                        last_seen_at=now,
                        dismissed=0,
                    ))
            session.commit()
        log.debug("Persisted %d label miss(es) to label_miss_log", len(misses))
    except Exception as exc:
        # Miss logging is non-critical — never let it break extraction.
        # Log at warning with count so repeated failures are visible in the log viewer.
        log.warning(
            "Could not persist %d label miss(es) — they will not appear in the Label Map editor: %s",
            len(misses), exc, exc_info=True,
        )


# ---------------------------------------------------------------------------
# Extraction hints — loaded on-demand from YAML files via hints_loader
# ---------------------------------------------------------------------------

def _get_extraction_hints() -> dict:
    """Return the current hints dict, reloading from YAML files if changed."""
    return hints_loader.get_hints()


def _match_issuer_hints(issuer_name: str | None, all_hints: dict | None = None) -> dict | None:
    """Return the hints block for the best-matching issuer, or None.

    Pass all_hints to avoid a redundant hints_loader call when the caller already
    holds the hints dict (e.g. extract_filing calls _get_extraction_hints once).
    """
    extraction_hints = all_hints if all_hints is not None else _get_extraction_hints()
    if not issuer_name or not extraction_hints:
        return None
    issuers = extraction_hints.get("issuers", {})
    issuer_name_lower = issuer_name.lower()
    for issuer_key, hints in issuers.items():
        patterns = hints.get("aliases", {}).get("name_match_patterns", [])
        if any(p.lower() in issuer_name_lower or issuer_name_lower in p.lower()
               for p in patterns):
            log.debug("Matched issuer hints: %r → %r", issuer_name, issuer_key)
            return hints
    return None


def _build_hints_block(issuer_hints: dict | None, all_hints: dict | None = None) -> str:
    """
    Render a concise prompt prefix from issuer-specific, cross-issuer, and schema-guide hints.

    Structure of the returned string:
      1. PRISM schema structural guide (discriminated unions, output format rules)
      2. Cross-issuer field-level rules (synonyms, value formats, cautions)
      3. Issuer-specific hints (section headings, field aliases, document layout)

    Pass all_hints to avoid a redundant hints_loader call when the caller already holds
    the dict (extract_filing loads once and passes to both _match_issuer_hints and here).
    Returns an empty string when no hints are available.
    """
    lines: list[str] = []
    if all_hints is None:
        all_hints = _get_extraction_hints()

    # --- PRISM schema guide (structural patterns — always applied when present) ---
    schema_guide = all_hints.get("schema_guide", {})
    if schema_guide:
        lines.append("## PRISM schema output rules")
        du = schema_guide.get("discriminated_union_pattern", {})
        if du:
            rule = du.get("output_rule", "")
            if rule:
                lines.append(f"Discriminated unions: {rule.strip()}")
        freq = schema_guide.get("Frequency", {})
        if freq:
            lines.append(
                "Frequency $type values: "
                + ", ".join(f"{k} → {{\"$type\": \"{k}\"}}"
                            for k in (freq.get("valid_variants") or {}).keys())
            )
        lines.append("")

    # --- Cross-issuer field-level hints (always applied when hints file exists) ---
    field_level = all_hints.get("field_level_hints", {})
    if field_level:
        lines.append("## Cross-issuer field extraction rules")
        for field_path, hint in field_level.items():
            if field_path == "_description":
                continue
            synonyms = hint.get("common_synonyms", [])
            description = hint.get("description", "")
            value_format = hint.get("value_format", "")
            caution = hint.get("caution", "")
            issuer_specific = hint.get("issuer_specific", {})

            parts = []
            if description:
                parts.append(description)
            if synonyms:
                parts.append(f"Synonyms: {', '.join(synonyms)}")
            if value_format:
                parts.append(f"Format: {value_format}")
            if caution:
                parts.append(f"⚠ {caution}")
            if issuer_specific:
                for iss, note in issuer_specific.items():
                    parts.append(f"[{iss}] {note}")

            if parts:
                lines.append(f"- **{field_path}**: {' | '.join(parts)}")
        lines.append("")

    # --- Issuer-specific hints (applied when issuer matched) ---
    if issuer_hints:
        section_headings = issuer_hints.get("section_headings", [])
        key_terms_pos = issuer_hints.get("key_terms_position", "")
        doc_structure = issuer_hints.get("document_structure", "")
        general_notes = issuer_hints.get("general_notes", "")
        field_hints = issuer_hints.get("field_hints", {})

        lines.append("## Issuer-specific extraction guidance")
        if key_terms_pos:
            lines.append(f"Key terms location: {key_terms_pos}")
        if doc_structure:
            lines.append(f"Document structure: {doc_structure}")
        if section_headings:
            lines.append(f"Key section headings to look for: {', '.join(section_headings[:6])}")
        if general_notes:
            # Limit to avoid prompt bloat; increase if notes contain critical disambiguation
            lines.append(f"Notes: {general_notes[:800]}")

        if field_hints:
            lines.append("Field-specific aliases for this issuer:")
            for field_path, hint in field_hints.items():
                synonyms = hint.get("synonyms", [])
                label = hint.get("label_in_doc", "")
                fmt = hint.get("format", "")
                loc = hint.get("typical_location", "")
                parts = []
                if synonyms:
                    parts.append(f"synonyms: {', '.join(synonyms)}")
                if label:
                    parts.append(f"label: '{label}'")
                if fmt:
                    parts.append(f"format: {fmt[:150]}")
                if loc:
                    parts.append(f"location: {loc[:100]}")
                if parts:
                    lines.append(f"  - {field_path}: {' | '.join(parts)}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ExtractionField:
    field_name: str          # dot-path
    extracted_value: Any     # Python value or None
    confidence_score: float
    source_excerpt: str
    not_found: bool
    validation_error: str | None = None  # set when value violates schema enum constraint
    source: str = "llm"      # "llm" | "html_table" | "registry" | "html_title"


@dataclass
class ExtractionResultData:
    extraction_id: str
    prism_model_id: str
    prism_model_version: str
    fields: list[ExtractionField]


# ---------------------------------------------------------------------------
# Prompt — base system prompt + live-reloadable financial glossary
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BASE = """\
You are a financial data extraction specialist.
You extract structured-product terms from SEC 424B2 prospectus filings and populate
a PRISM JSON object exactly matching the provided schema.

Rules:
- Use null for any field you cannot find in the filing.
- For dates use ISO format YYYY-MM-DD.
- For percentages expressed as "70%" output 0.70 (decimal, not percent).
- For party fields provide the LEI if available; otherwise the full legal name.
- Underlyings: use key "U1", "U2", … for multiple underlyings.
- Populate "_confidence" with a score 0.0–1.0 per dot-path field.
- Populate "_excerpts" with the source text fragment (max 200 chars) for every
  non-null field. If inferred from context, provide the supporting clause.
"""

_GLOSSARY_PATH = config.PROJECT_ROOT / "docs" / "research" / "financial_glossary.md"
_glossary_cache: dict = {"mtime": None, "text": ""}
# Guards _glossary_cache against concurrent mtime-check + write races when multiple
# extraction requests arrive simultaneously (FastAPI runs handlers in a thread pool).
_glossary_lock = threading.Lock()


def _get_system_prompt() -> str:
    """
    Return the extraction system prompt, appending the financial glossary if the file
    exists. The glossary is mtime-cached — edits to financial_glossary.md take effect
    on the next extraction call without a server restart.  Thread-safe via _glossary_lock.
    """
    global _glossary_cache
    if _GLOSSARY_PATH.exists():
        try:
            mtime = _GLOSSARY_PATH.stat().st_mtime
            with _glossary_lock:
                if mtime != _glossary_cache["mtime"]:
                    _glossary_cache["text"]  = _GLOSSARY_PATH.read_text(encoding="utf-8")
                    _glossary_cache["mtime"] = mtime
                    log.info("Financial glossary loaded/reloaded from %s", _GLOSSARY_PATH.name)
        except Exception as exc:
            log.warning("Could not load financial glossary: %s", exc)

    glossary = _glossary_cache.get("text", "")
    if glossary.strip():
        return _SYSTEM_PROMPT_BASE + "\n\n" + glossary
    return _SYSTEM_PROMPT_BASE


def _build_extraction_tool(model_name: str, model_schema: dict) -> dict:
    """
    Build an Anthropic tool definition that forces Claude to return structured
    PRISM data as a tool call rather than raw text.  This eliminates the risk
    of malformed JSON and removes the need for regex post-processing.

    The tool input schema wraps the PRISM model schema (resolved, no $refs)
    inside a top-level object with three keys: prism_data, _confidence, _excerpts.
    """
    # Strip JSON Schema meta-keys that Anthropic's tool schema doesn't accept
    safe_schema = {k: v for k, v in model_schema.items()
                   if k not in ("$schema", "$id", "$defs", "definitions")}

    return {
        "name": "submit_prism_extraction",
        "description": (
            f"Submit the fully extracted PRISM fields for model '{model_name}'. "
            "Call this tool exactly once with all extracted fields populated."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "prism_data": {
                    "description": f"Populated PRISM object for model '{model_name}'.",
                    **safe_schema,
                },
                "_confidence": {
                    "type": "object",
                    "description": (
                        "Map of dot-path field → confidence score 0.0–1.0. "
                        "1.0 = verbatim quoted, 0.7 = inferred from context, 0.4 = estimated."
                    ),
                    "additionalProperties": {"type": "number"},
                },
                "_excerpts": {
                    "type": "object",
                    "description": (
                        "Map of dot-path field → source text fragment (max 200 chars). "
                        "Required for every non-null field."
                    ),
                    "additionalProperties": {"type": "string"},
                },
            },
            "required": ["prism_data"],
        },
    }


def _trim_to_key_terms_section(
    filing_text: str,
    issuer_hints: dict | None,
    window: int = config.MAX_FILING_CHARS,
) -> tuple[str, bool]:
    """
    Trim filing text to a focused window anchored on the Key Terms section.

    Strategy (in order):
    1. Use the issuer's `section_headings` from the YAML hints as anchors.
       Take the earliest match and return `window` chars starting 200 chars
       before that position (to capture any lead-in header row).
    2. If no issuer-specific heading matches, try cross-issuer fallback anchors.
    3. If no anchor is found at all, fall back to the first `window` chars
       (original behaviour — no change vs. prior implementation).

    Returns (trimmed_text, was_trimmed).
    The was_trimmed flag is used only for logging.
    """
    FALLBACK_ANCHORS = [
        "KEY TERMS", "Key Terms", "SUPPLEMENTAL TERMS",
        "TERMS OF THE NOTES", "PRODUCT TERMS", "OFFERING TERMS",
    ]

    issuer_headings: list[str] = []
    if issuer_hints:
        issuer_headings = issuer_hints.get("section_headings", [])

    # Issuer-specific headings first, then fallbacks — deduplicated, order preserved
    all_anchors = list(dict.fromkeys(issuer_headings + FALLBACK_ANCHORS))

    best_pos = -1
    for anchor in all_anchors:
        idx = filing_text.find(anchor)
        if idx >= 0 and (best_pos < 0 or idx < best_pos):
            best_pos = idx

    if best_pos < 0:
        return filing_text[:window], False

    start = max(0, best_pos - 200)
    end   = min(len(filing_text), start + window)
    return filing_text[start:end], True


def _build_extraction_parts(
    model_name: str,
    schema_json: str,
    filing_text: str,
    hints_block: str = "",
) -> tuple[str, str]:
    """
    Split the extraction prompt into a cacheable preamble and an uncacheable filing suffix.

    The preamble (instructions + schema + hints) is identical for all filings of the same
    issuer and PRISM model — it is sent with cache_control so Claude can reuse the KV cache
    across a batch run, reducing input token cost by ~90% on cache hits.

    The filing suffix (unique per filing) is never cached.

    Returns:
        preamble    — static instructions, schema JSON, and hints block
        filing_part — "FILING TEXT:\\n{truncated_text}"
    """
    hints_section = f"\n{hints_block}\n---\n" if hints_block.strip() else "\n---\n"
    preamble = (
        f"Extract all fields from the 424B2 filing text below into a PRISM JSON object.\n"
        f"Model to populate: **{model_name}**\n\n"
        f"PRISM schema for this model:\n```json\n{schema_json}\n```\n\n"
        f"Output format — a single JSON object with three top-level keys:\n"
        f"1. The PRISM data itself (matching the schema above, including a \"model\" field set to \"{model_name}\")\n"
        f"2. \"_confidence\": {{ \"<dot.path.field>\": <0.0–1.0>, ... }}\n"
        f"3. \"_excerpts\":   {{ \"<dot.path.field>\": \"<source text fragment>\", ... }}\n"
        f"{hints_section}"
    )
    filing_part = f"FILING TEXT:\n{filing_text[:config.MAX_FILING_CHARS]}"
    return preamble, filing_part


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------

def extract_filing(filing_id: str) -> ExtractionResultData:
    """
    Extract PRISM fields from a classified filing.
    Persists ExtractionResult + FieldResult rows and updates the filing status.
    """
    if settings_store.get_settings().get("sectioned_extraction", config.SECTIONED_EXTRACTION):
        return extract_filing_sectioned(filing_id)

    # Load filing
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise ValueError(f"Filing not found: {filing_id}")
        if not filing.payout_type_id or filing.payout_type_id == "unknown":
            raise ValueError("Filing must be classified before extraction")
        model_name    = filing.payout_type_id
        raw_html_path = filing.raw_html_path
        issuer_name   = filing.issuer_name  # may be None for older rows

    # Load + resolve schema for this model
    model_schema = schema_loader.get_model_schema(model_name)
    if not model_schema:
        raise ValueError(f"Model '{model_name}' not found in PRISM schema")

    schema_version = schema_loader.get_schema_version()

    # Get field descriptors (for ensuring full coverage)
    descriptors = schema_loader.get_field_descriptors(model_name)
    descriptor_paths = {d.path for d in descriptors}

    # Prepare schema JSON for prompt (strip $ref artifacts, keep readable)
    schema_for_prompt = json.dumps(model_schema, indent=2)

    # Load filing HTML
    abs_path = config.PROJECT_ROOT / raw_html_path
    html = abs_path.read_text(encoding="utf-8", errors="replace")

    # Build issuer hints block (empty string if no match / hints unavailable).
    # Load hints once and pass to both helpers to avoid a redundant mtime-stat/reload.
    all_hints    = _get_extraction_hints()
    issuer_hints = _match_issuer_hints(issuer_name, all_hints=all_hints)
    hints_block  = _build_hints_block(issuer_hints, all_hints=all_hints)
    if hints_block.strip():
        log.info("Applying extraction hints for issuer %r", issuer_name)
    else:
        log.info("No issuer-specific hints matched for issuer %r — using base prompt", issuer_name)

    # ── Tier 0: Registry metadata extraction ────────────────────────────────
    with database.get_session() as session:
        filing_row = session.get(database.Filing, filing_id)
        filing_record = {
            "cusip":       filing_row.cusip       if filing_row else None,
            "issuer_name": filing_row.issuer_name if filing_row else None,
        }
    tier0_fields = extract_registry_fields(filing_record)
    if tier0_fields:
        log.info("Tier 0: %d registry fields extracted", len(tier0_fields))

    # ── Tier 1: HTML table extraction ────────────────────────────────────────
    issuer_table_labels = issuer_hints.get("table_labels", {}) if issuer_hints else {}
    label_map = build_label_map(issuer_table_labels=issuer_table_labels)
    tier1_fields, tier1_misses = extract_from_html(html, issuer_hints, label_map)
    if tier1_fields:
        log.info("Tier 1: %d fields extracted from HTML table", len(tier1_fields))
    if tier1_misses:
        _persist_label_misses(tier1_misses, filing_id=filing_id, issuer_name=issuer_name)

    # Strip HTML to plain text for LLM prompt
    filing_text = strip_html(html)

    # Section pre-filter: trim to the Key Terms window before sending to Claude.
    # Uses issuer section_headings from YAML hints as anchors; falls back to
    # cross-issuer anchors ("KEY TERMS", etc.); falls back to first MAX_FILING_CHARS.
    filing_text, was_trimmed = _trim_to_key_terms_section(filing_text, issuer_hints)
    log.info(
        "Filing text: %d chars %s",
        len(filing_text),
        "(trimmed to key-terms section)" if was_trimmed else "(no section anchor found — using head)",
    )

    # Build prompt parts and tool definition
    # preamble (schema + hints) is sent with cache_control; filing text is not cached.
    preamble, filing_part = _build_extraction_parts(model_name, schema_for_prompt, filing_text, hints_block)
    extraction_tool = _build_extraction_tool(model_name, model_schema)

    # Resolve active Claude model from runtime settings (changeable without server restart)
    active_model = settings_store.get_settings().get("claude_model", config.CLAUDE_MODEL_DEFAULT)

    client = _get_client()
    log.info("Extracting filing %s model=%s claude=%s (tool-call mode)", filing_id, model_name, active_model)

    t0 = time.monotonic()
    message = client.messages.create(
        model=active_model,
        max_tokens=8192,
        # System prompt is static per server instance — cache it
        system=[{"type": "text", "text": _get_system_prompt(), "cache_control": {"type": "ephemeral"}}],
        tools=[extraction_tool],
        tool_choice={"type": "tool", "name": "submit_prism_extraction"},
        # Two content blocks: cached preamble + uncached filing text
        messages=[{"role": "user", "content": [
            {"type": "text", "text": preamble,     "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": filing_part},
        ]}],
    )
    duration = time.monotonic() - t0

    # Log API usage including cache token counts (0 when caching not yet active)
    _log_api_usage(
        filing_id=filing_id,
        call_type="extract",
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        duration_seconds=duration,
        model=active_model,
        cache_read_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(message.usage, "cache_creation_input_tokens", 0) or 0,
    )

    # Extract from tool_use block (guaranteed valid JSON — no regex cleanup needed)
    prism_data, confidence_map, excerpts_map = _parse_tool_response(message)

    # Flatten PRISM data into field list
    flat_values: dict[str, Any] = {}
    _flatten(prism_data, "", flat_values, skip_keys={"model", "_confidence", "_excerpts"})

    # Build a quick enum-lookup from descriptors: {path: [allowed_values]}
    enum_lookup: dict[str, list[str]] = {
        d.path: d.enum_values
        for d in descriptors
        if d.enum_values
    }

    # ── Merge Tier 0 + Tier 1 results into a source-tagged override map ──────
    # Keys: field_name → HtmlField (Tier 1 wins over Tier 0 on conflict,
    # since Tier 1 parses from the document itself while Tier 0 is registry data).
    # Both tiers override the LLM result when present (higher trust).
    pre_extracted: dict[str, Any] = {}   # field_name → (value, score, excerpt, source)

    for hf in tier0_fields:
        pre_extracted[hf.field_name] = (hf.extracted_value, hf.confidence_score,
                                        hf.source_excerpt, hf.source)
    for hf in tier1_fields:
        if hf.field_name in pre_extracted:
            log.info(
                "Tier 1 overrides Tier 0 for %s: %r → %r",
                hf.field_name, pre_extracted[hf.field_name][0], hf.extracted_value,
            )
        pre_extracted[hf.field_name] = (hf.extracted_value, hf.confidence_score,
                                        hf.source_excerpt, hf.source)

    # Build ExtractionField list — ensure all descriptor paths are covered
    all_paths = descriptor_paths | set(flat_values.keys()) | set(pre_extracted.keys())
    fields: list[ExtractionField] = []
    for path in sorted(all_paths):
        if path in {"model", "_confidence", "_excerpts"}:
            continue

        # Determine source: Tier 0/1 win over LLM
        if path in pre_extracted:
            value, confidence, excerpt, src = pre_extracted[path]
            llm_value = flat_values.get(path)
            if llm_value is not None and llm_value != value:
                log.info(
                    "Conflict [Tier 1 wins]: %s — html=%r  llm=%r  (confidence=%.2f)",
                    path, value, llm_value, confidence,
                )
        else:
            value      = flat_values.get(path)
            _default   = 0.5 if value is not None else 0.0
            confidence = _clamp_conf(confidence_map.get(path, _default), path, _default)
            excerpt    = str(excerpts_map.get(path, ""))[:500]
            src        = "llm"

        not_found = value is None

        # Schema enum validation — flag values that violate the schema constraint
        validation_error: str | None = None
        if value is not None and path in enum_lookup:
            allowed = enum_lookup[path]
            str_value = str(value)
            if str_value not in allowed:
                validation_error = (
                    f"Schema violation: '{str_value}' is not a valid value. "
                    f"Allowed: {allowed}"
                )
                confidence = 0.0
                log.warning(
                    "Enum violation: field=%s  value=%r  allowed=%s",
                    path, str_value, allowed,
                )

        fields.append(ExtractionField(
            field_name=path,
            extracted_value=value,
            confidence_score=confidence,
            source_excerpt=excerpt,
            not_found=not_found,
            validation_error=validation_error,
            source=src,
        ))

    # Persist to DB
    now = datetime.now(timezone.utc).isoformat()
    extraction_id = str(uuid.uuid4())

    fields_found = sum(1 for f in fields if not f.not_found)
    fields_null  = sum(1 for f in fields if f.not_found)

    extraction_row = database.ExtractionResult(
        id=extraction_id,
        filing_id=filing_id,
        prism_model_id=model_name,
        prism_model_version=schema_version,
        extracted_at=now,
        field_count=len(fields),
        fields_found=fields_found,
        fields_null=fields_null,
        extraction_mode="single",
    )

    field_rows = [
        database.FieldResult(
            id=str(uuid.uuid4()),
            extraction_id=extraction_id,
            filing_id=filing_id,
            field_name=f.field_name,
            extracted_value=json.dumps(f.extracted_value),
            confidence_score=f.confidence_score,
            source_excerpt=f.source_excerpt,
            not_found=1 if f.not_found else 0,
            review_status="schema_error" if f.validation_error else "pending",
            validation_error=f.validation_error,
            source=f.source,
        )
        for f in fields
    ]

    with database.get_session() as session:
        session.add(extraction_row)
        for row in field_rows:
            session.add(row)
        # Update filing status
        filing_obj = session.get(database.Filing, filing_id)
        if filing_obj:
            filing_obj.status = "extracted"
        session.commit()

    log.info(
        "Extraction complete: filing=%s  model=%s  found=%d  null=%d",
        filing_id, model_name, fields_found, fields_null,
    )

    return ExtractionResultData(
        extraction_id=extraction_id,
        prism_model_id=model_name,
        prism_model_version=schema_version,
        fields=fields,
    )


# ---------------------------------------------------------------------------
# Section-by-section extraction helpers
# ---------------------------------------------------------------------------


def _slice_filing_text(full_text: str, section_spec: SectionSpec) -> str:
    """Return a slice of filing text anchored on section_spec.search_headers.
    Falls back to the beginning of the document for identifiers section,
    or returns empty string if no anchor found."""
    if section_spec.name == "identifiers":
        return full_text[: section_spec.max_chars]

    best_start = -1
    for header in section_spec.search_headers:
        match = re.search(r"(?i)\b" + re.escape(header) + r"\b", full_text)
        if match:
            pos = match.start()
            if best_start < 0 or pos < best_start:
                best_start = pos

    if best_start < 0:
        return ""

    # Extend backward a little (500 chars) to catch any lead-in text
    start = max(0, best_start - 500)
    end = min(len(full_text), start + section_spec.max_chars)
    return full_text[start:end]


def _extract_section_schema(model_schema: dict, section_spec: SectionSpec) -> dict:
    """Return a sub-schema containing only properties for section_spec.schema_keys."""
    props = model_schema.get("properties", {})
    required = model_schema.get("required", [])
    sub_props = {}
    sub_required = []
    for key in section_spec.schema_keys:
        if key in props:
            sub_props[key] = props[key]
            if key in required:
                sub_required.append(key)
    return {
        "type": "object",
        "properties": sub_props,
        **({"required": sub_required} if sub_required else {}),
        "additionalProperties": False,
    }


def _build_section_parts(
    model_name: str,
    section_spec: SectionSpec,
    section_schema_json: str,
    filing_slice: str,
    hints_block: str,
) -> tuple[str, str]:
    """
    Split a section-mode prompt into a cacheable preamble and an uncacheable filing excerpt.

    The preamble (model/section instructions + schema + hints) is stable within a batch run
    for the same model and section — it is sent with cache_control.

    Returns:
        preamble      — section instructions, schema, hints
        filing_part   — "FILING TEXT (section excerpt):\\n{slice}"
    """
    preamble_parts = [
        f"PRISM MODEL: {model_name}",
        f"SECTION: {section_spec.name}",
        f"SECTION INSTRUCTION: {section_spec.system_note.strip()}",
        "",
        "SECTION SCHEMA (extract ONLY the fields in this schema):",
        section_schema_json,
    ]
    if hints_block:
        preamble_parts += ["", hints_block]
    preamble = "\n".join(preamble_parts)

    filing_content = (
        filing_slice
        if filing_slice
        else "[No matching section found in this filing — return all fields as null]"
    )
    filing_part = f"FILING TEXT (section excerpt):\n{filing_content}"
    return preamble, filing_part


def _deep_set(d: dict, dot_path: str, value) -> dict:
    """Set a value at a dot-separated path in a nested dict, returning the mutated dict."""
    keys = dot_path.split(".")
    current = d
    for k in keys[:-1]:
        if k not in current or not isinstance(current[k], dict):
            current[k] = {}
        current = current[k]
    current[keys[-1]] = value
    return d


class SectionResult(NamedTuple):
    section_name: str
    prism_data: dict
    confidence_map: dict
    excerpts_map: dict


def _merge_section_results(
    section_results: list[SectionResult],
) -> tuple[dict, dict, dict]:
    """Merge multiple section results into a single (prism_data, confidence_map, excerpts_map)."""
    merged_prism: dict = {}
    merged_conf: dict = {}
    merged_excr: dict = {}

    for result in section_results:
        flat: dict = {}
        _flatten(result.prism_data, "", flat, skip_keys={"model", "_confidence", "_excerpts"})
        for path, value in flat.items():
            if value is None:
                continue
            existing_conf = merged_conf.get(path, -1.0)
            new_conf = float(result.confidence_map.get(path, 0.5))
            if (existing_conf < 0
                    or (new_conf - existing_conf) >= config.SECTION_MERGE_CONFIDENCE_DELTA):
                _deep_set(merged_prism, path, value)
                merged_conf[path] = new_conf
                merged_excr[path] = result.excerpts_map.get(path, "")

    return merged_prism, merged_conf, merged_excr


def extract_filing_sectioned(filing_id: str) -> ExtractionResultData:
    """
    Section-by-section extraction variant of extract_filing().
    Runs N focused Claude calls (one per section group) and merges results.
    Persists ExtractionResult + FieldResult rows and updates the filing status.
    """
    # Load filing
    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if not filing:
            raise ValueError(f"Filing not found: {filing_id}")
        if not filing.payout_type_id or filing.payout_type_id == "unknown":
            raise ValueError("Filing must be classified before extraction")
        model_name    = filing.payout_type_id
        raw_html_path = filing.raw_html_path
        issuer_name   = filing.issuer_name  # may be None for older rows

    # Load + resolve schema for this model
    model_schema = schema_loader.get_model_schema(model_name)
    if not model_schema:
        raise ValueError(f"Model '{model_name}' not found in PRISM schema")

    schema_version = schema_loader.get_schema_version()

    # Get field descriptors (for ensuring full coverage)
    descriptors = schema_loader.get_field_descriptors(model_name)
    descriptor_paths = {d.path for d in descriptors}

    # Load filing HTML and strip to text
    abs_path = config.PROJECT_ROOT / raw_html_path
    html = abs_path.read_text(encoding="utf-8", errors="replace")
    filing_text = strip_html(html)

    # Build issuer hints block
    issuer_hints = _match_issuer_hints(issuer_name)
    hints_block  = _build_hints_block(issuer_hints)
    if hints_block.strip():
        log.info("Applying extraction hints for issuer %r (sectioned mode)", issuer_name)

    # ── Tier 0: Registry metadata extraction ────────────────────────────────
    with database.get_session() as session:
        filing_row = session.get(database.Filing, filing_id)
        filing_record = {
            "cusip":       filing_row.cusip       if filing_row else None,
            "issuer_name": filing_row.issuer_name if filing_row else None,
        }
    tier0_fields = extract_registry_fields(filing_record)
    if tier0_fields:
        log.info("Tier 0: %d registry fields extracted", len(tier0_fields))

    # ── Tier 1: HTML table extraction ────────────────────────────────────────
    issuer_table_labels = issuer_hints.get("table_labels", {}) if issuer_hints else {}
    label_map = build_label_map(issuer_table_labels=issuer_table_labels)
    tier1_fields, tier1_misses = extract_from_html(html, issuer_hints, label_map)
    if tier1_fields:
        log.info("Tier 1: %d fields extracted from HTML table", len(tier1_fields))
    if tier1_misses:
        _persist_label_misses(tier1_misses, filing_id=filing_id, issuer_name=issuer_name)

    # Get sections for this model
    sections = get_sections_for_model(model_name)
    log.info(
        "Sectioned extraction: filing=%s model=%s sections=%s",
        filing_id, model_name, [s.name for s in sections],
    )

    # Resolve active Claude model once for the whole sectioned run
    active_model = settings_store.get_settings().get("claude_model", config.CLAUDE_MODEL_DEFAULT)
    system_prompt_cached = [{"type": "text", "text": _get_system_prompt(), "cache_control": {"type": "ephemeral"}}]

    client = _get_client()
    section_results: list[SectionResult] = []

    for section_spec in sections:
        # Slice filing text to the relevant portion
        filing_slice = _slice_filing_text(filing_text, section_spec)

        # Skip API call if slice is too short
        if len(filing_slice) < 100:
            log.info(
                "Section '%s' — no matching text found (slice < 100 chars), skipping API call",
                section_spec.name,
            )
            section_results.append(SectionResult(
                section_name=section_spec.name,
                prism_data={},
                confidence_map={},
                excerpts_map={},
            ))
            continue

        # Build section sub-schema
        section_schema = _extract_section_schema(model_schema, section_spec)
        section_schema_json = json.dumps(section_schema, indent=2)

        # Split into cached preamble (schema + hints) and uncached filing excerpt
        preamble, filing_part = _build_section_parts(
            model_name, section_spec, section_schema_json, filing_slice, hints_block
        )

        # Build tool definition using the section sub-schema
        extraction_tool = _build_extraction_tool(
            f"{model_name}/{section_spec.name}", section_schema
        )

        log.info(
            "Section '%s': slice=%d chars, schema_keys=%s",
            section_spec.name, len(filing_slice), section_spec.schema_keys,
        )

        t0 = time.monotonic()
        message = client.messages.create(
            model=active_model,
            max_tokens=4096,
            system=system_prompt_cached,
            tools=[extraction_tool],
            tool_choice={"type": "tool", "name": "submit_prism_extraction"},
            messages=[{"role": "user", "content": [
                {"type": "text", "text": preamble,     "cache_control": {"type": "ephemeral"}},
                {"type": "text", "text": filing_part},
            ]}],
        )
        duration = time.monotonic() - t0

        # Log API usage per section call including cache tokens
        _log_api_usage(
            filing_id=filing_id,
            call_type=f"extract_{section_spec.name}",
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            duration_seconds=duration,
            model=active_model,
            cache_read_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(message.usage, "cache_creation_input_tokens", 0) or 0,
        )

        prism_data, confidence_map, excerpts_map = _parse_tool_response(message)
        section_results.append(SectionResult(
            section_name=section_spec.name,
            prism_data=prism_data,
            confidence_map=confidence_map,
            excerpts_map=excerpts_map,
        ))
        log.info("Section '%s' complete in %.2fs", section_spec.name, duration)

    # Merge all section results
    merged_prism, merged_conf, merged_excr = _merge_section_results(section_results)

    # Build a quick enum-lookup from descriptors: {path: [allowed_values]}
    enum_lookup: dict[str, list[str]] = {
        d.path: d.enum_values
        for d in descriptors
        if d.enum_values
    }

    # Flatten merged PRISM data into field list
    flat_values: dict[str, Any] = {}
    _flatten(merged_prism, "", flat_values, skip_keys={"model", "_confidence", "_excerpts"})

    # ── Merge Tier 0 + Tier 1 into override map (same logic as extract_filing) ─
    # Tier 1 wins over Tier 0 on conflict; both win over LLM (higher trust).
    pre_extracted: dict[str, Any] = {}   # field_name → (value, score, excerpt, source)

    for hf in tier0_fields:
        pre_extracted[hf.field_name] = (hf.extracted_value, hf.confidence_score,
                                        hf.source_excerpt, hf.source)
    for hf in tier1_fields:
        if hf.field_name in pre_extracted:
            log.info(
                "Tier 1 overrides Tier 0 for %s: %r → %r",
                hf.field_name, pre_extracted[hf.field_name][0], hf.extracted_value,
            )
        pre_extracted[hf.field_name] = (hf.extracted_value, hf.confidence_score,
                                        hf.source_excerpt, hf.source)

    # Build ExtractionField list — ensure all descriptor paths are covered
    all_paths = descriptor_paths | set(flat_values.keys()) | set(pre_extracted.keys())
    fields: list[ExtractionField] = []
    for path in sorted(all_paths):
        if path in {"model", "_confidence", "_excerpts"}:
            continue

        # Determine source: Tier 0/1 win over LLM
        if path in pre_extracted:
            value, confidence, excerpt, src = pre_extracted[path]
            llm_value = flat_values.get(path)
            if llm_value is not None and llm_value != value:
                log.info(
                    "Conflict [Tier 1 wins]: %s — html=%r  llm=%r  (confidence=%.2f)",
                    path, value, llm_value, confidence,
                )
        else:
            value      = flat_values.get(path)
            _default   = 0.5 if value is not None else 0.0
            confidence = _clamp_conf(merged_conf.get(path, _default), path, _default)
            excerpt    = str(merged_excr.get(path, ""))[:500]
            src        = "llm"

        not_found = value is None

        # Schema enum validation
        validation_error: str | None = None
        if value is not None and path in enum_lookup:
            allowed = enum_lookup[path]
            str_value = str(value)
            if str_value not in allowed:
                validation_error = (
                    f"Schema violation: '{str_value}' is not a valid value. "
                    f"Allowed: {allowed}"
                )
                confidence = 0.0
                log.warning(
                    "Enum violation: field=%s  value=%r  allowed=%s",
                    path, str_value, allowed,
                )

        fields.append(ExtractionField(
            field_name=path,
            extracted_value=value,
            confidence_score=confidence,
            source_excerpt=excerpt,
            not_found=not_found,
            validation_error=validation_error,
            source=src,
        ))

    # Persist to DB
    now = datetime.now(timezone.utc).isoformat()
    extraction_id = str(uuid.uuid4())

    fields_found = sum(1 for f in fields if not f.not_found)
    fields_null  = sum(1 for f in fields if f.not_found)

    extraction_row = database.ExtractionResult(
        id=extraction_id,
        filing_id=filing_id,
        prism_model_id=model_name,
        prism_model_version=schema_version,
        extracted_at=now,
        field_count=len(fields),
        fields_found=fields_found,
        fields_null=fields_null,
        extraction_mode="sectioned",
    )

    field_rows = [
        database.FieldResult(
            id=str(uuid.uuid4()),
            extraction_id=extraction_id,
            filing_id=filing_id,
            field_name=f.field_name,
            extracted_value=json.dumps(f.extracted_value),
            confidence_score=f.confidence_score,
            source_excerpt=f.source_excerpt,
            not_found=1 if f.not_found else 0,
            review_status="schema_error" if f.validation_error else "pending",
            validation_error=f.validation_error,
            source=f.source,
        )
        for f in fields
    ]

    with database.get_session() as session:
        session.add(extraction_row)
        for row in field_rows:
            session.add(row)
        # Update filing status
        filing_obj = session.get(database.Filing, filing_id)
        if filing_obj:
            filing_obj.status = "extracted"
        session.commit()

    log.info(
        "Sectioned extraction complete: filing=%s  model=%s  sections=%d  found=%d  null=%d",
        filing_id, model_name, len(sections), fields_found, fields_null,
    )

    return ExtractionResultData(
        extraction_id=extraction_id,
        prism_model_id=model_name,
        prism_model_version=schema_version,
        fields=fields,
    )


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_tool_response(message: Any) -> tuple[dict, dict, dict]:
    """
    Extract (prism_data, confidence_map, excerpts_map) from a tool_use response.

    When Claude responds via tool_choice=forced, the response content contains
    a ToolUseBlock whose .input attribute is already a parsed Python dict —
    no JSON decoding or regex cleanup needed.
    """
    for block in message.content:
        if block.type == "tool_use" and block.name == "submit_prism_extraction":
            tool_input = block.input  # already a dict, guaranteed valid
            # Claude occasionally returns a non-dict for these maps (e.g. an empty
            # string or null) despite the tool schema specifying object types.
            # Guard here so callers never receive a non-dict and crash on .get().
            _tool_keys = [
                ("prism_data",   "prism_data"),
                ("_confidence",  "confidence_map"),
                ("_excerpts",    "excerpts_map"),
            ]
            _coerced: dict[str, dict] = {}
            for tool_key, var_name in _tool_keys:
                val = tool_input.get(tool_key, {})
                if not isinstance(val, dict):
                    log.warning(
                        "_parse_tool_response: %s was %s, defaulting to {}",
                        tool_key, type(val).__name__,
                    )
                    val = {}
                _coerced[var_name] = val
            return _coerced["prism_data"], _coerced["confidence_map"], _coerced["excerpts_map"]

    # Fallback: if no tool_use block found (should not happen with tool_choice=forced),
    # try to parse text content as raw JSON
    log.warning("No tool_use block in response — falling back to raw text parse")
    for block in message.content:
        if hasattr(block, "text"):
            return _parse_raw_json_response(block.text.strip())
    log.error("Extraction response contained neither tool_use nor text block")
    return {}, {}, {}


def _parse_raw_json_response(raw: str) -> tuple[dict, dict, dict]:
    """Fallback: parse Claude's raw text response (legacy path)."""
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse extraction response: %s\nRaw (first 500): %s", exc, raw[:500])
        return {}, {}, {}
    confidence_map = data.pop("_confidence", {})
    excerpts_map   = data.pop("_excerpts", {})
    return data, confidence_map, excerpts_map


def _flatten(obj: Any, prefix: str, out: dict[str, Any], skip_keys: set[str]) -> None:
    """Recursively flatten a nested dict into dot-path keys."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip_keys:
                continue
            new_key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)) and not _is_leaf_object(v):
                _flatten(v, new_key, out, skip_keys)
            else:
                out[new_key] = v
    elif isinstance(obj, list):
        # Lists are stored as-is (e.g. autocall payment schedules)
        out[prefix] = obj
    else:
        out[prefix] = obj


def _is_leaf_object(v: Any) -> bool:
    """
    Treat certain dicts as atomic values rather than flattening further.
    E.g. temporal payment schedules (dict of timestamp → entry) should be
    stored whole so the reviewer can see the full schedule.
    """
    if not isinstance(v, dict):
        return False
    # Heuristic: if keys look like ISO timestamps, it's a temporal schedule
    keys = list(v.keys())
    if keys and all(re.match(r"\d{4}-\d{2}-\d{2}T", k) for k in keys[:3]):
        return True
    return False


# ---------------------------------------------------------------------------
# API usage logging
# ---------------------------------------------------------------------------

def _log_api_usage(
    filing_id: str,
    call_type: str,
    input_tokens: int,
    output_tokens: int,
    duration_seconds: float | None = None,
    model: str | None = None,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> None:
    """Persist one API call record to api_usage_log."""
    entry = database.ApiUsageLog(
        id=str(uuid.uuid4()),
        filing_id=filing_id,
        call_type=call_type,
        model=model or config.CLAUDE_MODEL_DEFAULT,
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        duration_seconds=duration_seconds,
        cache_read_tokens=cache_read_tokens or None,
        cache_write_tokens=cache_write_tokens or None,
    )
    with database.get_session() as session:
        session.add(entry)
        session.commit()
