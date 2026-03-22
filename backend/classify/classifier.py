"""
PRISM payout-type classifier — two-stage approach.

Stage 1  (cover page, ~4 K chars):
  • Extract product title / feature keywords from the first page.
  • Classify into one PRISM model (or "unknown").
  • If confidence ≥ CLASSIFICATION_CONFIDENCE_THRESHOLD → done.

Stage 2  (targeted fallback, only when stage-1 is ambiguous):
  • Search the full filing for structural headers (BARRIER, COUPON, AUTOCALL,
    BUFFER, DIGITAL, PARTICIPATION, UNDERLYING, …) and collect up to 1 500
    chars around each match.
  • Re-classify using cover + targeted sections.
  • This specifically handles exotic coupons, complex baskets, and products
    whose key features appear in tables at the end of the document.

"unknown" is an explicit valid output whenever:
  • No model fits with confidence ≥ CLASSIFICATION_MIN_CONFIDENCE.
  • The CUSIP mapping suggests a model not yet in the schema.

The list of models is loaded from prism-v1.schema.json at runtime —
no payout-type logic is hardcoded here.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import anthropic

import config
import database
import schema_loader
import settings_store
from ingest.edgar_client import strip_html

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ClassificationResult:
    payout_type_id: str
    confidence_score: float          # 0.0 – 1.0
    matched_schema_version: str
    classification_timestamp: str
    reasoning: str                   # Claude's explanation (not persisted, for debug)
    title_excerpt: str               # quoted product title from filing page 1
    product_features: dict           # extracted keywords: {type, features, underlyings}
    stage: int                       # 1 = cover page only, 2 = targeted fallback used


# ---------------------------------------------------------------------------
# Structural-feature headers used for targeted section extraction (stage 2)
# ---------------------------------------------------------------------------

_SECTION_HEADERS: list[str] = [
    "BARRIER", "TRIGGER", "KNOCK-IN", "KNOCK IN",
    "AUTOCALL", "AUTO CALL", "AUTOMATIC CALL",
    "BUFFER", "SOFT PROTECTION", "PARTIAL PROTECTION",
    "DIGITAL", "BINARY", "FIXED RETURN",
    "PARTICIPATION", "LEVERAGED",
    "COUPON", "CONTINGENT INTEREST", "CONDITIONAL COUPON",
    "PAYMENT SCHEDULE", "INTEREST PAYMENT",
    "UNDERLYING", "BASKET", "INDEX COMPONENT",
    # Worst-of / best-of basket synonyms (issuer-specific)
    "LEAST PERFORMING", "WORST OF", "WORST-OF",
    "BEST OF", "BEST-OF", "LOWEST PERFORMING",
    # Payout formula anchors — explicitly targets payment mechanics text
    "PAYMENT AT MATURITY", "REDEMPTION AMOUNT", "PAYOUT",
    "PAYMENT UPON MATURITY", "CALCULATION OF PAYMENT",
    "ACCUMULATOR", "DECUMULATOR", "KNOCK-OUT FORWARD",
]

_SECTION_WINDOW = 1_500    # chars to collect around each matched header
_MAX_STAGE2_CHARS = 8_000  # cap for the targeted section block

# Pre-compiled combined pattern — one scan instead of 35+ per stage-2 call
_SECTION_PATTERN = re.compile(
    "|".join(re.escape(h) for h in _SECTION_HEADERS),
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a financial product analyst specialising in structured products.
Your task is to classify a 424B2 filing into exactly one PRISM payout type.

Respond ONLY with a valid JSON object — no markdown, no prose outside the JSON.
"""


def _model_list_text(models: list[str], descriptions: dict[str, str]) -> str:
    lines = []
    for m in models:
        desc = descriptions.get(m, "")
        lines.append(f"  - {m}" + (f"  — {desc}" if desc else ""))
    lines.append(
        "  - unknown  — use this when the filing does not clearly match any model "
        "above with confidence ≥ 0.60, OR when the product belongs to a family "
        "not represented in this list"
    )
    return "\n".join(lines)


