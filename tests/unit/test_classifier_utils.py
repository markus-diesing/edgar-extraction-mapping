"""
Unit tests for pure utility functions in backend/classify/classifier.py.

Tests _assert_text_response without starting the full FastAPI application.
"""
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

BACKEND = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(BACKEND))

# Stub heavy dependencies
for _mod in ("database", "schema_loader", "hints_loader", "settings_store"):
    sys.modules.setdefault(_mod, MagicMock())

_config_stub = MagicMock()
_config_stub.PROJECT_ROOT = BACKEND.parent
_config_stub.ANTHROPIC_API_KEY = "test-key"
_config_stub.CLAUDE_MODEL_DEFAULT = "claude-3-5-haiku-20241022"
_config_stub.CLASSIFICATION_CONFIDENCE_THRESHOLD = 0.80
_config_stub.CLASSIFICATION_MIN_CONFIDENCE = 0.40
sys.modules["config"] = _config_stub

sys.modules.setdefault("ingest.edgar_client", MagicMock())

from classify.classifier import _assert_text_response


def _make_msg(content_blocks):
    msg = MagicMock()
    msg.content = content_blocks
    return msg


def _make_text_block(text):
    block = MagicMock()
    block.text = text
    return block


class TestAssertTextResponse(unittest.TestCase):

    def test_returns_stripped_text(self):
        block = _make_text_block("  hello world  ")
        msg = _make_msg([block])
        result = _assert_text_response(msg, stage=1)
        self.assertEqual(result, "hello world")

    def test_empty_content_raises_value_error(self):
        msg = _make_msg([])
        with self.assertRaises(ValueError) as ctx:
            _assert_text_response(msg, stage=1)
        self.assertIn("Stage 1", str(ctx.exception))
        self.assertIn("empty", str(ctx.exception))

    def test_stage_number_in_error_message(self):
        msg = _make_msg([])
        with self.assertRaises(ValueError) as ctx:
            _assert_text_response(msg, stage=2)
        self.assertIn("Stage 2", str(ctx.exception))

    def test_block_without_text_attr_raises(self):
        block = MagicMock(spec=[])   # spec=[] means no attributes
        msg = _make_msg([block])
        with self.assertRaises(ValueError) as ctx:
            _assert_text_response(msg, stage=1)
        self.assertIn("Stage 1", str(ctx.exception))

    def test_valid_json_classification_response(self):
        """Simulate a real Claude response fragment."""
        raw = """
{
  "payout_type_id": "yieldEnhancementBarrierCoupon",
  "confidence_score": 0.88,
  "reasoning": "Barrier coupon product with capital at risk."
}
"""
        block = _make_text_block(raw)
        msg = _make_msg([block])
        result = _assert_text_response(msg, stage=1)
        self.assertIn("yieldEnhancementBarrierCoupon", result)

    def test_multiline_text_preserved(self):
        """Stripping only removes leading/trailing whitespace, not internal newlines."""
        text = "line one\nline two\nline three"
        block = _make_text_block(f"\n{text}\n")
        msg = _make_msg([block])
        result = _assert_text_response(msg, stage=1)
        self.assertEqual(result, text)


if __name__ == "__main__":
    unittest.main()
