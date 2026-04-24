"""
Underlying Data Module — LLM Extractor (Tier 2).

Extracts fields from the 10-K / 20-F cover page and Item 1 text that are not
available from EDGAR structured data (Tier 1) or market data (Tier 3).

Target fields
-------------
legal_name         Exact legal name of the registrant (cover page)
share_class_name   e.g. "Common Stock, $0.00001 par value per share"
share_type         e.g. "Common Stock"
brief_description  1–2 sentence company description from Item 1
adr_flag           True if the filing describes ADR / ADS shares

LLM backend
-----------
Calls are dispatched through ``underlying.llm_client``, which supports:
  anthropic          — Anthropic Messages API
  openai-compatible  — LM Studio / any /v1/chat/completions server
  ollama             — Ollama /api/chat

The active backend is read from ``runtime_settings.yaml`` at call time via
``llm_client.load_config()``.  No server restart required to switch models.

Design decisions
----------------
* The full filing text is truncated to ``UNDERLYING_EXTRACTION_CHARS`` chars
  so the prompt stays cheap for both cloud and local models.
* Confidence < ``EXTRACTION_CONFIDENCE_THRESHOLD`` flags the field for review.
* Failures (network, JSON parse) return an empty ExtractionResult so the
  caller can still write Tier 1 data to the DB.
* ``try_repair_json`` (from llm_client) recovers truncated JSON responses
  produced by LM Studio MLX (confirmed bug as of Apr 2026).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UNDERLYING_EXTRACTION_CHARS: int = config.UNDERLYING_EXTRACTION_CHARS

_TARGET_FIELDS = [
    "legal_name",
    "share_class_name",
    "share_type",
    "brief_description",
    "adr_flag",
]

_FIELD_SOURCE_TYPES: dict[str, str] = {
    "legal_name":        "10k_cover",
    "share_class_name":  "10k_cover",
    "share_type":        "10k_cover",
    "adr_flag":          "10k_cover",
    "brief_description": "10k_item1",
}

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class FieldResult:
    """Extracted value + metadata for one field."""
    field_name:     str
    value:          Any                      # str | bool | None
    confidence:     float                    # 0.0 – 1.0
    source_excerpt: str   = ""               # relevant text snippet (best-effort)
    source_type:    str   = "10k_cover"      # "10k_cover" | "10k_item1"
    needs_review:   bool  = False            # True when confidence < threshold


@dataclass
class ExtractionResult:
    """Result of one LLM extraction call."""
    fields:        list[FieldResult] = field(default_factory=list)
    raw_response:  str  = ""                 # full model response (for debugging)
    error:         str | None = None         # set if call or JSON parse failed
    input_tokens:  int  = 0                  # prompt tokens reported by the API
    output_tokens: int  = 0                  # completion tokens reported by the API

    def get(self, field_name: str) -> FieldResult | None:
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None

    def as_dict(self) -> dict[str, Any]:
        return {f.field_name: f.value for f in self.fields}


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are an expert financial data analyst.  You extract precise, factual
information from SEC 10-K and 20-F annual report text.  You never invent
information; if a field cannot be determined from the provided text, return
null for that field and assign a confidence of 0.0.

Respond ONLY with a valid JSON object in the format shown below — no
markdown, no commentary, no surrounding text.

{
  "fields": {
    "legal_name": <string or null>,
    "share_class_name": <string or null>,
    "share_type": <string or null>,
    "brief_description": <string or null>,
    "adr_flag": <true | false | null>
  },
  "confidence": {
    "legal_name": <0.0 – 1.0>,
    "share_class_name": <0.0 – 1.0>,
    "share_type": <0.0 – 1.0>,
    "brief_description": <0.0 – 1.0>,
    "adr_flag": <0.0 – 1.0>
  },
  "excerpts": {
    "legal_name": <short verbatim quote or "">,
    "share_class_name": <short verbatim quote or "">,
    "share_type": <short verbatim quote or "">,
    "brief_description": <short verbatim quote or "">,
    "adr_flag": <short verbatim quote or "">
  }
}

Field definitions
-----------------
legal_name : The exact legal name of the registrant as stated on the cover
    page (e.g. "Apple Inc.", "Microsoft Corporation").  This is typically
    the line that reads "Name of registrant as specified in its charter."
    Preserve original capitalisation exactly.

share_class_name : The exact security description from the cover page
    (e.g. "Common Stock, par value $0.00001 per share").  Include par value
    if stated.

share_type : Simplified security type.  Choose ONE of:
    "Common Stock", "Preferred Stock", "American Depositary Share",
    "American Depositary Receipt", "Ordinary Share", "Unit", or
    another concise label matching the filing.

brief_description : 1–2 complete sentences describing the company's primary
    business (from Item 1 or the cover page description).  Maximum 300 chars.

adr_flag : true if the registered security is an American Depositary Share
    (ADS) or American Depositary Receipt (ADR).  Otherwise false.
"""


