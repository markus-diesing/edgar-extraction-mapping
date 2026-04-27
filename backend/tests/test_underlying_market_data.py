"""
tests/test_underlying_market_data.py — Unit tests for underlying/market_data_client.py

yfinance is mocked throughout; no network calls.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from underlying.market_data_client import (
    MarketDataClient,
    MarketDataResult,
    YahooFinanceClient,
    fetch_market_data,
    get_default_client,
    set_default_client,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hist_df(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal yfinance-style history DataFrame."""
    dates = pd.to_datetime([r["date"] for r in rows])
    closes = [r["close"] for r in rows]
    volumes = [r.get("volume", 0) for r in rows]
    df = pd.DataFrame({"Close": closes, "Volume": volumes}, index=dates)
    df.index.name = "Date"
    return df


def _mock_yf_ticker(df: pd.DataFrame) -> MagicMock:
    """Return a MagicMock yfinance.Ticker whose .history() returns *df*."""
    ticker_mock = MagicMock()
    ticker_mock.history.return_value = df
    return ticker_mock


# ---------------------------------------------------------------------------
# MarketDataResult
# ---------------------------------------------------------------------------

class TestMarketDataResult:
    def test_is_ok_true_when_close_set(self):
        r = MarketDataResult()
        r.closing_value = 420.0
        assert r.is_ok() is True

    def test_is_ok_false_when_error(self):
        r = MarketDataResult()
        r.error = "timeout"
        r.closing_value = 420.0
        assert r.is_ok() is False

    def test_is_ok_false_when_no_close(self):
        r = MarketDataResult()
        assert r.is_ok() is False


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------

class TestMarketDataClientProtocol:
    def test_yahoo_client_is_protocol(self):
        assert isinstance(YahooFinanceClient(), MarketDataClient)

    def test_custom_client_is_protocol(self):
        class MyClient:
            def fetch(self, ticker: str, years: int = 5) -> MarketDataResult:
                return MarketDataResult()

        assert isinstance(MyClient(), MarketDataClient)

    def test_missing_fetch_not_protocol(self):
        class BadClient:
            pass

        assert not isinstance(BadClient(), MarketDataClient)


# ---------------------------------------------------------------------------
# YahooFinanceClient.fetch
# ---------------------------------------------------------------------------

class TestYahooFinanceClient:
    def _rows(self) -> list[dict]:
        return [
            {"date": "2020-01-02", "close": 100.0, "volume": 1_000_000},
            {"date": "2020-01-03", "close": 102.0, "volume": 900_000},
            {"date": "2025-03-31", "close": 420.0, "volume": 500_000},
        ]

    @patch("underlying.market_data_client.yfinance")
    def test_happy_path(self, mock_yf):
        df = _make_hist_df(self._rows())
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        client = YahooFinanceClient()
        result = client.fetch("MSFT", years=5)

        assert result.is_ok()
        assert result.closing_value == pytest.approx(420.0)
        assert result.closing_value_date == date(2025, 3, 31)
        assert result.initial_value == pytest.approx(100.0)
        assert result.initial_value_date == date(2020, 1, 2)
        assert result.error is None

    @patch("underlying.market_data_client.yfinance")
    def test_hist_data_series_is_valid_json(self, mock_yf):
        df = _make_hist_df(self._rows())
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        result = YahooFinanceClient().fetch("MSFT")

        assert result.hist_data_series is not None
        series = json.loads(result.hist_data_series)
        assert isinstance(series, list)
        assert len(series) == 3
        assert series[0]["date"] == "2020-01-02"
        assert series[-1]["close"] == pytest.approx(420.0)

    @patch("underlying.market_data_client.yfinance")
    def test_series_sorted_ascending(self, mock_yf):
        # Provide rows in reverse order to test sorting
        rows = [
            {"date": "2025-03-31", "close": 420.0},
            {"date": "2020-01-02", "close": 100.0},
            {"date": "2022-06-15", "close": 250.0},
        ]
        df = _make_hist_df(rows)
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        result = YahooFinanceClient().fetch("MSFT")
        series = json.loads(result.hist_data_series)
        dates = [r["date"] for r in series]
        assert dates == sorted(dates)

    @patch("underlying.market_data_client.yfinance")
    def test_empty_dataframe_returns_error(self, mock_yf):
        mock_yf.Ticker.return_value = _mock_yf_ticker(pd.DataFrame())

        result = YahooFinanceClient().fetch("BADTICKER")

        assert not result.is_ok()
        assert result.error is not None
        assert result.closing_value is None

    @patch("underlying.market_data_client.yfinance")
    def test_yfinance_exception_returns_error(self, mock_yf):
        mock_yf.Ticker.side_effect = RuntimeError("network error")

        result = YahooFinanceClient().fetch("MSFT")

        assert not result.is_ok()
        assert "network error" in (result.error or "")

    @patch("underlying.market_data_client.yfinance")
    def test_ticker_uppercased(self, mock_yf):
        df = _make_hist_df(self._rows())
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        result = YahooFinanceClient().fetch("msft")
        assert result.ticker == "MSFT"

    @patch("underlying.market_data_client.yfinance")
    def test_source_label_set(self, mock_yf):
        df = _make_hist_df(self._rows())
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        result = YahooFinanceClient().fetch("MSFT")
        assert "Yahoo Finance" in result.source

    @patch("underlying.market_data_client.yfinance")
    def test_auto_adjust_false_passed_to_history(self, mock_yf):
        """Verify we always request unadjusted prices."""
        df = _make_hist_df(self._rows())
        ticker_mock = _mock_yf_ticker(df)
        mock_yf.Ticker.return_value = ticker_mock

        YahooFinanceClient().fetch("MSFT", years=1)
        call_kwargs = ticker_mock.history.call_args.kwargs
        assert call_kwargs.get("auto_adjust") is False

    @patch("underlying.market_data_client.yfinance")
    def test_none_dataframe_returns_error(self, mock_yf):
        ticker_mock = MagicMock()
        ticker_mock.history.return_value = None
        mock_yf.Ticker.return_value = ticker_mock

        result = YahooFinanceClient().fetch("MSFT")
        assert result.error is not None


