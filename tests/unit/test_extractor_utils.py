"""
Unit tests for pure utility functions in backend/extract/extractor.py.

These tests exercise _clamp_conf and _parse_tool_response without starting
the full FastAPI application — the functions are imported directly after
patching the missing runtime dependencies (database, anthropic client, etc.).
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap: make backend/ importable and stub heavy dependencies so that
# extractor.py can be imported without a live database or Anthropic key.
# ---------------------------------------------------------------------------
BACKEND = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# Stub modules that have side-effects at import time
for _mod in ("database", "schema_loader", "hints_loader", "settings_store",
             "sections.section_loader"):
    sys.modules.setdefault(_mod, MagicMock())

# Stub config before importing extractor (it reads env vars at import)
_config_stub = MagicMock()
_config_stub.PROJECT_ROOT = BACKEND.parent
_config_stub.ANTHROPIC_API_KEY = "test-key"
_config_stub.CLAUDE_MODEL_DEFAULT = "claude-3-5-haiku-20241022"
sys.modules["config"] = _config_stub

# Stub ingest dependency
sys.modules.setdefault("ingest.edgar_client", MagicMock())

import anthropic  # real package — needed for type stubs; already installed

from extract.extractor import _clamp_conf, _parse_tool_response


# ===========================================================================
# _clamp_conf
# ===========================================================================

class TestClampConf(unittest.TestCase):

    # --- happy path ---

    def test_float_in_range(self):
        self.assertAlmostEqual(_clamp_conf(0.75), 0.75)

    def test_float_zero(self):
        self.assertAlmostEqual(_clamp_conf(0.0), 0.0)

    def test_float_one(self):
        self.assertAlmostEqual(_clamp_conf(1.0), 1.0)

    def test_int_input(self):
        """Integers are valid (e.g. default 0 fallback)."""
        self.assertAlmostEqual(_clamp_conf(1), 1.0)
        self.assertAlmostEqual(_clamp_conf(0), 0.0)

    def test_numeric_string(self):
        """Claude sometimes returns confidence as a string like '0.85'."""
        self.assertAlmostEqual(_clamp_conf("0.85"), 0.85)

    def test_numeric_string_with_spaces(self):
        self.assertAlmostEqual(_clamp_conf(" 0.9 "), 0.9)

    # --- clamping ---

    def test_clamps_above_one(self):
        self.assertAlmostEqual(_clamp_conf(1.5), 1.0)

    def test_clamps_below_zero(self):
        self.assertAlmostEqual(_clamp_conf(-0.3), 0.0)

    def test_clamps_large_int(self):
        self.assertAlmostEqual(_clamp_conf(100), 1.0)

    # --- bad input falls back to default ---

    def test_non_numeric_string_uses_default(self):
        """'high' / 'low' are strings Claude occasionally returns."""
        result = _clamp_conf("high", path="some.field", default=0.5)
        self.assertAlmostEqual(result, 0.5)

    def test_non_numeric_string_with_annotation(self):
        """'0.85 (estimated)' — numeric prefix but not directly castable."""
        result = _clamp_conf("0.85 (estimated)", path="some.field", default=0.5)
        self.assertAlmostEqual(result, 0.5)

    def test_none_uses_default(self):
        result = _clamp_conf(None, path="some.field", default=0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_empty_string_uses_default(self):
        result = _clamp_conf("", path="some.field", default=0.5)
        self.assertAlmostEqual(result, 0.5)

    def test_default_is_zero_for_null_field(self):
        """Null fields should receive confidence 0.0, not 0.5."""
        result = _clamp_conf("high", path="some.field", default=0.0)
        self.assertAlmostEqual(result, 0.0)

    def test_no_warning_when_no_path(self):
        """Non-numeric without a path should not crash — just return default."""
        result = _clamp_conf("bad", default=0.3)
        self.assertAlmostEqual(result, 0.3)


# ===========================================================================
# _parse_tool_response
# ===========================================================================

def _make_tool_use_block(prism_data=None, confidence=None, excerpts=None):
    """Build a minimal Anthropic ToolUseBlock mock."""
    block = MagicMock()
    block.type = "tool_use"
    block.name = "submit_prism_extraction"
    block.input = {
        "prism_data":   prism_data   if prism_data   is not None else {"ISIN": "CH1234567890"},
        "_confidence":  confidence   if confidence   is not None else {"ISIN": 0.9},
        "_excerpts":    excerpts     if excerpts     is not None else {"ISIN": "ISIN: CH1234"},
    }
    return block


def _make_message(blocks):
    msg = MagicMock()
    msg.content = blocks
    return msg


class TestParseToolResponse(unittest.TestCase):

    def test_happy_path(self):
        block = _make_tool_use_block()
        msg = _make_message([block])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertIsInstance(prism, dict)
        self.assertIsInstance(conf, dict)
        self.assertIsInstance(excr, dict)
        self.assertEqual(prism.get("ISIN"), "CH1234567890")
        self.assertAlmostEqual(conf.get("ISIN"), 0.9)

    def test_non_dict_prism_data_coerced_to_empty(self):
        """Claude returns '' for prism_data — must not propagate as string."""
        block = _make_tool_use_block(prism_data="")
        msg = _make_message([block])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertEqual(prism, {})

    def test_non_dict_confidence_coerced_to_empty(self):
        block = _make_tool_use_block(confidence=None.__class__())  # NoneType
        block.input["_confidence"] = None
        msg = _make_message([block])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertEqual(conf, {})

    def test_non_dict_excerpts_coerced_to_empty(self):
        block = _make_tool_use_block(excerpts="some string")
        msg = _make_message([block])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertEqual(excr, {})

    def test_no_tool_use_block_returns_empty_dicts(self):
        """No tool_use block (shouldn't happen, but must not crash)."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.name = "something_else"
        # Give it no text attr so the raw-json fallback also returns empty
        del text_block.text
        msg = _make_message([text_block])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertIsInstance(prism, dict)
        self.assertIsInstance(conf, dict)
        self.assertIsInstance(excr, dict)

    def test_empty_content_returns_empty_dicts(self):
        msg = _make_message([])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertEqual(prism, {})
        self.assertEqual(conf, {})
        self.assertEqual(excr, {})

    def test_wrong_tool_name_ignored(self):
        """A tool_use block with a different name must be skipped.

        The fallback path tries hasattr(block, 'text') — so this block must
        not expose a text attribute, matching what a real ToolUseBlock looks like.
        """
        block = MagicMock(spec=["type", "name", "input"])
        block.type = "tool_use"
        block.name = "some_other_tool"
        block.input = {"data": "irrelevant"}
        msg = _make_message([block])
        prism, conf, excr = _parse_tool_response(msg)
        self.assertEqual(prism, {})


if __name__ == "__main__":
    unittest.main()
