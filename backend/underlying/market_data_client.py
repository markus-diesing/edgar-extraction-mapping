"""
Underlying Data Module — Market Data Client (Tier 3).

Provides approximate price series and spot prices for underlying securities.
All Tier 3 data is clearly labelled as approximate and editable by reviewers.

Design
------
``MarketDataClient`` is a :class:`typing.Protocol` (structural subtyping) so
the default yfinance implementation can be swapped for a Bloomberg or other
premium feed without changing call sites.

``YahooFinanceClient`` is the default implementation.  It uses ``yfinance``
with ``auto_adjust=False`` to return unadjusted prices, which is the closest
proxy to the "Initial Value" used in structured product term sheets.

Thread safety: ``YahooFinanceClient`` is stateless; each call creates a new
``yfinance.Ticker`` object.  Concurrent calls are safe.

Data returned
-------------
initial_value       First close price in the requested date range (approx.)
initial_value_date  Corresponding date
closing_value       Most recent close price
closing_value_date  Corresponding date
hist_data_series    JSON string: list of {date, close, volume} dicts
                    covering ``config.MARKET_DATA_PRICE_SERIES_YEARS`` years
"""
from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
from datetime import date, datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable

import yfinance  # Tier-3 optional dependency; listed in requirements.txt

import config

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class MarketDataResult:
    """Result object returned by :class:`MarketDataClient` implementations."""

    __slots__ = (
        "ticker",
        "initial_value",
        "initial_value_date",
        "closing_value",
        "closing_value_date",
        "hist_data_series",   # JSON string
        "source",
        "error",
    )

    def __init__(self) -> None:
        self.ticker: str = ""
        self.initial_value: float | None = None
        self.initial_value_date: date | None = None
        self.closing_value: float | None = None
        self.closing_value_date: date | None = None
        self.hist_data_series: str | None = None   # JSON
        self.source: str = ""
        self.error: str | None = None

    def is_ok(self) -> bool:
        """True if at least a closing price was obtained."""
        return self.error is None and self.closing_value is not None


# ---------------------------------------------------------------------------
# Protocol (interface)
# ---------------------------------------------------------------------------

@runtime_checkable
class MarketDataClient(Protocol):
    """Structural protocol for market data providers.

    Implementors must provide :meth:`fetch`.  They need not inherit from this
    class — duck typing is sufficient.
    """

    def fetch(self, ticker: str, years: int = 5) -> MarketDataResult:
        """Fetch price history for *ticker* covering *years* of daily data.

        Parameters
        ----------
        ticker:
            Exchange ticker symbol (e.g. ``"MSFT"``).
        years:
            Number of calendar years of history to retrieve.

        Returns
        -------
        MarketDataResult
            ``error`` is set on failure; partial data may still be present.
        """
        ...


# ---------------------------------------------------------------------------
# Yahoo Finance implementation
# ---------------------------------------------------------------------------

# Maximum number of daily entries kept in hist_data_series.
# ~2 000 entries ≈ 7.7 years of trading days — well above the configured 5 years.
# Capping prevents abnormally large DB rows for tickers with split/dividend
# corrections that expand the series beyond a single entry per trading day.
_MAX_HIST_ENTRIES = 2_000

# Seconds to wait for a yfinance.history() response before giving up.
# yfinance itself has no timeout parameter; we enforce one via a thread future.
_YFINANCE_TIMEOUT_SECONDS = 30


