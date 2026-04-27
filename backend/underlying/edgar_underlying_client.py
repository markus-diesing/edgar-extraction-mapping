"""
Underlying Data Module — EDGAR Underlying Client.

Fetches and structures all Tier 1 data for an underlying security from the
SEC EDGAR API.  No LLM calls; no market data.  Data is sourced from:

  * ``data.sec.gov/submissions/CIK{id}.json`` — identity, SIC, FYE, filings
  * ``data.sec.gov/api/xbrl/companyfacts/CIK{id}.json`` — XBRL DEI/us-gaap facts
  * ``www.sec.gov/Archives/edgar/data/…`` — raw 10-K HTML for downstream extraction

Downstream consumers
--------------------
* ``underlying.extractor`` — receives ``annual_filing_text`` for LLM extraction
* ``underlying.background`` — orchestrates fetch + save to DB
* ``underlying.currentness`` — receives ``submissions`` dict for deadline checks
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import config
from ingest.edgar_client import (
    _get,
    SUBMISSIONS_BASE,
    ARCHIVES_BASE,
    strip_html,
    decode_html,
)
from underlying.currentness import compute_currentness, CurrentnessReport
from underlying.utils import detect_reporting_form

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EDGAR API endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Item 1 Business section finder
# ---------------------------------------------------------------------------

# Matches standard 10-K section headings for "ITEM 1  BUSINESS" including
# the AMAT-style split where "Item 1:" and "Business" are on separate lines.
# The pattern is intentionally permissive — the TOC-vs-real-section distinction
# is handled by inspecting the content that immediately follows each match.
_ITEM1_HEADING_RE = re.compile(
    r'ITEM\s+1[\s.:]*(?:\n\s*)?BUSINESS\b',
    re.IGNORECASE,
)

# 20-F filers use "Item 4" (Information on the Company) for the business section.
_ITEM4_HEADING_RE = re.compile(
    r'ITEM\s+4[\s.:]*(?:\n\s*)?INFORMATION\s+ON\s+THE\s+COMPANY\b'
    r'|ITEM\s+4[.:\s]+BUSINESS\s+OVERVIEW\b',
    re.IGNORECASE,
)

# A table-of-contents entry is followed by whitespace + a page number (1–3 digits)
# on the same or next line, with no substantial prose after it.
_TOC_TRAILER_RE = re.compile(r'^[\s.\-]*\d{1,3}\s*$', re.MULTILINE)


def find_item1_window(
    text: str,
    form: str = "10-K",
    context_before: int = config.UNDERLYING_ITEM1_CONTEXT_BEFORE,
    window_after:   int = config.UNDERLYING_ITEM1_WINDOW_CHARS,
) -> tuple[str, bool]:
    """Locate the Item 1 Business section and return a focused text window.

    Searches the *full* stripped filing text (not just the first N chars) so
    that filers with long preambles (forward-looking statements, risk factors)
    before Part I are handled correctly.

    For 20-F filers the search targets "Item 4  Information on the Company"
    instead of "Item 1  Business".

    Returns
    -------
    (window, found)
        *window* is a string of up to ``context_before + window_after`` chars
        centred on the located section header.  If the header cannot be found
        the function falls back to the first ``context_before + window_after``
        characters of *text*.
        *found* is ``True`` when the header was located.
    """
    fallback_chars = context_before + window_after
    if not text:
        return "", False

    heading_re = _ITEM4_HEADING_RE if form in ("20-F", "40-F") else _ITEM1_HEADING_RE

    for m in heading_re.finditer(text):
        # Inspect content immediately following the heading.
        after = text[m.end(): m.end() + 400].strip()

        # Reject TOC entries: the text right after the heading is just a page
        # number (possibly with dot leaders), with no substantive prose.
        if _TOC_TRAILER_RE.match(after[:80]):
            log.debug("Skipping TOC Item 1 entry at pos %d", m.start())
            continue

        # Require at least 40 alpha characters in the next 300 chars to confirm
        # this is the real section body and not another structural artifact.
        alpha_count = sum(1 for c in after[:300] if c.isalpha())
        if alpha_count < 40:
            log.debug(
                "Skipping low-content Item 1 candidate at pos %d (alpha=%d)",
                m.start(), alpha_count,
            )
            continue

        # Real section found — extract window with a little leading context.
        start = max(0, m.start() - context_before)
        end   = m.start() + window_after
        log.debug(
            "Item 1 Business section found at pos %d (form=%s)", m.start(), form
        )
        return text[start:end], True

    # Not found: return the initial fallback window.
    log.debug("Item 1 Business heading not found in text (len=%d, form=%s)", len(text), form)
    return text[:fallback_chars], False

_COMPANYFACTS_BASE = "https://data.sec.gov/api/xbrl/companyfacts"

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class AnnualFilingRef:
    """Reference to the most recent annual or quarterly filing."""
    form: str                 # "10-K" | "20-F" | "10-Q"
    accession: str            # dash-formatted accession number
    period_end: date
    filed: date
    primary_document: str | None = None  # filename from EDGAR submissions API (e.g. "msft-20250630.htm")


@dataclass
class XbrlFact:
    """A single XBRL value extracted from companyfacts."""
    value: int | float
    period_end: date
    form: str                 # "10-K" | "10-Q" | "20-F"


@dataclass
class UnderlyingMetadata:
    """All data fetched from EDGAR for one underlying security.

    This is the canonical intermediate object passed between the EDGAR
    client, the LLM extractor, and the background job that writes to DB.
    """
    # ── Identity ──────────────────────────────────────────────────────────
    cik: str                         # zero-padded 10-digit
    company_name: str
    tickers: list[str] = field(default_factory=list)
    exchanges: list[str] = field(default_factory=list)
    entity_type: str = ""
    adr_flag: bool = False           # True if cover page mentions "American Depositary"

    # ── Regulatory ────────────────────────────────────────────────────────
    category: str = ""               # filer category as returned by EDGAR
    fiscal_year_end: str = "1231"    # MMDD
    reporting_form: str = "10-K"     # "10-K" | "20-F" | "40-F"
    sic_code: str = ""
    sic_description: str = ""
    state_of_incorporation: str = ""

    # ── Most recent annual filing ──────────────────────────────────────────
    last_annual: AnnualFilingRef | None = None

    # ── Most recent quarterly filing (None for 20-F filers) ───────────────
    last_quarterly: AnnualFilingRef | None = None

    # ── Currentness ───────────────────────────────────────────────────────
    currentness: CurrentnessReport | None = None

    # ── XBRL quantitative facts ───────────────────────────────────────────
    shares_outstanding: int | None = None
    shares_outstanding_date: date | None = None
    public_float_usd: float | None = None
    public_float_date: date | None = None

    # ── Raw 10-K text for LLM extraction (Tier 2) ─────────────────────────
    annual_filing_text: str | None = None   # stripped plain text, ≤ MAX_FILING_CHARS

    # ── Error notes (non-fatal; logged per-field) ─────────────────────────
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_metadata(cik_padded: str) -> UnderlyingMetadata:
    """Fetch all Tier 1 EDGAR data for one underlying security.

    Orchestrates: submissions fetch → metadata extraction → XBRL facts →
    filing index + 10-K HTML download.  Failures in XBRL or HTML steps are
    non-fatal (warnings collected; partial result returned).

    Parameters
    ----------
    cik_padded:
        Zero-padded 10-digit CIK string.

    Returns
    -------
    UnderlyingMetadata
        Fully populated where data is available; ``None`` fields indicate
        that data could not be obtained.

    Raises
    ------
    httpx.HTTPStatusError
        If the submissions fetch fails (i.e. CIK not found on EDGAR).
    """
    log.info("Fetching EDGAR metadata for CIK %s", cik_padded)

    # Step 1 — submissions JSON
    submissions = _fetch_submissions(cik_padded)

    # Step 2 — extract structured metadata from submissions
    meta = _extract_from_submissions(submissions, cik_padded)

    # Step 3 — currentness assessment
    try:
        meta.currentness = compute_currentness(submissions)
    except Exception as exc:
        meta.warnings.append(f"Currentness check failed: {exc}")
        log.warning("Currentness check failed for CIK %s: %s", cik_padded, exc)

    # Step 4 — XBRL facts (shares outstanding, public float)
    try:
        _enrich_xbrl(meta, cik_padded)
    except Exception as exc:
        meta.warnings.append(f"XBRL facts unavailable: {exc}")
        log.warning("XBRL fetch failed for CIK %s: %s", cik_padded, exc)

    # Step 5 — download 10-K (or 20-F) HTML for LLM extraction
    if meta.last_annual is not None:
        try:
            meta.annual_filing_text = _download_annual_text(
                cik_padded,
                meta.last_annual.accession,
                meta.last_annual.form,
                primary_document=meta.last_annual.primary_document,
            )
        except Exception as exc:
            meta.warnings.append(f"Annual filing HTML download failed: {exc}")
            log.warning("Annual filing download failed for CIK %s / %s: %s",
                        cik_padded, meta.last_annual.accession, exc)

    return meta


# ---------------------------------------------------------------------------
# Submissions fetch + parsing
# ---------------------------------------------------------------------------

def _fetch_submissions(cik_padded: str) -> dict[str, Any]:
    """Fetch the EDGAR submissions JSON for a CIK."""
    url = f"{SUBMISSIONS_BASE}/CIK{cik_padded}.json"
    resp = _get(url)
    resp.raise_for_status()
    return resp.json()


def _extract_from_submissions(data: dict[str, Any], cik_padded: str) -> UnderlyingMetadata:
    """Parse a submissions dict into an :class:`UnderlyingMetadata` object."""
    warnings: list[str] = []

    recent = data.get("filings", {}).get("recent", {})
    forms: list[str]        = recent.get("form", [])
    filed_dates: list[str]  = recent.get("filingDate", [])
    report_dates: list[str] = recent.get("reportDate", [])
    accessions: list[str]   = recent.get("accessionNumber", [])
    # primaryDocument is available from the EDGAR submissions API and provides
    # the exact filename of the primary HTML document for each filing — this
    # lets us bypass the unreliable -index.json fetch entirely.
    primary_docs: list[str] = recent.get("primaryDocument", [])

    # Reporting form
    reporting_form = _detect_reporting_form(forms)

    # Most recent annual filing
    annual_form = "20-F" if reporting_form == "20-F" else "10-K"
    last_annual = _find_most_recent_filing(
        forms, accessions, filed_dates, report_dates, annual_form,
        primary_docs=primary_docs,
    )

    # Most recent quarterly filing (not applicable for 20-F filers)
    last_quarterly: AnnualFilingRef | None = None
    if reporting_form != "20-F":
        last_quarterly = _find_most_recent_filing(
            forms, accessions, filed_dates, report_dates, "10-Q",
            primary_docs=primary_docs,
        )

    return UnderlyingMetadata(
        cik=cik_padded,
        company_name=str(data.get("name", "")),
        tickers=list(data.get("tickers", [])),
        exchanges=list(data.get("exchanges", [])),
        entity_type=str(data.get("entityType", "")),
        category=str(data.get("category", "")),
        fiscal_year_end=str(data.get("fiscalYearEnd") or "1231"),
        reporting_form=reporting_form,
        sic_code=str(data.get("sic", "")),
        sic_description=str(data.get("sicDescription", "")),
        state_of_incorporation=str(data.get("stateOfIncorporation", "")),
        last_annual=last_annual,
        last_quarterly=last_quarterly,
        warnings=warnings,
    )


def _detect_reporting_form(forms: list[str]) -> str:
    """Infer the primary reporting form from the filing history (first 30 entries).

    Delegates to :func:`underlying.utils.detect_reporting_form` — the canonical
    implementation shared with ``currentness.py``.
    """
    return detect_reporting_form(forms)


def _find_most_recent_filing(
    forms: list[str],
    accessions: list[str],
    filed_dates: list[str],
    report_dates: list[str],
    target_form: str,
    *,
    primary_docs: list[str] | None = None,
) -> AnnualFilingRef | None:
    """Return a reference to the most recent filing of *target_form*.

    Prefers the exact form over ``/A`` amendments.  Returns the first
    (most recent) match in the ``recent`` array (EDGAR returns newest-first).

    Parameters
    ----------
    primary_docs:
        Optional list of primary document filenames from the EDGAR submissions
        ``recent.primaryDocument`` array.  When provided, the matched entry is
        stored on :attr:`AnnualFilingRef.primary_document` so that
        :func:`_download_annual_text` can build the direct HTML URL without
        fetching the filing index.
    """
    for i, form in enumerate(forms):
        if form not in (target_form, f"{target_form}/A"):
            continue
        try:
            filed = date.fromisoformat(filed_dates[i])
        except (ValueError, IndexError):
            continue
        period_raw = report_dates[i] if i < len(report_dates) else ""
        try:
            period = date.fromisoformat(period_raw)
        except ValueError:
            period = filed   # fallback: use filing date

        accession = accessions[i] if i < len(accessions) else ""
        # Normalise accession: EDGAR sometimes returns without dashes
        accession = _normalise_accession(accession)
        primary_document = (
            primary_docs[i] if primary_docs and i < len(primary_docs) else None
        )
        return AnnualFilingRef(
            form=target_form,
            accession=accession,
            period_end=period,
            filed=filed,
            primary_document=primary_document or None,
        )
    return None


def _normalise_accession(raw: str) -> str:
    """Ensure accession number is in 18-digit dash format (XXXXXXXXXX-YY-ZZZZZZ)."""
    clean = raw.replace("-", "")
    if len(clean) == 18:
        return f"{clean[:10]}-{clean[10:12]}-{clean[12:]}"
    return raw   # can't parse — return as-is


# ---------------------------------------------------------------------------
# XBRL companyfacts enrichment
# ---------------------------------------------------------------------------

# DEI concept names for shares outstanding and public float
_SHARES_CONCEPTS = [
    ("dei", "EntityCommonStockSharesOutstanding"),
    ("us-gaap", "CommonStockSharesOutstanding"),
]
_FLOAT_CONCEPTS = [
    ("dei", "EntityPublicFloat"),
]


def _enrich_xbrl(meta: UnderlyingMetadata, cik_padded: str) -> None:
    """Fetch XBRL companyfacts and update *meta* with shares + float data in place."""
    facts = _fetch_companyfacts(cik_padded)
    if not facts:
        return

    # Shares outstanding
    for namespace, concept in _SHARES_CONCEPTS:
        fact = _latest_xbrl_fact(facts, namespace, concept, units="shares")
        if fact is not None:
            meta.shares_outstanding = int(fact.value)
            meta.shares_outstanding_date = fact.period_end
            break

    # Public float (reported in USD)
    for namespace, concept in _FLOAT_CONCEPTS:
        fact = _latest_xbrl_fact(facts, namespace, concept, units="USD")
        if fact is not None:
            meta.public_float_usd = float(fact.value)
            meta.public_float_date = fact.period_end
            break


def _fetch_companyfacts(cik_padded: str) -> dict[str, Any] | None:
    """Fetch the XBRL companyfacts JSON.  Returns None on failure."""
    url = f"{_COMPANYFACTS_BASE}/CIK{cik_padded}.json"
    try:
        resp = _get(url)
        resp.raise_for_status()
        return resp.json().get("facts", {})
    except Exception as exc:
        log.debug("companyfacts not available for CIK %s: %s", cik_padded, exc)
        return None


def _latest_xbrl_fact(
    facts: dict[str, Any],
    namespace: str,
    concept: str,
    units: str,
) -> XbrlFact | None:
    """Extract the most recent value for a DEI/us-gaap concept.

    Prefers FY annual (10-K / 20-F) values over interim.  Ties broken by
    ``end`` date descending.

    Returns None if the concept is not available.
    """
    ns_data = facts.get(namespace, {})
    concept_data = ns_data.get(concept, {})
    unit_entries: list[dict[str, Any]] = concept_data.get("units", {}).get(units, [])

    if not unit_entries:
        return None

    # Prefer FY annual forms; fall back to any form
    preferred: list[dict[str, Any]] = [
        e for e in unit_entries if e.get("form") in ("10-K", "20-F", "40-F")
    ]
    candidates = preferred if preferred else unit_entries

    # Sort by period end date, newest first
    def _sort_key(e: dict[str, Any]) -> str:
        return e.get("end", "") or ""

    candidates_sorted = sorted(candidates, key=_sort_key, reverse=True)

    for entry in candidates_sorted:
        end_str = entry.get("end", "")
        val = entry.get("val")
        if val is None or not end_str:
            continue
        try:
            period_end = date.fromisoformat(end_str)
        except ValueError:
            continue
        return XbrlFact(
            value=val,
            period_end=period_end,
            form=str(entry.get("form", "")),
        )

    return None


# ---------------------------------------------------------------------------
# 10-K HTML download + text extraction
# ---------------------------------------------------------------------------

def _download_annual_text(
    cik_padded: str,
    accession: str,
    form: str,
    *,
    primary_document: str | None = None,
) -> str | None:
    """Download the primary HTML document of a 10-K/20-F and return stripped text.

    When *primary_document* is supplied (filename from the EDGAR submissions
    ``recent.primaryDocument`` array, e.g. ``"msft-20250630.htm"``), the
    direct archive URL is constructed and the filing index is **not** fetched.
    This bypasses the ``-index.json`` endpoint which returns HTTP 404 for many
    filings.  When *primary_document* is ``None`` the legacy index-JSON lookup
    is attempted as a fallback.

    Returns None if no HTML document can be found.
    Text is truncated at ``config.MAX_FILING_CHARS`` characters.
    """
    log.info("Downloading annual filing HTML: CIK=%s acc=%s", cik_padded, accession)

    cik_numeric = str(int(cik_padded))   # strip leading zeros for URL
    acc_nodash = accession.replace("-", "")

    if primary_document:
        # Fast path: construct direct URL from submissions API metadata.
        html_url: str | None = (
            f"{ARCHIVES_BASE}/{cik_numeric}/{acc_nodash}/{primary_document}"
        )
        log.debug("Using primaryDocument direct URL: %s", html_url)
    else:
        # Fallback: fetch the filing index JSON and locate the primary HTML.
        index_url = (
            f"{ARCHIVES_BASE}/{cik_numeric}/{acc_nodash}/{accession}-index.json"
        )
        try:
            resp = _get(index_url)
            resp.raise_for_status()
            index = resp.json()
        except Exception as exc:
            log.warning("Filing index unavailable (%s): %s", index_url, exc)
            return None

        html_url = _find_primary_html_url(index, cik_numeric, acc_nodash, form)
        if not html_url:
            log.info("No primary HTML document found for %s / %s", cik_padded, accession)
            return None

    # Download and decode HTML
    try:
        resp2 = _get(html_url)
        resp2.raise_for_status()
        html = decode_html(resp2.content)
    except Exception as exc:
        log.warning("HTML download failed (%s): %s", html_url, exc)
        return None

    text = strip_html(html)
    if len(text) > config.MAX_FILING_CHARS:
        text = text[: config.MAX_FILING_CHARS]
        log.debug("Truncated annual filing text to %d chars", config.MAX_FILING_CHARS)

    return text


def _find_primary_html_url(
    index: dict[str, Any],
    cik_numeric: str,
    acc_nodash: str,
    form: str,
) -> str | None:
    """Identify the primary HTML document URL from a filing index JSON.

    The EDGAR index JSON has a ``files`` list with ``name`` and ``type``
    (document type).  We prefer a document explicitly typed with the target
    form, then fall back to any ``.htm`` file.
    """
    files: list[dict[str, Any]] = index.get("files", [])
    base_url = f"{ARCHIVES_BASE}/{cik_numeric}/{acc_nodash}/"

    def _abs(name: str) -> str:
        return f"{base_url}{name}"

    # Priority 1: file typed as the form itself (e.g. "10-K")
    for doc in files:
        name = doc.get("name", "")
        dtype = (doc.get("type", "") or "").upper()
        if dtype == form.upper() and name.lower().endswith((".htm", ".html")):
            return _abs(name)

    # Priority 2: file with form name in file name
    form_slug = form.lower().replace("-", "")
    for doc in files:
        name = (doc.get("name", "") or "").lower()
        if form_slug in name and name.endswith((".htm", ".html")):
            return _abs(doc["name"])

    # Priority 3: first .htm file (not the index itself)
    for doc in files:
        name = (doc.get("name", "") or "").lower()
        if name.endswith((".htm", ".html")) and "index" not in name:
            return _abs(doc["name"])

    return None


# ---------------------------------------------------------------------------
# ADR detection helper (used by background.py after text extraction)
# ---------------------------------------------------------------------------

_ADR_PATTERNS = re.compile(
    r"\bamerican\s+depositary\s+(share|receipt|unit|interest)\b",
    re.IGNORECASE,
)

# Characters of filing text examined by the regex ADR fallback.
# The cover page (where the security description lives) is typically within
# the first 3 000 characters of the stripped text.  Limiting scope reduces
# false positives from boilerplate legal disclaimers later in the document.
_ADR_SCAN_CHARS = 3_000


def detect_adr(text: str) -> bool:
    """Return True if the *cover-page* portion of *text* mentions ADR/ADS.

    Only the first :data:`_ADR_SCAN_CHARS` characters are examined so that
    boilerplate legal text later in the filing does not produce false positives.
    The LLM extraction result always takes priority over this regex fallback;
    this function is only called when LLM extraction is unavailable.
    """
    return bool(_ADR_PATTERNS.search((text or "")[:_ADR_SCAN_CHARS]))
