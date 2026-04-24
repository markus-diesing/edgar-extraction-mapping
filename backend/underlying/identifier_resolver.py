"""
Underlying Data Module — Identifier Resolver.

Resolves any user-supplied identifier (ticker, ISIN, CUSIP, CIK, Bloomberg
ticker, or company name) to one or more EDGAR CIK numbers and their
associated submission metadata.

Resolution chain:
    cik        → direct EDGAR submissions lookup
    ticker     → company_tickers.json (cached EDGAR file)
    bb_ticker  → strip exchange suffix → resolve as ticker
    isin       → OpenFIGI API → ticker → CIK
    cusip      → OpenFIGI API → ticker → CIK
    name       → EDGAR EFTS company search (returns candidates for user pick)
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import config
from ingest.edgar_client import _get, SUBMISSIONS_BASE

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class IdentifierType:
    """Constants for identifier type strings used throughout the module."""
    CIK:       str = "cik"
    TICKER:    str = "ticker"
    BB_TICKER: str = "bb_ticker"
    ISIN:      str = "isin"
    CUSIP:     str = "cusip"
    NAME:      str = "name"


@dataclass
class ResolvedSecurity:
    """A single resolution result — one CIK + ticker combination."""
    cik: str                          # zero-padded 10-digit EDGAR CIK
    ticker: str                       # primary ticker for this share class
    company_name: str
    exchange: str
    tickers: list[str] = field(default_factory=list)   # all tickers for this CIK
    exchanges: list[str] = field(default_factory=list)
    source_identifier: str = ""       # the raw value the user typed
    source_identifier_type: str = ""  # detected type string


@dataclass
class ResolutionResult:
    """Return value of :func:`resolve`."""
    status: str                                   # "resolved" | "multi_class" | "candidates" | "not_found" | "error"
    resolved: ResolvedSecurity | None = None      # set when status == "resolved"
    candidates: list[ResolvedSecurity] = field(default_factory=list)  # multi_class or candidates
    error: str | None = None


# ---------------------------------------------------------------------------
# Identifier detection
# ---------------------------------------------------------------------------

# Regex patterns evaluated in order. First match wins.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cik",       re.compile(r"^\d{7,10}$")),
    ("isin",      re.compile(r"^[A-Z]{2}[A-Z0-9]{10}$")),
    ("cusip",     re.compile(r"^[A-Z0-9]{9}$")),
    ("bb_ticker", re.compile(r"^[A-Z0-9]{1,6}\s+[A-Z]{2}$")),  # e.g. "MSFT UW", "VOD LN"
    ("ticker",    re.compile(r"^[A-Z\.\-]{1,6}$")),
]


def detect_type(raw: str) -> str:
    """Detect the identifier type from the raw string.

    Returns one of: ``"cik"``, ``"isin"``, ``"cusip"``, ``"bb_ticker"``,
    ``"ticker"``, ``"name"``.
    """
    normalized = raw.strip().upper()
    for id_type, pattern in _PATTERNS:
        if pattern.match(normalized):
            return id_type
    return "name"


# ---------------------------------------------------------------------------
# company_tickers.json cache
# ---------------------------------------------------------------------------

_ticker_cache: dict[str, str] | None = None   # ticker (upper) → zero-padded CIK
_ticker_cache_loaded_at: float = 0.0
_ticker_cache_lock = threading.Lock()


def _load_ticker_cache() -> dict[str, str]:
    """Return the cached ticker → CIK mapping, refreshing if stale or absent.

    Thread-safety
    -------------
    Uses a double-checked locking pattern:

    1. A fast unlocked check avoids lock contention on the hot path (cache
       is valid and warm).
    2. A second check *inside* the lock prevents multiple threads from all
       simultaneously detecting a stale cache and each racing to reload it.
    """
    global _ticker_cache, _ticker_cache_loaded_at

    # Fast path — no lock needed if cache is clearly fresh
    now = time.monotonic()
    if _ticker_cache is not None and (now - _ticker_cache_loaded_at) < config.COMPANY_TICKERS_CACHE_TTL:
        return _ticker_cache

    # Slow path — acquire lock, then re-check before doing expensive I/O
    with _ticker_cache_lock:
        now = time.monotonic()
        if _ticker_cache is not None and (now - _ticker_cache_loaded_at) < config.COMPANY_TICKERS_CACHE_TTL:
            return _ticker_cache  # another thread already refreshed it

        cache_file: Path = config.COMPANY_TICKERS_CACHE_FILE

        # Try to read from disk cache (avoids network call on cold start)
        if cache_file.exists():
            mtime = cache_file.stat().st_mtime
            age = time.time() - mtime
            if age < config.COMPANY_TICKERS_CACHE_TTL:
                log.debug("Loading company_tickers cache from disk (%d s old)", int(age))
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                _ticker_cache = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
                _ticker_cache_loaded_at = now
                return _ticker_cache

        # Fetch from EDGAR
        log.info("Fetching company_tickers.json from EDGAR (cache missing or stale)")
        try:
            resp = _get(config.COMPANY_TICKERS_URL)
            resp.raise_for_status()
            raw = resp.json()
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(raw), encoding="utf-8")
            _ticker_cache = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
            _ticker_cache_loaded_at = now
            log.info("company_tickers cache refreshed (%d entries)", len(_ticker_cache))
        except Exception as exc:
            log.warning("Failed to fetch company_tickers.json: %s", exc)
            if cache_file.exists():
                log.warning("Falling back to stale disk cache")
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                _ticker_cache = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in raw.values()}
            else:
                _ticker_cache = {}
            _ticker_cache_loaded_at = now

        return _ticker_cache


# ---------------------------------------------------------------------------
# EDGAR submissions lookup
# ---------------------------------------------------------------------------

def _fetch_submissions(cik_padded: str) -> dict[str, Any]:
    """Fetch the EDGAR submissions JSON for a CIK. Raises on HTTP error."""
    url = f"{SUBMISSIONS_BASE}/CIK{cik_padded}.json"
    resp = _get(url)
    resp.raise_for_status()
    return resp.json()


def _submissions_to_resolved(data: dict[str, Any], source_id: str, source_type: str) -> list[ResolvedSecurity]:
    """Convert an EDGAR submissions JSON dict into :class:`ResolvedSecurity` objects.

    Returns one object per ticker so that multi-class companies (e.g. Alphabet)
    produce separate entries, each representing one share class.
    """
    cik_raw: str = str(data.get("cik", "")).zfill(10)
    company_name: str = data.get("name", "")
    tickers: list[str] = data.get("tickers", [])
    exchanges: list[str] = data.get("exchanges", [])

    if not tickers:
        # Company with no listed tickers — use CIK as de-facto identifier
        return [ResolvedSecurity(
            cik=cik_raw,
            ticker=cik_raw,
            company_name=company_name,
            exchange="",
            tickers=[],
            exchanges=[],
            source_identifier=source_id,
            source_identifier_type=source_type,
        )]

    results: list[ResolvedSecurity] = []
    for i, ticker in enumerate(tickers):
        exchange = exchanges[i] if i < len(exchanges) else ""
        results.append(ResolvedSecurity(
            cik=cik_raw,
            ticker=ticker,
            company_name=company_name,
            exchange=exchange,
            tickers=tickers,
            exchanges=exchanges,
            source_identifier=source_id,
            source_identifier_type=source_type,
        ))
    return results


# ---------------------------------------------------------------------------
# OpenFIGI resolution (ISIN / CUSIP → ticker)
# ---------------------------------------------------------------------------

_FIGI_ID_TYPE_MAP = {
    "isin":  "ID_ISIN",
    "cusip": "ID_CUSIP",
}

_openfigi_last_call: float = 0.0
_openfigi_rate_lock = threading.Lock()


def _openfigi_lookup(identifier: str, id_type: str) -> list[str]:
    """Call the OpenFIGI API and return a list of tickers for the given identifier.

    Uses the free-tier endpoint (no API key). Rate-limited to
    :data:`config.OPENFIGI_RATE_LIMIT_DELAY` seconds between calls.

    Returns an empty list on failure or no match.
    """
    global _openfigi_last_call
    figi_type = _FIGI_ID_TYPE_MAP.get(id_type)
    if not figi_type:
        return []

    # Rate limiting — lock protects _openfigi_last_call against concurrent reads/writes
    with _openfigi_rate_lock:
        now = time.monotonic()
        elapsed = now - _openfigi_last_call
        if elapsed < config.OPENFIGI_RATE_LIMIT_DELAY:
            time.sleep(config.OPENFIGI_RATE_LIMIT_DELAY - elapsed)
        _openfigi_last_call = time.monotonic()

    payload = [{"idType": figi_type, "idValue": identifier.upper()}]
    try:
        resp = httpx.post(
            config.OPENFIGI_API_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.warning("OpenFIGI lookup failed for %s %r: %s", id_type, identifier, exc)
        return []

    tickers: list[str] = []
    for entry in data:
        for item in entry.get("data", []):
            ticker = item.get("ticker")
            # Prefer common stock / equity; skip bonds, warrants, etc.
            security_type = item.get("securityType2", "") or item.get("securityType", "")
            if ticker and "Common" in security_type:
                tickers.append(ticker)
    # Fallback: accept any ticker if no common stock found
    if not tickers:
        for entry in data:
            for item in entry.get("data", []):
                ticker = item.get("ticker")
                if ticker:
                    tickers.append(ticker)

    return list(dict.fromkeys(tickers))  # de-duplicate preserving order


# ---------------------------------------------------------------------------
# EDGAR EFTS company name search
# ---------------------------------------------------------------------------

_EFTS_COMPANY_URL = "https://efts.sec.gov/LATEST/search-index"


def _edgar_name_search(name: str, limit: int = 5) -> list[dict[str, Any]]:
    """Search EDGAR for companies by name. Returns up to *limit* hit dicts."""
    try:
        resp = _get(
            _EFTS_COMPANY_URL,
            params={"q": f'"{name}"', "forms": "10-K,20-F,40-F", "size": limit},
        )
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
    except Exception as exc:
        log.warning("EDGAR name search failed for %r: %s", name, exc)
        return []

    results: list[dict[str, Any]] = []
    for h in hits:
        src = h.get("_source", {})
        display = (src.get("display_names") or [""])[0]
        ciks = src.get("ciks") or []
        if ciks:
            results.append({"display_name": display, "cik": str(ciks[0]).zfill(10)})
    return results


# ---------------------------------------------------------------------------
# Public resolution entry point
# ---------------------------------------------------------------------------

def resolve(raw: str, id_type: str | None = None) -> ResolutionResult:
    """Resolve any identifier string to one or more :class:`ResolvedSecurity` objects.

    Parameters
    ----------
    raw:
        The identifier as entered by the user (ticker, ISIN, CUSIP, CIK, name, …).
    id_type:
        Optional explicit type. When ``None``, :func:`detect_type` is used.

    Returns
    -------
    ResolutionResult
        ``status`` is one of:

        ``"resolved"``
            Exactly one result; ``resolved`` is set.
        ``"multi_class"``
            The CIK has multiple listed tickers (e.g. GOOGL + GOOG).
            ``candidates`` lists all classes; the frontend should ask the user
            which ones to ingest.
        ``"candidates"``
            A name search returned multiple companies; ``candidates`` lists them
            so the user can pick.
        ``"not_found"``
            Resolution produced no results.
        ``"error"``
            An unexpected error occurred; ``error`` carries the message.
    """
    raw = raw.strip()
    detected_type = id_type or detect_type(raw)
    log.info("Resolving identifier: %r  type=%s", raw, detected_type)

    try:
        if detected_type == "cik":
            return _resolve_cik(raw.zfill(10), raw, detected_type)

        if detected_type == "ticker":
            return _resolve_ticker(raw.upper(), raw, detected_type)

        if detected_type == "bb_ticker":
            # Strip exchange suffix (e.g. "MSFT UW" → "MSFT")
            ticker_part = raw.split()[0].upper()
            result = _resolve_ticker(ticker_part, raw, detected_type)
            return result

        if detected_type in ("isin", "cusip"):
            return _resolve_via_openfigi(raw.upper(), detected_type)

        if detected_type == "name":
            return _resolve_by_name(raw, raw, detected_type)

    except Exception as exc:
        log.error("Unexpected error resolving %r: %s", raw, exc, exc_info=True)
        return ResolutionResult(status="error", error=str(exc))

    return ResolutionResult(status="not_found")


# ---------------------------------------------------------------------------
# Internal resolution helpers
# ---------------------------------------------------------------------------

def _resolve_cik(cik_padded: str, source_id: str, source_type: str) -> ResolutionResult:
    try:
        data = _fetch_submissions(cik_padded)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return ResolutionResult(status="not_found")
        return ResolutionResult(status="error", error=str(exc))

    securities = _submissions_to_resolved(data, source_id, source_type)
    if len(securities) == 1:
        return ResolutionResult(status="resolved", resolved=securities[0])
    if len(securities) > 1:
        return ResolutionResult(status="multi_class", candidates=securities)
    return ResolutionResult(status="not_found")


def _resolve_ticker(ticker: str, source_id: str, source_type: str) -> ResolutionResult:
    cache = _load_ticker_cache()
    cik = cache.get(ticker)
    if not cik:
        log.debug("Ticker %r not found in company_tickers cache", ticker)
        # Fall back to name search so we still get candidates
        return _resolve_by_name(ticker, source_id, source_type)
    return _resolve_cik(cik, source_id, source_type)


def _resolve_via_openfigi(identifier: str, id_type: str) -> ResolutionResult:
    tickers = _openfigi_lookup(identifier, id_type)
    if not tickers:
        log.info("OpenFIGI returned no results for %s %r", id_type, identifier)
        return ResolutionResult(status="not_found")

    # Try each resolved ticker until we get a hit
    candidates: list[ResolvedSecurity] = []
    cache = _load_ticker_cache()
    for ticker in tickers:
        cik = cache.get(ticker.upper())
        if not cik:
            continue
        try:
            data = _fetch_submissions(cik)
        except Exception:
            continue
        securities = _submissions_to_resolved(data, identifier, id_type)
        candidates.extend(securities)

    if not candidates:
        return ResolutionResult(status="not_found")
    if len(candidates) == 1:
        return ResolutionResult(status="resolved", resolved=candidates[0])
    # Multiple tickers from FIGI → likely multi-class; return as candidates
    # De-duplicate by (cik, ticker)
    seen: set[tuple[str, str]] = set()
    unique: list[ResolvedSecurity] = []
    for sec in candidates:
        key = (sec.cik, sec.ticker)
        if key not in seen:
            seen.add(key)
            unique.append(sec)
    if len(unique) == 1:
        return ResolutionResult(status="resolved", resolved=unique[0])
    return ResolutionResult(status="multi_class", candidates=unique)


def _resolve_by_name(name: str, source_id: str, source_type: str) -> ResolutionResult:
    hits = _edgar_name_search(name, limit=5)
    if not hits:
        return ResolutionResult(status="not_found")

    candidates: list[ResolvedSecurity] = []
    for hit in hits[:5]:
        try:
            data = _fetch_submissions(hit["cik"])
        except Exception:
            continue
        securities = _submissions_to_resolved(data, source_id, source_type)
        if securities:
            candidates.append(securities[0])   # take primary ticker per company for the picker

    if not candidates:
        return ResolutionResult(status="not_found")
    if len(candidates) == 1:
        return ResolutionResult(status="resolved", resolved=candidates[0])
    return ResolutionResult(status="candidates", candidates=candidates)
