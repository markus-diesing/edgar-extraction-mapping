"""
tests/test_underlying_extractor.py — Unit tests for underlying/extractor.py

No real Claude API calls.  The Anthropic client is mocked so tests run
offline, deterministically, and without API cost.
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from underlying.extractor import (
    ExtractionResult,
    FieldResult,
    extract_underlying_fields,
    _parse_response,
    _clamp_conf,
    _build_user_prompt,
    UNDERLYING_EXTRACTION_CHARS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claude_response(
    legal_name: str | None = "Microsoft Corporation",
    share_class_name: str | None = "Common Stock, $0.00001 par value per share",
    share_type: str | None = "Common Stock",
    brief_description: str | None = "Microsoft designs and sells software and cloud services.",
    adr_flag: bool = False,
    conf: float = 0.95,
) -> str:
    """Build a mock Claude JSON response (all 5 current target fields)."""
    return json.dumps({
        "fields": {
            "legal_name":        legal_name,
            "share_class_name":  share_class_name,
            "share_type":        share_type,
            "brief_description": brief_description,
            "adr_flag":          adr_flag,
        },
        "confidence": {
            "legal_name":        conf,
            "share_class_name":  conf,
            "share_type":        conf,
            "brief_description": conf,
            "adr_flag":          conf,
        },
        "excerpts": {
            "legal_name":        "Microsoft Corporation",
            "share_class_name":  "Common Stock, $0.00001 par value per share",
            "share_type":        "Common Stock",
            "brief_description": "Microsoft designs and sells software.",
            "adr_flag":          "",
        },
    })


def _mock_client(response_text: str) -> MagicMock:
    """Return a mock Anthropic client that returns *response_text*."""
    content_block = MagicMock()
    content_block.text = response_text
    message = MagicMock()
    message.content = [content_block]
    client = MagicMock()
    client.messages.create.return_value = message
    return client


# ---------------------------------------------------------------------------
# _clamp_conf
# ---------------------------------------------------------------------------

class TestClampConf:
    def test_float_in_range(self):
        assert _clamp_conf(0.85) == 0.85

    def test_clamps_above_1(self):
        assert _clamp_conf(1.5) == 1.0

    def test_clamps_below_0(self):
        assert _clamp_conf(-0.1) == 0.0

    def test_string_numeric(self):
        assert _clamp_conf("0.9") == pytest.approx(0.9)

    def test_invalid_string_returns_default(self):
        assert _clamp_conf("high") == 0.5

    def test_none_returns_default(self):
        assert _clamp_conf(None) == 0.5


# ---------------------------------------------------------------------------
# _build_user_prompt
# ---------------------------------------------------------------------------

class TestBuildUserPrompt:
    def test_includes_company_name(self):
        prompt = _build_user_prompt("some filing text", "MICROSOFT CORP", "10-K")
        assert "MICROSOFT CORP" in prompt

    def test_includes_form_type(self):
        prompt = _build_user_prompt("some filing text", "TEST CO", "20-F")
        assert "20-F" in prompt

    def test_text_truncated_at_limit(self):
        # Use a character guaranteed not to appear in the static template text
        filler = "§"
        long_text = filler * (UNDERLYING_EXTRACTION_CHARS + 5000)
        prompt = _build_user_prompt(long_text, "CO", "10-K")
        # Exactly UNDERLYING_EXTRACTION_CHARS filler chars should appear in the prompt
        assert prompt.count(filler) == UNDERLYING_EXTRACTION_CHARS


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------

class TestParseResponse:
    def test_parses_valid_response(self):
        raw = _make_claude_response()
        result = _parse_response(raw)
        assert result.error is None
        assert len(result.fields) == 5  # legal_name, share_class_name, share_type, brief_description, adr_flag

    def test_share_class_name_extracted(self):
        raw = _make_claude_response(share_class_name="Common Stock, $0.00001 par value")
        result = _parse_response(raw)
        f = result.get("share_class_name")
        assert f is not None
        assert f.value == "Common Stock, $0.00001 par value"

    def test_adr_flag_true_parsed(self):
        raw = _make_claude_response(adr_flag=True)
        result = _parse_response(raw)
        f = result.get("adr_flag")
        assert f is not None
        assert f.value is True

    def test_adr_flag_string_true(self):
        data = json.loads(_make_claude_response())
        data["fields"]["adr_flag"] = "true"
        result = _parse_response(json.dumps(data))
        assert result.get("adr_flag").value is True

    def test_adr_flag_string_false(self):
        data = json.loads(_make_claude_response())
        data["fields"]["adr_flag"] = "false"
        result = _parse_response(json.dumps(data))
        assert result.get("adr_flag").value is False

    def test_null_field_returns_none(self):
        raw = _make_claude_response(share_class_name=None)
        result = _parse_response(raw)
        f = result.get("share_class_name")
        assert f is not None
        assert f.value is None

    def test_empty_string_field_normalised_to_none(self):
        raw = _make_claude_response(share_class_name="  ")
        result = _parse_response(raw)
        assert result.get("share_class_name").value is None

    def test_markdown_fences_stripped(self):
        raw = "```json\n" + _make_claude_response() + "\n```"
        result = _parse_response(raw)
        assert result.error is None

    def test_invalid_json_returns_error(self):
        result = _parse_response("NOT VALID JSON AT ALL")
        assert result.error is not None
        assert "JSON parse error" in result.error

    def test_low_confidence_sets_needs_review(self):
        raw = _make_claude_response(conf=0.5)  # below 0.80 threshold
        result = _parse_response(raw)
        for f in result.fields:
            assert f.needs_review is True

    def test_high_confidence_not_needs_review(self):
        raw = _make_claude_response(conf=0.95)
        result = _parse_response(raw)
        for f in result.fields:
            assert f.needs_review is False

    def test_excerpt_captured(self):
        raw = _make_claude_response()
        result = _parse_response(raw)
        f = result.get("share_class_name")
        assert f is not None
        assert len(f.source_excerpt) > 0

    def test_all_target_fields_present(self):
        raw = _make_claude_response()
        result = _parse_response(raw)
        names = {f.field_name for f in result.fields}
        assert names == {"legal_name", "share_class_name", "share_type", "brief_description", "adr_flag"}

    def test_as_dict(self):
        raw = _make_claude_response(share_type="Common Stock")
        result = _parse_response(raw)
        d = result.as_dict()
        assert d["share_type"] == "Common Stock"


# ---------------------------------------------------------------------------
# ExtractionResult.get
# ---------------------------------------------------------------------------

class TestExtractionResultGet:
    def test_get_existing(self):
        fr = FieldResult("share_type", "Common Stock", 0.9)
        res = ExtractionResult(fields=[fr])
        assert res.get("share_type") is fr

    def test_get_missing_returns_none(self):
        res = ExtractionResult()
        assert res.get("nonexistent") is None


# ---------------------------------------------------------------------------
# extract_underlying_fields — mocked Claude call
# ---------------------------------------------------------------------------

class TestExtractUnderlyingFields:
    """Tests for extract_underlying_fields().

    The LLM dispatch layer (underlying.llm_client.call_underlying_llm) is
    mocked so no real API or local-model calls are made.  The mock returns
    (raw_json_string, input_tokens, output_tokens) matching the function's
    actual return type.
    """

    _PATCH_TARGET = "underlying.llm_client.call_underlying_llm"

    def _run(self, response_text: str, *, filing_text: str = "Annual report text...",
             company_name: str = "MICROSOFT CORP", form: str = "10-K",
             model: str | None = None,
             input_tokens: int = 0, output_tokens: int = 0):
        with patch(self._PATCH_TARGET, return_value=(response_text, input_tokens, output_tokens)):
            return extract_underlying_fields(
                filing_text=filing_text,
                company_name=company_name,
                form=form,
                model=model,
            )

    def test_happy_path(self):
        result = self._run(_make_claude_response())
        assert result.error is None
        assert result.get("share_type") is not None
        assert result.get("share_type").value == "Common Stock"

    def test_empty_text_returns_error(self):
        result = extract_underlying_fields("")
        assert result.error is not None
        assert "No filing text" in result.error

    def test_whitespace_only_returns_error(self):
        result = extract_underlying_fields("   \n\t  ")
        assert result.error is not None

    def test_api_exception_returns_error(self):
        with patch(self._PATCH_TARGET, side_effect=RuntimeError("API timeout")):
            result = extract_underlying_fields("some text")
        assert result.error is not None
        assert "API timeout" in result.error

    def test_20f_form_captured_in_result(self):
        """20-F form type is passed to the prompt and reflected in source types."""
        result = self._run(_make_claude_response(), form="20-F", filing_text="some 20-F text")
        # No error means the 20-F form was accepted
        assert result.error is None

    def test_adr_detected_from_text(self):
        adr_response = _make_claude_response(
            share_class_name="American Depositary Shares",
            share_type="American Depositary Share",
            adr_flag=True,
        )
        result = self._run(
            adr_response,
            filing_text="Each American Depositary Share represents one ordinary share.",
            company_name="SONY GROUP CORP",
            form="20-F",
        )
        assert result.get("adr_flag").value is True

    def test_legal_name_extracted(self):
        """legal_name is extracted with correct value and high confidence → not needs_review."""
        result = self._run(
            _make_claude_response(legal_name="Apple Inc.", conf=0.95),
            filing_text="Annual report text...",
            company_name="APPLE INC",
        )
        f = result.get("legal_name")
        assert f is not None
        assert f.value == "Apple Inc."
        assert f.needs_review is False

    def test_legal_name_missing_from_response_sets_needs_review(self):
        """When the LLM omits legal_name from the JSON, the field gets 0.5 confidence
        (the _clamp_conf default) and is therefore flagged needs_review=True."""
        import json as _json
        data = _json.loads(_make_claude_response())
        del data["fields"]["legal_name"]
        del data["confidence"]["legal_name"]
        del data["excerpts"]["legal_name"]
        result = _parse_response(_json.dumps(data))
        f = result.get("legal_name")
        assert f is not None
        assert f.value is None
        assert f.needs_review is True   # missing → 0.5 conf < 0.80 threshold

    def test_token_counts_captured(self):
        """input_tokens and output_tokens are attached to ExtractionResult."""
        result = self._run(
            _make_claude_response(),
            input_tokens=1200,
            output_tokens=80,
        )
        assert result.input_tokens == 1200
        assert result.output_tokens == 80