def _get_few_shot_examples() -> tuple[list[database.ClassificationFeedback], str]:
    """
    Query up to 3 recent ClassificationFeedback rows (not yet used as examples,
    where a human correction exists) and format them as a few-shot block.

    Returns (rows, formatted_text).  rows is the list to mark after use.
    formatted_text is the block to inject into the Stage 1 prompt, or "" if none.
    """
    try:
        with database.get_session() as session:
            rows = (
                session.query(database.ClassificationFeedback)
                .filter(
                    database.ClassificationFeedback.used_as_example == False,  # noqa: E712
                    database.ClassificationFeedback.corrected_payout_type != None,  # noqa: E711
                )
                .order_by(database.ClassificationFeedback.corrected_at.desc())
                .limit(3)
                .all()
            )
            # Detach from session so we can use ids later
            example_ids = [r.id for r in rows]
            examples = [
                {
                    "id": r.id,
                    "cusip": r.filing.cusip if r.filing else None,
                    "original": r.original_payout_type,
                    "corrected": r.corrected_payout_type,
                    "reason": r.correction_reason or "",
                }
                for r in rows
            ]

        if not examples:
            return [], ""

        lines = ["## Recent human corrections (use as examples):"]
        for ex in examples:
            cusip_str = f"CUSIP {ex['cusip']} | " if ex["cusip"] else ""
            reason_str = f" | Reason: {ex['reason']}" if ex["reason"] else ""
            lines.append(
                f"- {cusip_str}Classifier predicted: {ex['original']} | "
                f"Human correction: {ex['corrected']}{reason_str}"
            )
        return example_ids, "\n".join(lines) + "\n"

    except Exception as exc:
        log.warning("Failed to load few-shot feedback examples: %s", exc)
        return [], ""


def _mark_examples_used(example_ids: list[str]) -> None:
    """Mark ClassificationFeedback rows as used_as_example = True."""
    if not example_ids:
        return
    try:
        with database.get_session() as session:
            for row_id in example_ids:
                row = session.get(database.ClassificationFeedback, row_id)
                if row:
                    row.used_as_example = True
            session.commit()
    except Exception as exc:
        log.warning("Failed to mark feedback examples as used: %s", exc)


def _build_stage1_prompt(
    cover_text: str,
    models: list[str],
    descriptions: dict[str, str],
    cusip_hint: str | None,
    cusip_hint_in_schema: bool,
    few_shot_block: str = "",
) -> str:
    model_list = _model_list_text(models, descriptions)

    hint_section = ""
    if cusip_hint and cusip_hint_in_schema:
        hint_section = (
            f"\nNote: The CUSIP lookup table suggests this may be a **{cusip_hint}** — "
            "treat this as a prior but verify independently.\n"
        )
    elif cusip_hint and not cusip_hint_in_schema:
        hint_section = (
            f"\nNote: The CUSIP lookup table suggests this product is a "
            f"**{cusip_hint}**, but that model does not yet exist in the current schema. "
            "If the filing clearly belongs to that product family and no listed model "
            "fits well, return 'unknown' — do not force a wrong match.\n"
        )

    few_shot_section = f"\n{few_shot_block}" if few_shot_block else ""

    return f"""Classify the following 424B2 filing into one of the PRISM payout types listed below.
{hint_section}{few_shot_section}
Available PRISM models:
{model_list}

Respond with this JSON structure (no other text):
{{
  "payout_type_id": "<model name from the list above, or 'unknown'>",
  "confidence_score": <float 0.0–1.0>,
  "reasoning": "<1–3 sentence explanation>",
  "title_excerpt": "<exact product title / name copied verbatim from the filing>",
  "product_features": {{
    "type": "<e.g. 'autocall barrier note', 'participation note', 'reverse convertible'>",
    "features": ["<e.g. 'autocall'>", "<e.g. 'contingent coupon'>", "<e.g. 'barrier'>"],
    "underlyings": ["<index or equity name>"]
  }}
}}

Rules:
- If confidence < 0.60 you MUST return "unknown".
- Never guess between two similar models — prefer "unknown" over a coin-flip.
- "title_excerpt" must be the exact text of the product name/title from the document.

---
FILING (cover page, first {config.CLASSIFICATION_CHARS:,} characters):
{cover_text}
"""