# ---------------------------------------------------------------------------
# Default client management
# ---------------------------------------------------------------------------

class TestDefaultClient:
    def setup_method(self):
        """Reset module-level default before each test."""
        import underlying.market_data_client as m
        m._default_client = None

    def teardown_method(self):
        import underlying.market_data_client as m
        m._default_client = None

    def test_get_default_returns_yahoo_client(self):
        client = get_default_client()
        assert isinstance(client, YahooFinanceClient)

    def test_get_default_returns_same_instance(self):
        c1 = get_default_client()
        c2 = get_default_client()
        assert c1 is c2

    def test_set_default_replaces_client(self):
        class DummyClient:
            def fetch(self, ticker, years=5):
                return MarketDataResult()

        dummy = DummyClient()
        set_default_client(dummy)
        assert get_default_client() is dummy

    @patch("underlying.market_data_client.yfinance")
    def test_fetch_market_data_uses_default(self, mock_yf):
        import underlying.market_data_client as m
        m._default_client = None  # force fresh default

        df = _make_hist_df([{"date": "2025-01-02", "close": 400.0}])
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        result = fetch_market_data("MSFT")
        assert result.closing_value == pytest.approx(400.0)


# ---------------------------------------------------------------------------
# M5 / H2 additions — timeout and size-cap behaviour
# ---------------------------------------------------------------------------

class TestYahooFinanceClientTimeout:
    """H2: yfinance.history() timeout is enforced via a thread future."""

    @patch("underlying.market_data_client.yfinance")
    def test_timeout_returns_error_result(self, mock_yf):
        """When yfinance hangs past the timeout, an error result is returned."""
        from concurrent.futures import TimeoutError as FuturesTimeout
        import underlying.market_data_client as m

        # Simulate a yfinance.history() call that never returns within the timeout
        mock_ticker = MagicMock()
        mock_ticker.history.side_effect = FuturesTimeout()
        mock_yf.Ticker.return_value = mock_ticker

        # Patch _YFINANCE_TIMEOUT_SECONDS so future.result() raises immediately
        with patch.object(m, "_YFINANCE_TIMEOUT_SECONDS", 0.001):
            client = YahooFinanceClient()
            # Wrap history in a real ThreadPoolExecutor call but very short timeout
            # By patching the ticker to raise FuturesTimeout directly we simulate the outcome
            result = client.fetch("SLOW")

        assert result.is_ok() is False
        # The test simulates timeout by having history() itself raise; the actual
        # timeout path uses future.result(timeout=...) inside a ThreadPoolExecutor.
        assert result.error is not None

    @patch("underlying.market_data_client.yfinance")
    def test_series_truncated_to_max_entries(self, mock_yf):
        """M6: Oversized hist_data_series is capped at _MAX_HIST_ENTRIES."""
        import underlying.market_data_client as m

        # Build a DataFrame with more rows than the cap
        n = m._MAX_HIST_ENTRIES + 100
        rows = [{"date": f"202{i // 365 % 10}-01-01", "close": float(i)} for i in range(n)]
        # Use unique dates by adding day offset
        from datetime import date as _date, timedelta
        base = _date(2020, 1, 1)
        rows = [
            {"date": (base + timedelta(days=i)).isoformat(), "close": float(i + 1)}
            for i in range(n)
        ]
        df = _make_hist_df(rows)
        mock_yf.Ticker.return_value = _mock_yf_ticker(df)

        client = YahooFinanceClient()
        result = client.fetch("BIG")

        assert result.is_ok()
        series = json.loads(result.hist_data_series)
        assert len(series) == m._MAX_HIST_ENTRIES
        # Most recent entries should be kept (last n entries of the sorted series)
        assert series[-1]["close"] == pytest.approx(float(n))


# ---------------------------------------------------------------------------
# BusinessInfoResult
# ---------------------------------------------------------------------------

