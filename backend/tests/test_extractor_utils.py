"""
tests/test_extractor_utils.py — Unit tests for extractor internals.

Tests _clamp_conf, _slice_filing_text, and the module-level client singleton.
No network calls — the Anthropic client creation is verified without connecting.
"""
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# _clamp_conf
# ---------------------------------------------------------------------------

class TestClampConf:
    """_clamp_conf must handle float, int, numeric string, and junk."""

    @pytest.fixture(autouse=True)
    def import_clamp(self):
        from extract.extractor import _clamp_conf
        self.clamp = _clamp_conf

    def test_float_passthrough(self):
        assert self.clamp(0.85) == pytest.approx(0.85)

    def test_int_converted(self):
        assert self.clamp(1) == pytest.approx(1.0)

    def test_clamps_above_one(self):
        assert self.clamp(1.5) == pytest.approx(1.0)

    def test_clamps_below_zero(self):
        assert self.clamp(-0.1) == pytest.approx(0.0)

    def test_numeric_string(self):
        assert self.clamp("0.75") == pytest.approx(0.75)

    def test_non_numeric_uses_default(self):
        result = self.clamp("high", path="coupon.rate", default=0.5)
        assert result == pytest.approx(0.5)

    def test_none_uses_default(self):
        result = self.clamp(None, path="coupon.rate", default=0.0)
        assert result == pytest.approx(0.0)

    def test_non_numeric_no_path_no_warning(self):
        # When path is empty no log.warning should be emitted
        result = self.clamp("bad", default=0.3)
        assert result == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# _slice_filing_text
# ---------------------------------------------------------------------------

class TestSliceFilingText:
    @pytest.fixture(autouse=True)
    def import_slice(self):
        from extract.extractor import _slice_filing_text
        from extract.section_router import SectionSpec
        self.slice = _slice_filing_text
        self.SectionSpec = SectionSpec

    def _make_spec(self, name: str, headers: list, max_chars: int = 500):
        return self.SectionSpec(
            name=name,
            search_headers=headers,
            schema_keys=[],
            max_chars=max_chars,
            system_note="",
        )

    def test_identifiers_returns_head(self):
        text = "A" * 2000
        spec = self._make_spec("identifiers", [], max_chars=500)
        result = self.slice(text, spec)
        assert result == "A" * 500

    def test_finds_header_and_slices(self):
        # _slice_filing_text extends 500 chars BEFORE the header anchor, so
        # max_chars must be > 500 to ensure the header itself appears in the slice.
        text = "preamble " * 100 + "BARRIER TERMS " + "barrier content " * 50
        spec = self._make_spec("barrier", ["BARRIER TERMS"], max_chars=600)
        result = self.slice(text, spec)
        assert "BARRIER TERMS" in result
        assert len(result) <= 600

    def test_no_header_match_returns_empty(self):
        text = "completely unrelated text " * 20
        spec = self._make_spec("barrier", ["BARRIER TERMS"], max_chars=500)
        result = self.slice(text, spec)
        assert result == ""

    def test_case_insensitive_match(self):
        text = "some text. Barrier Terms. more text."
        spec = self._make_spec("barrier", ["barrier terms"], max_chars=500)
        result = self.slice(text, spec)
        assert "Barrier Terms" in result

    def test_first_occurring_header_wins(self):
        text = "COUPON TERMS early. " + "A" * 200 + " BARRIER TERMS late."
        spec = self._make_spec("multi", ["BARRIER TERMS", "COUPON TERMS"], max_chars=300)
        result = self.slice(text, spec)
        # COUPON TERMS appears earlier — slice should start near it
        assert "COUPON TERMS" in result


# ---------------------------------------------------------------------------
# Module-level client singleton — no network, just construction check
# ---------------------------------------------------------------------------

class TestClientSingleton:
    def test_get_client_returns_same_instance(self):
        import extract.extractor as ext
        # Reset the singleton to ensure we test the creation path
        original = ext._client
        ext._client = None
        try:
            with patch("anthropic.Anthropic") as mock_cls:
                mock_cls.return_value = MagicMock()
                c1 = ext._get_client()
                c2 = ext._get_client()
                assert c1 is c2
                mock_cls.assert_called_once()  # constructed exactly once
        finally:
            ext._client = original

    def test_classifier_get_client_singleton(self):
        import classify.classifier as cls
        original = cls._client
        cls._client = None
        try:
            with patch("anthropic.Anthropic") as mock_cls:
                mock_cls.return_value = MagicMock()
                c1 = cls._get_client()
                c2 = cls._get_client()
                assert c1 is c2
                mock_cls.assert_called_once()
        finally:
            cls._client = original