def _build_stage2_prompt(
    cover_text: str,
    targeted_sections: str,
    models: list[str],
    descriptions: dict[str, str],
    cusip_hint: str | None,
    cusip_hint_in_schema: bool,
    prior_reasoning: str,
    prior_features: dict,
) -> str:
    model_list = _model_list_text(models, descriptions)

    hint_section = ""
    if cusip_hint and cusip_hint_in_schema:
        hint_section = (
            f"\nNote: The CUSIP lookup table suggests this may be a **{cusip_hint}**.\n"
        )
    elif cusip_hint and not cusip_hint_in_schema:
        hint_section = (
            f"\nNote: CUSIP lookup suggests **{cusip_hint}** (not in current schema). "
            "Return 'unknown' if no listed model fits.\n"
        )

    features_hint = ""
    if prior_features:
        features_hint = (
            f"\nFrom the cover page you already identified: "
            f"type='{prior_features.get('type', '')}', "
            f"features={prior_features.get('features', [])}, "
            f"underlyings={prior_features.get('underlyings', [])}.\n"
            f"Prior reasoning: {prior_reasoning}\n"
        )

    return f"""A first classification pass on the cover page was inconclusive.
Additional targeted sections from the full document are provided below to help
disambiguate.{hint_section}{features_hint}
Available PRISM models:
{model_list}

Respond with this JSON structure (no other text):
{{
  "payout_type_id": "<model name from the list above, or 'unknown'>",
  "confidence_score": <float 0.0–1.0>,
  "reasoning": "<1–3 sentence explanation>",
  "title_excerpt": "<exact product title copied verbatim from the filing>",
  "product_features": {{
    "type": "<e.g. 'autocall barrier note'>",
    "features": ["<feature>"],
    "underlyings": ["<name>"]
  }}
}}

Rules:
- If confidence < 0.60 you MUST return "unknown".
- Never guess — prefer "unknown" over a low-confidence forced match.

---
COVER PAGE:
{cover_text}

---
TARGETED SECTIONS (key structural terms found in full document):
{targeted_sections}
"""


# ---------------------------------------------------------------------------
# Targeted section extractor (stage 2)
# ---------------------------------------------------------------------------

def _extract_targeted_sections(full_text: str) -> str:
    """
    Search the full filing for structural-feature headers and return up to
    _MAX_STAGE2_CHARS of context around each match.
    Deduplicates overlapping windows.

    Uses a single pre-compiled combined pattern (_SECTION_PATTERN) instead of
    compiling and running 35+ individual regexes.
    """
    windows: list[tuple[int, int]] = []
    for m in _SECTION_PATTERN.finditer(full_text):
        start = max(0, m.start() - 200)
        end   = min(len(full_text), m.end() + _SECTION_WINDOW)
        windows.append((start, end))

    if not windows:
        return ""

    # Merge overlapping windows
    windows.sort()
    merged: list[tuple[int, int]] = [windows[0]]
    for s, e in windows[1:]:
        if s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    # Collect text, capped at _MAX_STAGE2_CHARS
    sections: list[str] = []
    total = 0
    for s, e in merged:
        chunk = full_text[s:e].strip()
        if total + len(chunk) > _MAX_STAGE2_CHARS:
            chunk = chunk[: _MAX_STAGE2_CHARS - total]
            sections.append(chunk)
            break
        sections.append(chunk)
        total += len(chunk)
        if total >= _MAX_STAGE2_CHARS:
            break

    return "\n\n[...]\n\n".join(sections)


# ---------------------------------------------------------------------------
# Schema descriptions helper
# ---------------------------------------------------------------------------

def _get_model_descriptions(schema: dict[str, Any]) -> dict[str, str]:
    """Return {model_name: description} for all models in the schema."""
    result: dict[str, str] = {}
    for entry in schema.get("oneOf", []):
        const = entry.get("properties", {}).get("model", {}).get("const")
        desc  = entry.get("description", "")
        if const:
            result[const] = desc
    return result