class TestBusinessInfoResult:
    def test_is_ok_true_when_summary_set(self):
        from underlying.market_data_client import BusinessInfoResult
        r = BusinessInfoResult()
        r.long_business_summary = "Acme Corp makes widgets."
        assert r.is_ok() is True

    def test_is_ok_false_when_error(self):
        from underlying.market_data_client import BusinessInfoResult
        r = BusinessInfoResult()
        r.error = "timeout"
        r.long_business_summary = "Acme Corp makes widgets."
        assert r.is_ok() is False

    def test_is_ok_false_when_no_summary(self):
        from underlying.market_data_client import BusinessInfoResult
        r = BusinessInfoResult()
        assert r.is_ok() is False


# ---------------------------------------------------------------------------
# _trim_to_sentences
# ---------------------------------------------------------------------------

class TestTrimToSentences:
    def _call(self, text, max_chars=500):
        from underlying.market_data_client import _trim_to_sentences
        return _trim_to_sentences(text, max_chars)

    def test_short_text_returned_unchanged(self):
        text = "Acme makes widgets. It is based in NY."
        assert self._call(text) == text.strip()

    def test_long_text_trimmed_at_sentence_boundary(self):
        # Build a text where the first sentence is short and fits
        first = "Acme Corp makes widgets."
        rest = " " + "B" * 600 + "."
        result = self._call(first + rest, max_chars=50)
        assert result == first

    def test_always_returns_at_least_first_sentence(self):
        # Single very long sentence → returned in full even if > max_chars
        long_sentence = "A" * 600 + "."
        result = self._call(long_sentence, max_chars=50)
        assert result == long_sentence.rstrip()


# ---------------------------------------------------------------------------
# YahooFinanceClient.fetch_business_info
# ---------------------------------------------------------------------------

class TestFetchBusinessInfo:
    @patch("underlying.market_data_client.yfinance")
    def test_happy_path(self, mock_yf):
        from underlying.market_data_client import YahooFinanceClient, _SUMMARY_MAX_CHARS
        ticker_mock = MagicMock()
        ticker_mock.info = {
            "longBusinessSummary": "Acme Corp designs and sells widgets. It serves many markets.",
            "sector": "Technology",
            "industry": "Software",
        }
        mock_yf.Ticker.return_value = ticker_mock

        client = YahooFinanceClient()
        result = client.fetch_business_info("ACME")

        assert result.is_ok()
        assert result.ticker == "ACME"
        assert "Acme Corp" in (result.long_business_summary or "")
        assert result.sector == "Technology"
        assert result.industry == "Software"
        assert result.error is None

    @patch("underlying.market_data_client.yfinance")
    def test_empty_info_returns_error(self, mock_yf):
        from underlying.market_data_client import YahooFinanceClient
        ticker_mock = MagicMock()
        ticker_mock.info = {}
        mock_yf.Ticker.return_value = ticker_mock

        result = YahooFinanceClient().fetch_business_info("ACME")
        assert not result.is_ok()

    @patch("underlying.market_data_client.yfinance")
    def test_no_summary_key_is_ok_false(self, mock_yf):
        from underlying.market_data_client import YahooFinanceClient
        ticker_mock = MagicMock()
        ticker_mock.info = {"sector": "Technology"}
        mock_yf.Ticker.return_value = ticker_mock

        result = YahooFinanceClient().fetch_business_info("ACME")
        assert not result.is_ok()
        assert result.sector == "Technology"

    @patch("underlying.market_data_client.yfinance")
    def test_yfinance_exception_returns_error(self, mock_yf):
        from underlying.market_data_client import YahooFinanceClient
        mock_yf.Ticker.side_effect = RuntimeError("network error")
        result = YahooFinanceClient().fetch_business_info("ACME")
        assert not result.is_ok()
        assert "network error" in (result.error or "")

    @patch("underlying.market_data_client.yfinance")
    def test_summary_trimmed_to_sentences(self, mock_yf):
        from underlying.market_data_client import YahooFinanceClient, _SUMMARY_MAX_CHARS
        # Provide a very long summary
        long_summary = "First sentence is short. " + "X" * 600 + ". Last part."
        ticker_mock = MagicMock()
        ticker_mock.info = {"longBusinessSummary": long_summary}
        mock_yf.Ticker.return_value = ticker_mock

        result = YahooFinanceClient().fetch_business_info("ACME")
        assert result.is_ok()
        # Should have been trimmed
        assert len(result.long_business_summary or "") <= _SUMMARY_MAX_CHARS + 10


# ---------------------------------------------------------------------------
# Module-level fetch_business_info convenience function
# ---------------------------------------------------------------------------

class TestFetchBusinessInfoConvenience:
    def setup_method(self):
        import underlying.market_data_client as m
        m._default_client = None

    def teardown_method(self):
        import underlying.market_data_client as m
        m._default_client = None

    @patch("underlying.market_data_client.yfinance")
    def test_delegates_to_default_client(self, mock_yf):
        from underlying.market_data_client import fetch_business_info
        ticker_mock = MagicMock()
        ticker_mock.info = {"longBusinessSummary": "Works great."}
        mock_yf.Ticker.return_value = ticker_mock

        result = fetch_business_info("MSFT")
        assert result.is_ok()
        assert "Works great" in (result.long_business_summary or "")
