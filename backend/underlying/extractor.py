"""
Underlying Data Module — LLM Extractor (Tier 2).

Extracts fields from the 10-K / 20-F cover page and Item 1 text that are not
available from EDGAR structured data (Tier 1) or market data (Tier 3).

Target fields
-------------
legal_name         Exact legal name of the registrant (cover page)
share_class_name   e.g. "Class A Common Stock" (class name only, NO par value)
par_value          e.g. "$0.001 par value" (separate from class name)
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
* ``try_repair_json`` (from llm_client) recovers malformed JSON responses:
  unescaped inner double-quotes (SEC filing text with ``("VCS")``) handled
  by the json_repair library; LM Studio MLX truncation covered by suffix
  injection fallback.
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
    "par_value",
    "share_type",
    "brief_description",
    "adr_flag",
]

_FIELD_SOURCE_TYPES: dict[str, str] = {
    "legal_name":        "10k_cover",
    "share_class_name":  "10k_cover",
    "par_value":         "10k_cover",
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
    "par_value": <string or null>,
    "share_type": <string or null>,
    "brief_description": <string or null>,
    "adr_flag": <true | false | null>
  },
  "confidence": {
    "legal_name": <0.0 – 1.0>,
    "share_class_name": <0.0 – 1.0>,
    "par_value": <0.0 – 1.0>,
    "share_type": <0.0 – 1.0>,
    "brief_description": <0.0 – 1.0>,
    "adr_flag": <0.0 – 1.0>
  },
  "excerpts": {
    "legal_name": <short verbatim quote or "">,
    "share_class_name": <short verbatim quote or "">,
    "par_value": <short verbatim quote or "">,
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

share_class_name : The share class name ONLY — do NOT include par value.
    Examples: "Common Stock", "Class A Common Stock", "Class C Capital Stock",
    "Ordinary Shares", "American Depositary Shares".
    IMPORTANT — multi-class filers: if the cover page lists multiple share
    classes (e.g. Class A + Class C), extract the class whose Trading Symbol
    matches the Ticker provided in the user message.  If no Ticker is given,
    extract the first / primary listed class.

par_value : The par value of the share as stated on the cover page, exactly
    as written (e.g. "$0.001 par value", "par value $0.00001 per share",
    "no par value").  null if par value is not stated.
    IMPORTANT — multi-class filers: match the same row as share_class_name.

share_type : Simplified security type.  Choose ONE of:
    "Common Stock", "Preferred Stock", "American Depositary Share",
    "American Depositary Receipt", "Ordinary Share", "Unit", or
    another concise label matching the filing.

brief_description : The company's primary business description taken directly
    from the Business Overview or the opening paragraph of Item 1.
    PREFERENCE ORDER (strictly in this order):
      1. Quote the Overview / opening paragraph verbatim if it is ≤ 500 chars
         and reads as a complete, standalone description.
      2. If the verbatim text is > 500 chars, quote just the first 1–2 complete
         sentences (up to 500 chars) without paraphrasing.
      3. Only write a condensed summary if no suitable verbatim passage exists
         (e.g. the section is truncated or contains only bullet lists).
    Do NOT invent content or add information not present in the text.

adr_flag : true if the registered security is an American Depositary Share
    (ADS) or American Depositary Receipt (ADR).  Otherwise false.
"""


def _build_user_prompt(
    filing_text: str,
    company_name: str,
    form: str,
    ticker: str = "",
) -> str:
    truncated = filing_text[:UNDERLYING_EXTRACTION_CHARS]
    ticker_line = f"Ticker: {ticker}\n" if ticker else ""
    return (
        f"Company: {company_name}\n"
        f"Filing form: {form}\n"
        f"{ticker_line}"
        f"\n--- FILING TEXT (first {UNDERLYING_EXTRACTION_CHARS} characters) ---\n"
        f"{truncated}\n"
        f"--- END OF TEXT ---\n\n"
        "Extract the requested fields from the text above."
        + (
            f"  For share_class_name and par_value extract the row whose"
            f" Trading Symbol is {ticker}."
            if ticker else ""
        )
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_underlying_fields(
    filing_text:  str,
    company_name: str = "",
    form:         str = "10-K",
    ticker:       str = "",
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
    ticker:
        Exchange ticker symbol for this specific security.  Used to
        disambiguate share_class_name / par_value in multi-class filings
        (e.g. GOOGL → Class A Common Stock; GOOG → Class C Capital Stock).
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

    user_prompt = _build_user_prompt(filing_text, company_name, form, ticker)

    log.info(
        "Underlying LLM extraction: company=%r ticker=%r form=%s chars=%d "
        "provider=%s model=%s",
        company_name, ticker, form, len(filing_text), cfg.provider, cfg.model,
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


# ---------------------------------------------------------------------------
# 424B2 brief_description fallback extractor
# ---------------------------------------------------------------------------

_424B2_SYSTEM_PROMPT = """\
You are a financial data analyst.  You are given a short excerpt from a
424B2 structured product filing.  The excerpt was selected because it
mentions a specific company.

Extract a brief business description of that company from the excerpt.
Respond ONLY with a valid JSON object — no markdown, no commentary:

{
  "brief_description": <1–2 sentence verbatim or near-verbatim quote, or null>,
  "confidence": <0.0 – 1.0>
}

Rules:
- Use verbatim or near-verbatim text from the excerpt when possible.
- Return null if the excerpt does not contain a meaningful description.
- Maximum 500 characters.
"""


def extract_brief_description_from_424b2(
    context_text: str,
    company_name: str,
) -> FieldResult | None:
    """Extract ``brief_description`` from a 424B2 filing excerpt.

    This is the level-3 fallback in the brief_description waterfall.  Called
    only when both yfinance and the 10-K LLM paths yielded no description.

    Parameters
    ----------
    context_text:
        A short window (~2 000 chars) from a 424B2 filing that mentions the
        company by name.
    company_name:
        The company's name — included in the user prompt for context.

    Returns
    -------
    FieldResult | None
        ``None`` on LLM failure or if the model returns null confidence.
    """
    if not context_text or not context_text.strip():
        return None

    from underlying.llm_client import (
        load_config, call_underlying_llm, clean_response, try_repair_json,
    )

    cfg = load_config()
    user_prompt = (
        f"Company: {company_name}\n\n"
        f"--- 424B2 EXCERPT ---\n{context_text[:2_000]}\n--- END ---\n\n"
        "Extract a brief description of this company from the excerpt above."
    )

    log.info(
        "424B2 brief_description fallback: company=%r provider=%s",
        company_name, cfg.provider,
    )

    try:
        raw, input_tokens, output_tokens = call_underlying_llm(
            _424B2_SYSTEM_PROMPT, user_prompt, cfg,
        )
    except Exception as exc:
        log.warning("424B2 LLM call failed for %r: %s", company_name, exc)
        return None

    text = clean_response(raw)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = try_repair_json(text)
        if data is None:
            log.warning("424B2 JSON parse failed for %r", company_name)
            return None

    desc = data.get("brief_description")
    conf = _clamp_conf(data.get("confidence", 0.5))

    if not desc or not isinstance(desc, str) or not desc.strip():
        return None

    return FieldResult(
        field_name="brief_description",
        value=desc.strip(),
        confidence=conf,
        source_excerpt=desc.strip()[:200],
        source_type="424b2_llm",
        needs_review=conf < config.EXTRACTION_CONFIDENCE_THRESHOLD,
    )
