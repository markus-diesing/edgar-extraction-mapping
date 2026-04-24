"""
Underlying Data Module — LLM Extractor (Tier 2).

Extracts fields from the 10-K / 20-F cover page and Item 1 text that are not
available from EDGAR structured data (Tier 1) or market data (Tier 3).

Target fields
-------------
share_class_name   e.g. "Common Stock, $0.00001 par value per share"
share_type         e.g. "Common Stock"
brief_description  1–2 sentence company description from Item 1
adr_flag           True if the filing describes ADR / ADS shares

Design decisions
----------------
* The full filing text is truncated to ``UNDERLYING_EXTRACTION_CHARS`` chars
  (cover page + beginning of Item 1) so the prompt stays cheap.
* Claude returns a JSON object with ``fields`` (field_name → value) and
  ``confidence`` (field_name → 0.0–1.0) keys.
* Confidence < ``EXTRACTION_CONFIDENCE_THRESHOLD`` flags the field for review
  in the UI (stored as ``review_status = "needs_review"``).
* Failures (API errors, JSON parse errors) return an empty result so the
  caller can still write Tier 1 data to the DB.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

import anthropic

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Characters of stripped 10-K text passed to the extraction prompt.
# Defined centrally in config.UNDERLYING_EXTRACTION_CHARS — imported below.
# This local alias is kept so call-sites within this module stay readable.
UNDERLYING_EXTRACTION_CHARS: int = config.UNDERLYING_EXTRACTION_CHARS

# Fields the LLM is asked to populate.
_TARGET_FIELDS = [
    "share_class_name",
    "share_type",
    "brief_description",
    "adr_flag",
]

# Maps each target field to the section of the annual report it is drawn from.
# Used to populate FieldResult.source_type and the DB source_type column.
_FIELD_SOURCE_TYPES: dict[str, str] = {
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
    field_name: str
    value: Any                    # str | bool | None
    confidence: float             # 0.0 – 1.0
    source_excerpt: str = ""      # relevant text snippet (best-effort)
    source_type: str = "10k_cover"  # origin section: "10k_cover" | "10k_item1"
    needs_review: bool = False    # True when confidence < threshold


@dataclass
class ExtractionResult:
    """Result of one LLM extraction call."""
    fields: list[FieldResult] = field(default_factory=list)
    raw_response: str = ""        # full Claude response text (for debugging)
    error: str | None = None      # set if Claude call or JSON parse failed

    def get(self, field_name: str) -> FieldResult | None:
        for f in self.fields:
            if f.field_name == field_name:
                return f
        return None

    def as_dict(self) -> dict[str, Any]:
        return {f.field_name: f.value for f in self.fields}


# ---------------------------------------------------------------------------
# Anthropic client (module-level singleton)
# ---------------------------------------------------------------------------

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


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
    "share_class_name": <string or null>,
    "share_type": <string or null>,
    "brief_description": <string or null>,
    "adr_flag": <true | false | null>
  },
  "confidence": {
    "share_class_name": <0.0 – 1.0>,
    "share_type": <0.0 – 1.0>,
    "brief_description": <0.0 – 1.0>,
    "adr_flag": <0.0 – 1.0>
  },
  "excerpts": {
    "share_class_name": <short verbatim quote or "">,
    "share_type": <short verbatim quote or "">,
    "brief_description": <short verbatim quote or "">,
    "adr_flag": <short verbatim quote or "">
  }
}

Field definitions
-----------------
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
    filing_text: str,
    company_name: str = "",
    form: str = "10-K",
    model: str | None = None,
) -> ExtractionResult:
    """Call Claude to extract Tier 2 fields from annual report text.

    Parameters
    ----------
    filing_text:
        Stripped plain text of the 10-K / 20-F annual report.
    company_name:
        Company name for context (added to the prompt).
    form:
        Filing form type ("10-K" | "20-F").
    model:
        Claude model string. Defaults to ``config.CLAUDE_MODEL_DEFAULT``.

    Returns
    -------
    ExtractionResult
        ``error`` is set (and ``fields`` is empty) if the call fails.
        Partial results are returned if JSON parsing succeeds but some fields
        are missing.
    """
    if not filing_text or not filing_text.strip():
        return ExtractionResult(error="No filing text provided")

    model_id = model or config.CLAUDE_MODEL_DEFAULT
    user_prompt = _build_user_prompt(filing_text, company_name, form)

    log.info(
        "Underlying LLM extraction: company=%r form=%s chars=%d model=%s",
        company_name, form, len(filing_text), model_id,
    )

    try:
        client = _get_client()
        response = client.messages.create(
            model=model_id,
            max_tokens=1_024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text if response.content else ""
    except Exception as exc:
        log.error("Claude API call failed for underlying extraction: %s", exc)
        return ExtractionResult(error=str(exc))

    return _parse_response(raw)


def _parse_response(raw: str) -> ExtractionResult:
    """Parse Claude's JSON response into an :class:`ExtractionResult`.

    Tolerates minor formatting issues (leading/trailing whitespace, markdown
    fences).  Returns an error result if JSON cannot be parsed.
    """
    text = raw.strip()
    # Strip markdown code fences if present
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        log.warning("JSON parse error in underlying extraction response: %s", exc)
        return ExtractionResult(raw_response=raw, error=f"JSON parse error: {exc}")

    fields_raw: dict[str, Any] = data.get("fields", {})
    conf_raw: dict[str, Any]   = data.get("confidence", {})
    excerpts_raw: dict[str, Any] = data.get("excerpts", {})

    threshold = config.EXTRACTION_CONFIDENCE_THRESHOLD
    results: list[FieldResult] = []

    for fname in _TARGET_FIELDS:
        value = fields_raw.get(fname)
        confidence = _clamp_conf(conf_raw.get(fname, 0.5))
        excerpt = str(excerpts_raw.get(fname, ""))[:500]   # cap excerpt length
        src_type = _FIELD_SOURCE_TYPES.get(fname, "10k_cover")

        # Normalise adr_flag to bool
        if fname == "adr_flag" and value is not None:
            if isinstance(value, bool):
                pass
            elif isinstance(value, str):
                value = value.lower() in ("true", "yes", "1")
            else:
                value = bool(value)

        # Normalise string fields: strip and set None if empty
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
    """Parse *raw* as a float confidence clamped to [0.0, 1.0]."""
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.5