# ---------------------------------------------------------------------------
# Main classifier
# ---------------------------------------------------------------------------

def classify_filing(
    filing_id: str,
    raw_html_path: str,
    cusip_hint: str | None = None,
    cusip_hint_in_schema: bool = True,
) -> ClassificationResult:
    """
    Classify a filing using a two-stage approach and update its database record.

    Args:
        filing_id:             DB id of the Filing row.
        raw_html_path:         Relative path to raw.html (relative to project root).
        cusip_hint:            Known payout_type_id from CUSIP mapping (optional).
        cusip_hint_in_schema:  False when the hint model is not in the current schema.

    Returns ClassificationResult.
    Raises on API error.
    """
    # Load filing text
    abs_path = config.PROJECT_ROOT / raw_html_path
    html     = abs_path.read_text(encoding="utf-8", errors="replace")
    full_text = strip_html(html)
    cover_text = full_text[: config.CLASSIFICATION_CHARS]

    # Load available models + descriptions
    raw_schema   = schema_loader._load_raw_schema()
    models       = schema_loader.list_models()
    descriptions = _get_model_descriptions(raw_schema)
    if not models:
        raise RuntimeError("No PRISM models loaded — check prism-v1.schema.json")

    schema_version = schema_loader.get_schema_version()

    # Resolve active Claude model from runtime settings (changeable without server restart)
    active_model = settings_store.get_settings().get("claude_model", config.CLAUDE_MODEL_DEFAULT)
    # System prompt is static — cache it to reduce token cost on repeated calls
    system_cached = [{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}]

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    # ------------------------------------------------------------------
    # Stage 1 — cover page (with few-shot feedback injection)
    # ------------------------------------------------------------------
    log.info("Classification stage 1: filing=%s  chars=%d  claude=%s", filing_id, len(cover_text), active_model)
    example_ids, few_shot_block = _get_few_shot_examples()
    if example_ids:
        log.info("Injecting %d few-shot feedback example(s) into stage 1 prompt", len(example_ids))
    prompt1 = _build_stage1_prompt(
        cover_text, models, descriptions, cusip_hint, cusip_hint_in_schema,
        few_shot_block=few_shot_block,
    )

    t0 = time.monotonic()
    msg1 = client.messages.create(
        model=active_model,
        max_tokens=768,
        system=system_cached,
        messages=[{"role": "user", "content": prompt1}],
    )
    duration1 = time.monotonic() - t0

    _log_api_usage(
        filing_id=filing_id,
        call_type="classify_stage1",
        input_tokens=msg1.usage.input_tokens,
        output_tokens=msg1.usage.output_tokens,
        duration_seconds=duration1,
        model=active_model,
        cache_read_tokens=getattr(msg1.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(msg1.usage, "cache_creation_input_tokens", 0) or 0,
    )

    result1 = _parse_classification_response(msg1.content[0].text.strip(), models, schema_version, stage=1)
    log.info(
        "Stage 1 result: model=%s  confidence=%.2f",
        result1.payout_type_id, result1.confidence_score,
    )

    # Mark few-shot examples as used now that the stage 1 call completed
    _mark_examples_used(example_ids)

    # If stage 1 is confident enough → done
    if result1.confidence_score >= config.CLASSIFICATION_CONFIDENCE_THRESHOLD:
        _persist(filing_id, result1)
        return result1

    # ------------------------------------------------------------------
    # Stage 2 — targeted fallback (only for ambiguous stage-1)
    # ------------------------------------------------------------------
    log.info("Stage 1 confidence %.2f below threshold — running stage 2 fallback", result1.confidence_score)
    targeted = _extract_targeted_sections(full_text)

    if not targeted:
        log.info("No targeted sections found — keeping stage 1 result")
        _persist(filing_id, result1)
        return result1

    prompt2 = _build_stage2_prompt(
        cover_text, targeted, models, descriptions,
        cusip_hint, cusip_hint_in_schema,
        prior_reasoning=result1.reasoning,
        prior_features=result1.product_features,
    )

    t0 = time.monotonic()
    msg2 = client.messages.create(
        model=active_model,
        max_tokens=768,
        system=system_cached,
        messages=[{"role": "user", "content": prompt2}],
    )
    duration2 = time.monotonic() - t0

    _log_api_usage(
        filing_id=filing_id,
        call_type="classify_stage2",
        input_tokens=msg2.usage.input_tokens,
        output_tokens=msg2.usage.output_tokens,
        duration_seconds=duration2,
        model=active_model,
        cache_read_tokens=getattr(msg2.usage, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(msg2.usage, "cache_creation_input_tokens", 0) or 0,
    )

    result2 = _parse_classification_response(msg2.content[0].text.strip(), models, schema_version, stage=2)
    log.info(
        "Stage 2 result: model=%s  confidence=%.2f",
        result2.payout_type_id, result2.confidence_score,
    )

    # Use whichever stage produced the higher confidence (or the non-unknown)
    final = result2 if result2.confidence_score >= result1.confidence_score else result1
    _persist(filing_id, final)
    return final


# ---------------------------------------------------------------------------
# Persist helper
# ---------------------------------------------------------------------------

def _persist(filing_id: str, result: ClassificationResult) -> None:
    now = datetime.now(timezone.utc).isoformat()
    new_status = (
        "classified"
        if result.confidence_score >= config.CLASSIFICATION_CONFIDENCE_THRESHOLD
        and result.payout_type_id != "unknown"
        else "needs_review"
    )

    with database.get_session() as session:
        filing = session.get(database.Filing, filing_id)
        if filing:
            filing.payout_type_id               = result.payout_type_id
            filing.classification_confidence    = result.confidence_score
            filing.matched_schema_version       = result.matched_schema_version
            filing.classified_at                = now
            filing.status                       = new_status
            filing.classification_title_excerpt = result.title_excerpt
            filing.classification_product_features = json.dumps(result.product_features)
            session.commit()

    log.info(
        "Classification persisted: filing=%s  model=%s  confidence=%.2f  stage=%d  status=%s",
        filing_id, result.payout_type_id, result.confidence_score, result.stage, new_status,
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def _parse_classification_response(
    raw: str,
    known_models: list[str],
    schema_version: str,
    stage: int = 1,
) -> ClassificationResult:
    # Strip markdown fences if present
    raw = re.sub(r"^```[a-z]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$",          "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.error("Failed to parse Claude classification response: %s\nRaw: %s", exc, raw)
        return ClassificationResult(
            payout_type_id="unknown",
            confidence_score=0.0,
            matched_schema_version=schema_version,
            classification_timestamp=datetime.now(timezone.utc).isoformat(),
            reasoning="Failed to parse Claude response.",
            title_excerpt="",
            product_features={},
            stage=stage,
        )

    payout_type = str(data.get("payout_type_id", "unknown"))

    # Validate against known models; "unknown" is always valid
    if payout_type != "unknown" and payout_type not in known_models:
        log.warning("Claude returned unknown model '%s'; marking as unknown", payout_type)
        payout_type = "unknown"

    confidence = float(data.get("confidence_score", 0.0))
    confidence = max(0.0, min(1.0, confidence))

    # Enforce minimum confidence floor
    if confidence < config.CLASSIFICATION_MIN_CONFIDENCE:
        log.info(
            "Confidence %.2f below minimum %.2f — forcing 'unknown'",
            confidence, config.CLASSIFICATION_MIN_CONFIDENCE,
        )
        payout_type = "unknown"

    return ClassificationResult(
        payout_type_id=payout_type,
        confidence_score=confidence,
        matched_schema_version=schema_version,
        classification_timestamp=datetime.now(timezone.utc).isoformat(),
        reasoning=str(data.get("reasoning", "")),
        title_excerpt=str(data.get("title_excerpt", ""))[:300],
        product_features=data.get("product_features", {}),
        stage=stage,
    )


# ---------------------------------------------------------------------------
# Helpers
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
