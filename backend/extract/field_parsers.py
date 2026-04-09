"""
field_parsers.py — Typed value parsers for programmatic extraction.

Each parser takes the raw label-cell text from an HTML table and returns
a Python value ready for JSON serialisation into PRISM field_results.

Parsers return None when the input is clearly unparseable, allowing the
caller to fall back to the LLM result instead.

Parser registry:
    FIELD_PARSERS: dict[str, Callable[[str], Any]]
        Maps PRISM field path → parser function.
        Paths containing [*] wildcards (array fields) are matched by
        label_mapper using a prefix-aware lookup.
"""
from __future__ import annotations

import calendar
import re
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Module-level constants — built once, not per-call
# ---------------------------------------------------------------------------

# Maps lowercase month name / abbreviation → 1-based month number.
# Built once at import time; calendar.month_name[0] is '' (empty), skipped.
_MONTH_NAMES: dict[str, int] = {
    name.lower(): i for i, name in enumerate(calendar.month_name) if name
}
_MONTH_NAMES.update(
    {name.lower(): i for i, name in enumerate(calendar.month_abbr) if name}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_footnotes(text: str) -> str:
    """Remove common footnote markers: *, †, ‡, (1), (2), superscripts."""
    text = re.sub(r"[\*†‡§¶]", "", text)
    text = re.sub(r"\s*\(\d+\)", "", text)        # (1), (2) ...
    text = re.sub(r"\s*\[\d+\]", "", text)        # [1], [2] ...
    return text.strip()


def _numeric(text: str) -> float | None:
    """Parse a numeric string, stripping currency symbols and commas."""
    text = re.sub(r"[,$£€¥\s]", "", text)
    # Remove trailing % if present — caller handles percent conversion
    text = text.rstrip("%")
    try:
        return float(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Individual parsers
# ---------------------------------------------------------------------------

def parse_text(raw: str) -> str | None:
    """Return the raw value stripped of footnote markers and whitespace."""
    cleaned = _strip_footnotes(raw.strip())
    return cleaned if cleaned else None


def parse_date(raw: str) -> str | None:
    """
    Parse a date string and return ISO format YYYY-MM-DD.

    Handles:
      "March 21, 2029"      → "2029-03-21"
      "March 21, 2029*"     → "2029-03-21"  (footnote stripped)
      "2029-03-21"          → "2029-03-21"  (already ISO)
      "on or about March 21, 2029"  → "2029-03-21"
      "expected to be March 21, 2029"  → "2029-03-21"
    """
    raw = _strip_footnotes(raw.strip())
    # Already ISO
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    # Attempt "Month DD, YYYY" or "Month D, YYYY" using module-level month map
    pattern = re.search(
        r"\b([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})\b",
        raw,
    )
    if pattern:
        month_str, day_str, year_str = pattern.groups()
        month = _MONTH_NAMES.get(month_str.lower())
        if month:
            return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"
    # MM/DD/YYYY or DD/MM/YYYY — ambiguous without locale, skip
    iso_m = re.search(r"\b(\d{4})[/\-](\d{2})[/\-](\d{2})\b", raw)
    if iso_m:
        return f"{iso_m.group(1)}-{iso_m.group(2)}-{iso_m.group(3)}"
    return None


def parse_percentage(raw: str) -> float | None:
    """
    Parse a percentage value and return a decimal (e.g. 70% → 0.70).

    Handles:
      "70%"                                                   → 0.70
      "70.00%"                                                → 0.70
      "70.00% of Initial Underlier Value"                     → 0.70
      "70% of the Initial Level"                              → 0.70
      "1,949.187, 80.00% of its Initial Level"                → 0.80
      "$5,350.77 (80.00% of its Initial Level)"               → 0.80
      "$8.75 per $1,000 ... 10.50% per annum or 0.875% per month" → 0.1050

    Priority order:
      1. A percentage explicitly qualified with "per annum", "p.a.", "per year",
         or "annually" — always preferred (annual rate wins over monthly rate).
      2. Among remaining percentages, non-monthly figures are preferred over
         those qualified as "per month" / "monthly".
      3. Fall back to the last percentage found (existing behaviour, preserves
         barrier / call-level parsing which never has annum/month qualifiers).
    """
    def _to_decimal(raw_num: str) -> float | None:
        try:
            pct = float(raw_num.replace(",", ""))
        except ValueError:
            return None
        return round(pct / 100.0, 6) if pct > 1.0 else round(pct, 6)

    # Priority 1: per-annum qualified percentage
    pa_match = re.search(
        r"([\d,]+\.?\d*)\s*%\s*(?:per\s+annum|p\.a\.|per\s+year|annually)\b",
        raw, re.IGNORECASE,
    )
    if pa_match:
        result = _to_decimal(pa_match.group(1))
        if result is not None:
            return result

    # Collect all percentage occurrences; tag each as monthly or not
    # Regex: capture the number, then optionally a "per month" / "monthly" qualifier
    candidates: list[tuple[str, bool]] = []   # (raw_number, is_monthly)
    for m in re.finditer(
        r"([\d,]+\.?\d*)\s*%(\s*(?:per\s+month|monthly)\b)?",
        raw, re.IGNORECASE,
    ):
        is_monthly = bool(m.group(2))
        candidates.append((m.group(1), is_monthly))

    if not candidates:
        return None

    # Priority 2: prefer non-monthly figures when both kinds are present
    non_monthly = [num for num, monthly in candidates if not monthly]
    pool = non_monthly if non_monthly else [num for num, _ in candidates]

    # Take the last from the preferred pool (existing "last match" convention)
    return _to_decimal(pool[-1])


def parse_amount(raw: str) -> float | None:
    """
    Parse a monetary amount and return a number (strip $ and commas).

    Handles:
      "$1,372,000.00"  → 1372000.0
      "$1,000 per note" → 1000.0   (takes the first number)
      "1,372,000"      → 1372000.0
      "US$ 2,000,000"  → 2000000.0
    """
    raw = re.sub(r"[US$£€¥]", "", raw)
    # Take only the first numeric token (ignores "per note" suffix etc.)
    m = re.search(r"[\d,]+\.?\d*", raw)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def parse_number(raw: str) -> float | None:
    """
    Parse a plain numeric value (index level, initial value, etc.).

    Handles:
      "5,350.77"   → 5350.77
      "19,324.56"  → 19324.56
      "$150.00"    → 150.0
    """
    raw = re.sub(r"[,$£€¥]", "", raw.strip())
    m = re.search(r"[\d,]+\.?\d*", raw)
    if not m:
        return None
    try:
        return float(m.group().replace(",", ""))
    except ValueError:
        return None


def parse_cusip(raw: str) -> str | None:
    """
    Extract a CUSIP (9-character alphanumeric) from a cell.

    Handles:
      "06749FWA3"
      "06749FWA3 / US06749FWA31"   (combined CUSIP/ISIN cell)
    """
    raw = _strip_footnotes(raw.strip())
    m = re.search(r"\b([A-Z0-9]{9})\b", raw)
    return m.group(1) if m else None


def parse_isin(raw: str) -> str | None:
    """
    Extract an ISIN (12-character: 2-letter country code + 10 alphanumeric).

    Handles:
      "US06749FWA31"
      "06749FWA3 / US06749FWA31"   (combined CUSIP/ISIN cell)
    """
    raw = _strip_footnotes(raw.strip())
    m = re.search(r"\b([A-Z]{2}[A-Z0-9]{10})\b", raw)
    return m.group(1) if m else None


def parse_currency(raw: str) -> str | None:
    """
    Return ISO 4217 currency code.

    Handles:
      "USD", "U.S. dollars", "US dollars", "USD (United States Dollars)"
    """
    raw = raw.strip().upper()
    # Direct ISO code
    m = re.search(r"\b(USD|EUR|GBP|JPY|CHF|CAD|AUD|NZD|HKD|SGD|NOK|SEK|DKK)\b", raw)
    if m:
        return m.group(1)
    # Plain text aliases
    if "U.S. DOLLAR" in raw or "US DOLLAR" in raw or "UNITED STATES DOLLAR" in raw:
        return "USD"
    return None


def parse_frequency(raw: str) -> dict | None:
    """
    Map a frequency description to a PRISM discriminated-union object.

    Returns {"$type": "<value>"} matching the PRISM Frequency oneOf schema.

    Handles:
      "monthly", "per month", "each month"  → {"$type": "monthly"}
      "quarterly", "per quarter"             → {"$type": "quarterly"}
      "semi-annual", "semi-annually"         → {"$type": "semiAnnually"}
      "annual", "annually", "per year"       → {"$type": "annually"}
    """
    raw_lower = raw.lower().strip()
    if any(k in raw_lower for k in ("monthly", "per month", "each month", "month")):
        return {"$type": "monthly"}
    if any(k in raw_lower for k in ("quarterly", "per quarter", "each quarter")):
        return {"$type": "quarterly"}
    if any(k in raw_lower for k in ("semi-annual", "semiannual", "semi annual", "every six")):
        return {"$type": "semiAnnually"}
    if any(k in raw_lower for k in ("annual", "per year", "each year", "yearly")):
        return {"$type": "annually"}
    if any(k in raw_lower for k in ("weekly", "per week", "each week")):
        return {"$type": "weekly"}
    if any(k in raw_lower for k in ("daily", "per day", "each day")):
        return {"$type": "daily"}
    return None


def parse_observation_type(raw: str) -> str | None:
    """
    Map barrier observation type to PRISM enum.

    Handles:
      "European", "observed at maturity"     → "european"
      "American", "daily monitoring"         → "american"
      "periodic", "on each Observation Date" → "periodic"
    """
    raw_lower = raw.lower()
    if "european" in raw_lower or "at maturity" in raw_lower or "final" in raw_lower:
        return "european"
    if "american" in raw_lower or "daily" in raw_lower or "continuous" in raw_lower:
        return "american"
    if "periodic" in raw_lower or "observation date" in raw_lower:
        return "periodic"
    return None


# ---------------------------------------------------------------------------
# Parser registry — maps PRISM field path → parser function
#
# For array paths containing [*] (e.g. underlyingTerms.underlyingAssets[*].name),
# label_mapper.py uses prefix matching: strip everything after [*] and match.
# ---------------------------------------------------------------------------

FIELD_PARSERS: dict[str, Callable[[str], Any]] = {
    # Identifiers
    "identifiers.cusip":                                    parse_cusip,
    "identifiers.isin":                                     parse_isin,

    # Dates
    "structuredProductsGeneral.maturityDate":               parse_date,
    "structuredProductsGeneral.tradeDate":                  parse_date,
    "structuredProductsGeneral.issueDate":                  parse_date,
    "structuredProductsGeneral.valuationDate":              parse_date,

    # Notional / denomination
    "structuredProductsGeneral.notional":                   parse_amount,
    "structuredProductsGeneral.currency":                   parse_currency,
    "product.denomination":                                 parse_amount,

    # Term
    "structuredProductsGeneral.term":                       parse_text,

    # Coupon
    "coupon.rate":                                          parse_percentage,
    "coupon.barrierLevel":                                  parse_percentage,
    "coupon.frequency":                                     parse_frequency,

    # Barrier
    "barrier.triggerDetails.triggerLevel":                  parse_percentage,
    "barrier.triggerDetails.observationType":               parse_observation_type,

    # Autocall
    "autocall.callLevel":                                   parse_percentage,

    # Underlying assets (array — matched by prefix in label_mapper)
    "underlyingTerms.underlyingAssets[*].name":             parse_text,
    "underlyingTerms.underlyingAssets[*].initialLevel":     parse_number,
    "underlyingTerms.underlyingAssets[*].finalLevel":       parse_number,
    "underlyingTerms.underlyingAssets[*].bloombergTicker":  parse_text,

    # Parties
    "parties.issuer.name":                                  parse_text,
    "parties.guarantor.name":                               parse_text,
    "parties.calculationAgent.name":                        parse_text,
}