class YahooFinanceClient:
    """Market data client backed by the ``yfinance`` library.

    Prices are unadjusted (``auto_adjust=False``) to match the prices
    typically referenced in structured product term sheets.

    Limitations
    -----------
    * Yahoo Finance data is approximate and may be delayed.
    * Not suitable for intraday or high-frequency use.
    * ``yfinance`` may return empty DataFrames for tickers not covered.
    """

    source_label: str = "Yahoo Finance (approximate)"

    def fetch(self, ticker: str, years: int | None = None) -> MarketDataResult:
        """Fetch *years* years of daily OHLCV history for *ticker*.

        Parameters
        ----------
        ticker:
            Ticker symbol as used on the exchange.
        years:
            Calendar years of history.  Defaults to
            ``config.MARKET_DATA_PRICE_SERIES_YEARS``.
        """
        years = years or config.MARKET_DATA_PRICE_SERIES_YEARS
        result = MarketDataResult()
        result.ticker = ticker.upper()
        result.source = self.source_label

        end_date = datetime.now(tz=timezone.utc).date()
        start_date = end_date - timedelta(days=365 * years)

        log.info("Fetching market data: ticker=%s years=%d", ticker, years)

        # yfinance has no built-in timeout; enforce one via a thread future so
        # a slow/hung Yahoo Finance request does not block the ingest pipeline.
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    yfinance.Ticker(ticker).history,
                    start=start_date.isoformat(),
                    end=end_date.isoformat(),
                    auto_adjust=False,
                    actions=False,
                )
                hist = future.result(timeout=_YFINANCE_TIMEOUT_SECONDS)
        except _FuturesTimeout:
            log.warning(
                "yfinance timed out after %ds for %r", _YFINANCE_TIMEOUT_SECONDS, ticker
            )
            result.error = (
                f"yfinance timeout after {_YFINANCE_TIMEOUT_SECONDS}s for ticker {ticker!r}"
            )
            return result
        except Exception as exc:
            log.warning("yfinance error for %r: %s", ticker, exc)
            result.error = str(exc)
            return result

        if hist is None or hist.empty:
            log.info("No data returned by yfinance for ticker %r", ticker)
            result.error = f"No data available for ticker {ticker!r}"
            return result

        # Build price series (date + Close only; volume included for reference)
        series: list[dict[str, Any]] = []
        for ts, row in hist.iterrows():
            try:
                close = float(row["Close"])
                vol = int(row["Volume"]) if "Volume" in row else 0
                day = ts.date() if hasattr(ts, "date") else date.fromisoformat(str(ts)[:10])
                series.append({"date": day.isoformat(), "close": round(close, 4), "volume": vol})
            except Exception:
                continue  # skip malformed rows

        if not series:
            result.error = f"Price series empty after processing for {ticker!r}"
            return result

        # Sort ascending by date
        series.sort(key=lambda r: r["date"])

        # Cap to most recent _MAX_HIST_ENTRIES entries to prevent oversized DB rows
        if len(series) > _MAX_HIST_ENTRIES:
            log.warning(
                "Truncating hist_data_series for %r from %d to %d entries",
                ticker, len(series), _MAX_HIST_ENTRIES,
            )
            series = series[-_MAX_HIST_ENTRIES:]

        result.initial_value = series[0]["close"]
        result.initial_value_date = date.fromisoformat(series[0]["date"])
        result.closing_value = series[-1]["close"]
        result.closing_value_date = date.fromisoformat(series[-1]["date"])
        result.hist_data_series = json.dumps(series)

        log.info(
            "Market data OK: ticker=%s close=%.4f date=%s series_len=%d",
            ticker, result.closing_value, result.closing_value_date, len(series),
        )
        return result


# ---------------------------------------------------------------------------
# Module-level default instance
# ---------------------------------------------------------------------------

_default_client: MarketDataClient | None = None


def get_default_client() -> MarketDataClient:
    """Return the module-level default :class:`MarketDataClient` instance.

    The default is :class:`YahooFinanceClient`.  Call :func:`set_default_client`
    to swap in a different implementation (e.g. for tests or Bloomberg feed).
    """
    global _default_client
    if _default_client is None:
        _default_client = YahooFinanceClient()
    return _default_client


def set_default_client(client: MarketDataClient) -> None:
    """Replace the module-level default client (useful for testing / DI)."""
    global _default_client
    _default_client = client


def fetch_market_data(ticker: str, years: int | None = None) -> MarketDataResult:
    """Convenience function: fetch via the default client."""
    return get_default_client().fetch(ticker, years or config.MARKET_DATA_PRICE_SERIES_YEARS)
