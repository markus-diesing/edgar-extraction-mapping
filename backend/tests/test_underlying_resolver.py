"""
tests/test_underlying_resolver.py — Unit tests for underlying/identifier_resolver.py

All network calls are mocked.  No DB, no filesystem I/O beyond what the
module under test performs (ticker cache patching bypasses disk entirely).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from underlying.identifier_resolver import (
    ResolutionResult,
    ResolvedSecurity,
    detect_type,
    resolve,
    _load_ticker_cache,
    _openfigi_lookup,
    _submissions_to_resolved,
    _edgar_name_search,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_submissions(cik: str = "0000789019", name: str = "MICROSOFT CORP",
                       tickers: list[str] | None = None,
                       exchanges: list[str] | None = None) -> dict[str, Any]:
    """Return a minimal EDGAR submissions dict."""
    return {
        "cik": cik.lstrip("0") or "0",
        "name": name,
        "tickers": tickers if tickers is not None else ["MSFT"],
        "exchanges": exchanges if exchanges is not None else ["Nasdaq"],
        "filings": {"recent": {"form": [], "filingDate": [], "reportDate": []}},
    }


# ---------------------------------------------------------------------------
# detect_type
# ---------------------------------------------------------------------------

class TestDetectType:
    def test_cik_7_digits(self):
        assert detect_type("7890190") == "cik"

    def test_cik_10_digits(self):
        assert detect_type("0000789019") == "cik"

    def test_isin(self):
        assert detect_type("US5949181045") == "isin"

    def test_cusip(self):
        # Must contain at least one letter; all-digit 9-char strings match CIK first
        assert detect_type("ABC123456") == "cusip"

    def test_bb_ticker_with_exchange(self):
        assert detect_type("MSFT UW") == "bb_ticker"

    def test_ticker_simple(self):
        assert detect_type("MSFT") == "ticker"

    def test_ticker_with_dot(self):
        assert detect_type("BRK.B") == "ticker"

    def test_name_fallback(self):
        assert detect_type("Microsoft Corporation") == "name"

    def test_name_mixed_case(self):
        assert detect_type("Goldman Sachs") == "name"

    def test_strips_whitespace(self):
        assert detect_type("  MSFT  ") == "ticker"

    def test_isin_case_insensitive_normalised(self):
        # detect_type uppercases before matching
        assert detect_type("us5949181045") == "isin"

    def test_cusip_9_chars(self):
        assert detect_type("ABC123456") == "cusip"

    def test_8_digit_number_is_cik(self):
        assert detect_type("78901900") == "cik"


# ---------------------------------------------------------------------------
# _submissions_to_resolved
# ---------------------------------------------------------------------------

class TestSubmissionsToResolved:
    def test_single_ticker(self):
        data = _make_submissions(tickers=["MSFT"], exchanges=["Nasdaq"])
        results = _submissions_to_resolved(data, "MSFT", "ticker")
        assert len(results) == 1
        r = results[0]
        assert r.ticker == "MSFT"
        assert r.exchange == "Nasdaq"
        assert r.cik == "0000789019"
        assert r.company_name == "MICROSOFT CORP"

    def test_multi_ticker_multi_class(self):
        data = _make_submissions(
            cik="0001652044", name="ALPHABET INC",
            tickers=["GOOGL", "GOOG"], exchanges=["Nasdaq", "Nasdaq"]
        )
        results = _submissions_to_resolved(data, "GOOGL", "ticker")
        assert len(results) == 2
        tickers = [r.ticker for r in results]
        assert "GOOGL" in tickers
        assert "GOOG" in tickers

    def test_no_tickers_uses_cik(self):
        data = _make_submissions(tickers=[], exchanges=[])
        results = _submissions_to_resolved(data, "789019", "cik")
        assert len(results) == 1
        assert results[0].ticker == results[0].cik  # CIK used as de-facto ticker

    def test_cik_is_zero_padded_to_10(self):
        data = _make_submissions(cik="789019")
        results = _submissions_to_resolved(data, "789019", "cik")
        assert results[0].cik == "0000789019"

    def test_exchange_shorter_list(self):
        """If exchanges list is shorter than tickers, missing entries default to ''."""
        data = _make_submissions(tickers=["GOOGL", "GOOG"], exchanges=["Nasdaq"])
        results = _submissions_to_resolved(data, "GOOGL", "ticker")
        exchanges = {r.ticker: r.exchange for r in results}
        assert exchanges["GOOGL"] == "Nasdaq"
        assert exchanges["GOOG"] == ""


# ---------------------------------------------------------------------------
# resolve — CIK path
# ---------------------------------------------------------------------------

class TestResolveCik:
    @patch("underlying.identifier_resolver._fetch_submissions")
    def test_resolved_single_ticker(self, mock_fetch):
        mock_fetch.return_value = _make_submissions()
        result = resolve("0000789019", id_type="cik")
        assert result.status == "resolved"
        assert result.resolved is not None
        assert result.resolved.ticker == "MSFT"

    @patch("underlying.identifier_resolver._fetch_submissions")
    def test_multi_class(self, mock_fetch):
        mock_fetch.return_value = _make_submissions(
            cik="0001652044", name="ALPHABET INC",
            tickers=["GOOGL", "GOOG"], exchanges=["Nasdaq", "Nasdaq"]
        )
        result = resolve("1652044", id_type="cik")
        assert result.status == "multi_class"
        assert len(result.candidates) == 2

    @patch("underlying.identifier_resolver._fetch_submissions")
    def test_not_found_404(self, mock_fetch):
        import httpx
        mock_fetch.side_effect = httpx.HTTPStatusError(
            "Not found", request=MagicMock(), response=MagicMock(status_code=404)
        )
        result = resolve("9999999999", id_type="cik")
        assert result.status == "not_found"

    @patch("underlying.identifier_resolver._fetch_submissions")
    def test_error_on_5xx(self, mock_fetch):
        import httpx
        mock_fetch.side_effect = httpx.HTTPStatusError(
            "Server error", request=MagicMock(), response=MagicMock(status_code=500)
        )
        result = resolve("0000789019", id_type="cik")
        assert result.status == "error"


# ---------------------------------------------------------------------------
# resolve — ticker path
# ---------------------------------------------------------------------------

class TestResolveTicker:
    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    def test_ticker_found_in_cache(self, mock_cache, mock_fetch):
        mock_cache.return_value = {"MSFT": "0000789019"}
        mock_fetch.return_value = _make_submissions()
        result = resolve("MSFT", id_type="ticker")
        assert result.status == "resolved"
        assert result.resolved.ticker == "MSFT"

    @patch("underlying.identifier_resolver._resolve_by_name")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    def test_ticker_not_in_cache_falls_back_to_name(self, mock_cache, mock_name):
        mock_cache.return_value = {}
        mock_name.return_value = ResolutionResult(status="not_found")
        result = resolve("UNKNWN", id_type="ticker")
        mock_name.assert_called_once()
        assert result.status == "not_found"

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    def test_bb_ticker_strips_suffix(self, mock_cache, mock_fetch):
        mock_cache.return_value = {"MSFT": "0000789019"}
        mock_fetch.return_value = _make_submissions()
        result = resolve("MSFT UW", id_type="bb_ticker")
        assert result.status == "resolved"
        assert result.resolved.ticker == "MSFT"


# ---------------------------------------------------------------------------
# resolve — ISIN / CUSIP via OpenFIGI
# ---------------------------------------------------------------------------

class TestResolveOpenFigi:
    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    @patch("underlying.identifier_resolver._openfigi_lookup")
    def test_isin_resolved(self, mock_figi, mock_cache, mock_fetch):
        mock_figi.return_value = ["MSFT"]
        mock_cache.return_value = {"MSFT": "0000789019"}
        mock_fetch.return_value = _make_submissions()
        result = resolve("US5949181045", id_type="isin")
        assert result.status == "resolved"
        assert result.resolved.ticker == "MSFT"

    @patch("underlying.identifier_resolver._openfigi_lookup")
    def test_isin_figi_no_results(self, mock_figi):
        mock_figi.return_value = []
        result = resolve("US5949181045", id_type="isin")
        assert result.status == "not_found"

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    @patch("underlying.identifier_resolver._openfigi_lookup")
    def test_multi_tickers_deduplicated(self, mock_figi, mock_cache, mock_fetch):
        """If OpenFIGI returns two tickers pointing to the same CIK+ticker, dedup."""
        mock_figi.return_value = ["MSFT", "MSFT"]   # duplicates
        mock_cache.return_value = {"MSFT": "0000789019"}
        mock_fetch.return_value = _make_submissions()
        result = resolve("US5949181045", id_type="isin")
        # After dedup, single result → resolved
        assert result.status == "resolved"

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    @patch("underlying.identifier_resolver._openfigi_lookup")
    def test_multi_tickers_different_class(self, mock_figi, mock_cache, mock_fetch):
        """Two different tickers for same company → multi_class."""
        mock_figi.return_value = ["GOOGL", "GOOG"]
        mock_cache.return_value = {"GOOGL": "0001652044", "GOOG": "0001652044"}
        mock_fetch.return_value = _make_submissions(
            cik="0001652044", name="ALPHABET INC",
            tickers=["GOOGL", "GOOG"], exchanges=["Nasdaq", "Nasdaq"]
        )
        result = resolve("US02079K3059", id_type="isin")
        assert result.status == "multi_class"


# ---------------------------------------------------------------------------
# resolve — name search
# ---------------------------------------------------------------------------

class TestResolveByName:
    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._edgar_name_search")
    def test_single_hit_resolved(self, mock_search, mock_fetch):
        mock_search.return_value = [{"display_name": "MICROSOFT CORP", "cik": "0000789019"}]
        mock_fetch.return_value = _make_submissions()
        result = resolve("Microsoft", id_type="name")
        assert result.status == "resolved"

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._edgar_name_search")
    def test_multiple_hits_candidates(self, mock_search, mock_fetch):
        mock_search.return_value = [
            {"display_name": "APPLE INC", "cik": "0000320193"},
            {"display_name": "APPLE HOSPITALITY", "cik": "0001418121"},
        ]
        call_count = 0
        def _fetch_side(cik):
            nonlocal call_count
            call_count += 1
            if cik == "0000320193":
                return _make_submissions(cik="0000320193", name="APPLE INC", tickers=["AAPL"])
            return _make_submissions(cik="0001418121", name="APPLE HOSPITALITY", tickers=["APLE"])
        mock_fetch.side_effect = _fetch_side
        result = resolve("Apple", id_type="name")
        assert result.status == "candidates"
        assert len(result.candidates) == 2

    @patch("underlying.identifier_resolver._edgar_name_search")
    def test_no_hits_not_found(self, mock_search):
        mock_search.return_value = []
        result = resolve("NoSuchCompany XYZ123", id_type="name")
        assert result.status == "not_found"


# ---------------------------------------------------------------------------
# resolve — error handling
# ---------------------------------------------------------------------------

class TestResolveErrors:
    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    def test_unexpected_exception_returns_error(self, mock_cache, mock_fetch):
        mock_cache.return_value = {"MSFT": "0000789019"}
        mock_fetch.side_effect = RuntimeError("connection reset")
        result = resolve("MSFT", id_type="ticker")
        assert result.status == "error"
        assert "connection reset" in (result.error or "")


# ---------------------------------------------------------------------------
# Multi-class auto-resolution via preferred_ticker (KKR fix)
# ---------------------------------------------------------------------------

def _make_kkr_submissions() -> dict[str, Any]:
    """Return an EDGAR submissions dict that mimics KKR's multi-class CIK."""
    return {
        "cik": "1404912",
        "name": "KKR & CO INC",
        "tickers": ["KKR", "KKR-PD", "KKRS", "KKRT"],
        "exchanges": ["NYSE", "NYSE", "NYSE", "NYSE"],
        "filings": {"recent": {"form": [], "filingDate": [], "reportDate": []}},
    }