def _build_user_prompt(filing_text: str, company_name: str, form: str) -> str:
    truncated = filing_text[:UNDERLYING_EXTRACTION_CHARS]
    return (
        f"Company: {company_name}\n"
        f"Filing form: {form}\n\n"
        f"--- FILING TEXT (first {UNDERLYING_EXTRACTION_CHARS} characters) ---\n"
        f"{truncated}\n"
        f"--- END OF TEXT ---\n\n"
        "Extract the requested fields from the text above."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_underlying_fields(
    filing_text:  str,
    company_name: str = "",
    form:         str = "10-K",
    model:        str | None = None,
) -> ExtractionResult:
    """Call the configured LLM to extract Tier 2 fields from annual report text.

    Parameters
    ----------
    filing_text:
        Stripped plain text of the 10-K / 20-F annual report.
    company_name:
        Company name added to the prompt for context.
    form:
        Filing form type ("10-K" | "20-F").
    model:
        Optional model override.  When set and the active provider is
        ``"anthropic"``, this value replaces the configured model name.
        For local providers the configured model always takes precedence.

    Returns
    -------
    ExtractionResult
        ``error`` is set (and ``fields`` is empty) if the call fails.
        Partial results are returned when JSON parsing succeeds but some
        fields are missing from the model response.
    """
    if not filing_text or not filing_text.strip():
        return ExtractionResult(error="No filing text provided")

    from underlying.llm_client import (
        load_config, call_underlying_llm, clean_response, try_repair_json,
    )

    cfg = load_config()

    # Optional model override — honoured for Anthropic only (local models are
    # always addressed by their full model-file name from settings)
    if model and cfg.provider == "anthropic":
        cfg.model = model

    user_prompt = _build_user_prompt(filing_text, company_name, form)

    log.info(
        "Underlying LLM extraction: company=%r form=%s chars=%d "
        "provider=%s model=%s",
        company_name, form, len(filing_text), cfg.provider, cfg.model,
    )

    try:
        raw, input_tokens, output_tokens = call_underlying_llm(
            _SYSTEM_PROMPT, user_prompt, cfg,
        )
    except Exception as exc:
        log.error("LLM call failed for underlying extraction: %s", exc)
        return ExtractionResult(error=str(exc))

    result = _parse_response(raw, clean_response, try_repair_json)
    result.input_tokens  = input_tokens
    result.output_tokens = output_tokens
    return result


# ---------------------------------------------------------------------------
# Response parser
# ---------------------------------------------------------------------------


def _parse_response(raw: str, clean_fn=None, repair_fn=None) -> ExtractionResult:
    """Parse the LLM JSON response into an :class:`ExtractionResult`.

    Parameters are injectable for unit-testing without importing llm_client.
    Production callers always pass ``clean_response`` and ``try_repair_json``
    from ``underlying.llm_client``.
    """
    import re as _re

    # ── Text cleanup ───────────────────────────────────────────────────────
    if clean_fn is not None:
        text = clean_fn(raw)
    else:
        # Lightweight fallback (used in tests without llm_client)
        text = raw.strip()
        text = _re.sub(r"^```(?:json)?\s*", "", text, flags=_re.MULTILINE)
        text = _re.sub(r"```\s*$",          "", text, flags=_re.MULTILINE)
        text = text.strip()

    # ── JSON parse with repair fallback ────────────────────────────────────
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        data = repair_fn(text) if repair_fn is not None else None
        if data is None:
            log.warning("JSON parse error in underlying extraction: %s", exc)
            return ExtractionResult(raw_response=raw, error=f"JSON parse error: {exc}")
        log.info("Underlying extraction: repaired truncated JSON response")

    # ── Field extraction ───────────────────────────────────────────────────
    fields_raw:   dict[str, Any] = data.get("fields",     {}) or {}
    conf_raw:     dict[str, Any] = data.get("confidence", {}) or {}
    excerpts_raw: dict[str, Any] = data.get("excerpts",   {}) or {}

    threshold = config.EXTRACTION_CONFIDENCE_THRESHOLD
    results: list[FieldResult] = []

    for fname in _TARGET_FIELDS:
        value      = fields_raw.get(fname)
        confidence = _clamp_conf(conf_raw.get(fname, 0.5))
        excerpt    = str(excerpts_raw.get(fname, ""))[:500]
        src_type   = _FIELD_SOURCE_TYPES.get(fname, "10k_cover")

        # Normalise adr_flag to bool
        if fname == "adr_flag" and value is not None:
            if isinstance(value, bool):
                pass
            elif isinstance(value, str):
                value = value.lower() in ("true", "yes", "1")
            else:
                value = bool(value)

        # Normalise string fields: strip, set None if empty
        if fname != "adr_flag" and isinstance(value, str):
            value = value.strip() or None

        results.append(FieldResult(
            field_name=fname,
            value=value,
            confidence=confidence,
            source_excerpt=excerpt,
            source_type=src_type,
            needs_review=confidence < threshold,
        ))

    return ExtractionResult(fields=results, raw_response=raw)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clamp_conf(raw: Any) -> float:
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5