class TestMultiClassAutoResolution:
    """Verify that typing an exact common-stock ticker for a multi-class CIK
    auto-resolves instead of returning the noisy 'multi_class' status."""

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    def test_ticker_exact_match_auto_resolves(self, mock_cache, mock_fetch):
        """User types 'KKR' → resolved to KKR, not multi_class."""
        mock_cache.return_value = {"KKR": "0001404912"}
        mock_fetch.return_value = _make_kkr_submissions()
        result = resolve("KKR", id_type="ticker")
        assert result.status == "resolved", f"Expected resolved, got {result.status}"
        assert result.resolved is not None
        assert result.resolved.ticker == "KKR"

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    def test_ticker_preferred_series_also_resolves(self, mock_cache, mock_fetch):
        """Typing 'KKR-PD' (preferred shares) also auto-resolves to that class."""
        mock_cache.return_value = {"KKR-PD": "0001404912"}
        mock_fetch.return_value = _make_kkr_submissions()
        result = resolve("KKR-PD", id_type="ticker")
        assert result.status == "resolved"
        assert result.resolved.ticker == "KKR-PD"

    @patch("underlying.identifier_resolver._fetch_submissions")
    def test_cik_path_still_returns_multi_class(self, mock_fetch):
        """Resolving by CIK directly has no preferred ticker → still multi_class.

        This is the correct behaviour: when the user enters a raw CIK they
        should be shown all share classes so they can pick the one they want.
        """
        mock_fetch.return_value = _make_kkr_submissions()
        result = resolve("0001404912", id_type="cik")
        assert result.status == "multi_class"
        assert len(result.candidates) == 4

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    @patch("underlying.identifier_resolver._openfigi_lookup")
    def test_openfigi_preferred_ticker_resolves_multi_class(
        self, mock_figi, mock_cache, mock_fetch
    ):
        """ISIN mapped to 'KKR' by OpenFIGI → auto-resolved despite multi-class CIK."""
        mock_figi.return_value = ["KKR"]
        mock_cache.return_value = {"KKR": "0001404912"}
        mock_fetch.return_value = _make_kkr_submissions()
        result = resolve("US48251W1044", id_type="isin")
        assert result.status == "resolved"
        assert result.resolved is not None
        assert result.resolved.ticker == "KKR"

    @patch("underlying.identifier_resolver._fetch_submissions")
    @patch("underlying.identifier_resolver._load_ticker_cache")
    @patch("underlying.identifier_resolver._openfigi_lookup")
    def test_openfigi_two_common_tickers_stays_multi_class(
        self, mock_figi, mock_cache, mock_fetch
    ):
        """When OpenFIGI returns GOOGL and GOOG (genuinely two share classes),
        the result should remain multi_class even with preferred_ticker logic."""
        mock_figi.return_value = ["GOOGL", "GOOG"]
        mock_cache.return_value = {"GOOGL": "0001652044", "GOOG": "0001652044"}
        mock_fetch.return_value = _make_submissions(
            cik="0001652044", name="ALPHABET INC",
            tickers=["GOOGL", "GOOG"], exchanges=["Nasdaq", "Nasdaq"],
        )
        result = resolve("US02079K3059", id_type="isin")
        assert result.status == "multi_class"
        tickers_returned = {c.ticker for c in result.candidates}
        assert tickers_returned == {"GOOGL", "GOOG"}
