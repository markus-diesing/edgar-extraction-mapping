"""
tests/test_edgar_underlying_client.py — Unit tests for underlying/edgar_underlying_client.py

All network calls are mocked.  The tests verify data extraction logic, XBRL
fact parsing, HTML URL resolution, and ADR detection.  No DB, no filesystem.
"""
from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from ingest.edgar_client import _get as edgar_get
from underlying.edgar_underlying_client import (
    UnderlyingMetadata,
    AnnualFilingRef,
    XbrlFact,
    fetch_metadata,
    _extract_from_submissions,
    _find_most_recent_filing,
    _normalise_accession,
    _detect_reporting_form,
    _latest_xbrl_fact,
    _find_primary_html_url,
    _download_annual_text,
    detect_adr,
    _ADR_SCAN_CHARS,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_submissions(
    cik: str = "789019",
    name: str = "MICROSOFT CORP",
    tickers: list[str] | None = None,
    exchanges: list[str] | None = None,
    category: str = "large accelerated filer",
    sic: str = "7372",
    sic_desc: str = "Prepackaged Software",
    state: str = "WA",
    fye: str = "0630",
    forms: list[str] | None = None,
    filing_dates: list[str] | None = None,
    report_dates: list[str] | None = None,
    accessions: list[str] | None = None,
    primary_docs: list[str] | None = None,
) -> dict[str, Any]:
    recent: dict[str, Any] = {
        "form": forms or [],
        "filingDate": filing_dates or [],
        "reportDate": report_dates or [],
        "accessionNumber": accessions or [],
    }
    if primary_docs is not None:
        recent["primaryDocument"] = primary_docs
    return {
        "cik": cik,
        "name": name,
        "tickers": tickers if tickers is not None else ["MSFT"],
        "exchanges": exchanges if exchanges is not None else ["Nasdaq"],
        "entityType": "operating",
        "category": category,
        "fiscalYearEnd": fye,
        "sic": sic,
        "sicDescription": sic_desc,
        "stateOfIncorporation": state,
        "filings": {"recent": recent},
    }


def _make_companyfacts(
    *,
    shares: int | None = 7_500_000_000,
    shares_end: str = "2025-06-30",
    float_usd: float | None = 2_800_000_000_000.0,
    float_end: str = "2025-06-30",
) -> dict[str, Any]:
    facts: dict[str, Any] = {"dei": {}, "us-gaap": {}}
    if shares is not None:
        facts["dei"]["EntityCommonStockSharesOutstanding"] = {
            "units": {
                "shares": [
                    {"end": shares_end, "val": shares, "form": "10-K", "filed": "2025-07-30"},
                    {"end": "2024-06-30", "val": shares + 100_000_000, "form": "10-K", "filed": "2024-07-29"},
                ]
            }
        }
    if float_usd is not None:
        facts["dei"]["EntityPublicFloat"] = {
            "units": {
                "USD": [
                    {"end": float_end, "val": float_usd, "form": "10-K", "filed": "2025-07-30"},
                ]
            }
        }
    return facts


# ---------------------------------------------------------------------------
# _normalise_accession
# ---------------------------------------------------------------------------

class TestNormaliseAccession:
    def test_already_formatted(self):
        assert _normalise_accession("0000950170-25-100235") == "0000950170-25-100235"

    def test_without_dashes(self):
        assert _normalise_accession("000095017025100235") == "0000950170-25-100235"

    def test_short_unknown_passthrough(self):
        raw = "12345"
        assert _normalise_accession(raw) == raw


# ---------------------------------------------------------------------------
# _detect_reporting_form
# ---------------------------------------------------------------------------

class TestDetectReportingForm:
    def test_10k_default(self):
        assert _detect_reporting_form(["10-K", "10-Q", "8-K"]) == "10-K"

    def test_20f_detected(self):
        assert _detect_reporting_form(["20-F", "6-K"]) == "20-F"

    def test_40f_detected(self):
        assert _detect_reporting_form(["40-F"]) == "40-F"

    def test_20f_wins_over_40f_by_order(self):
        assert _detect_reporting_form(["20-F", "40-F"]) == "20-F"

    def test_empty_defaults_to_10k(self):
        assert _detect_reporting_form([]) == "10-K"

    def test_only_checks_first_30(self):
        # If 20-F only appears at position 31, it should not be detected
        forms = ["10-K"] * 30 + ["20-F"]
        assert _detect_reporting_form(forms) == "10-K"


# ---------------------------------------------------------------------------
# _find_most_recent_filing
# ---------------------------------------------------------------------------

class TestFindMostRecentFiling:
    def test_finds_latest_10k(self):
        forms        = ["10-K", "10-Q", "10-K"]
        accessions   = ["0000111111-25-001", "0000111111-25-002", "0000111111-24-001"]
        filed_dates  = ["2025-07-30", "2025-02-14", "2024-07-29"]
        report_dates = ["2025-06-30", "2024-12-31", "2024-06-30"]

        ref = _find_most_recent_filing(forms, accessions, filed_dates, report_dates, "10-K")
        assert ref is not None
        assert ref.period_end == date(2025, 6, 30)
        assert ref.filed == date(2025, 7, 30)

    def test_finds_latest_10q(self):
        forms        = ["10-K", "10-Q", "10-Q"]
        accessions   = ["A", "B", "C"]
        filed_dates  = ["2025-07-30", "2025-05-08", "2025-02-14"]
        report_dates = ["2025-06-30", "2025-03-31", "2024-12-31"]

        ref = _find_most_recent_filing(forms, accessions, filed_dates, report_dates, "10-Q")
        assert ref is not None
        assert ref.period_end == date(2025, 3, 31)

    def test_accepts_amended_form(self):
        forms        = ["10-K/A"]
        accessions   = ["A"]
        filed_dates  = ["2025-08-01"]
        report_dates = ["2025-06-30"]

        ref = _find_most_recent_filing(forms, accessions, filed_dates, report_dates, "10-K")
        assert ref is not None
        assert ref.form == "10-K"

    def test_returns_none_when_not_found(self):
        ref = _find_most_recent_filing(["10-Q"], ["A"], ["2025-05-01"], ["2025-03-31"], "10-K")
        assert ref is None

    def test_accession_normalised(self):
        forms        = ["10-K"]
        accessions   = ["000095017025100235"]   # no dashes
        filed_dates  = ["2025-07-30"]
        report_dates = ["2025-06-30"]

        ref = _find_most_recent_filing(forms, accessions, filed_dates, report_dates, "10-K")
        assert ref is not None
        assert ref.accession == "0000950170-25-100235"

    def test_primary_document_stored(self):
        """primary_docs kwarg is captured on the returned AnnualFilingRef."""
        forms        = ["10-K"]
        accessions   = ["0000111111-25-001"]
        filed_dates  = ["2025-07-30"]
        report_dates = ["2025-06-30"]
        primary_docs = ["msft-20250630.htm"]

        ref = _find_most_recent_filing(
            forms, accessions, filed_dates, report_dates, "10-K",
            primary_docs=primary_docs,
        )
        assert ref is not None
        assert ref.primary_document == "msft-20250630.htm"

    def test_primary_document_none_when_not_provided(self):
        """Existing call-sites without primary_docs get None."""
        forms        = ["10-K"]
        accessions   = ["0000111111-25-001"]
        filed_dates  = ["2025-07-30"]
        report_dates = ["2025-06-30"]

        ref = _find_most_recent_filing(forms, accessions, filed_dates, report_dates, "10-K")
        assert ref is not None
        assert ref.primary_document is None

    def test_primary_document_empty_string_treated_as_none(self):
        """An empty string in primary_docs is coerced to None (falsy guard)."""
        forms        = ["10-K"]
        accessions   = ["0000111111-25-001"]
        filed_dates  = ["2025-07-30"]
        report_dates = ["2025-06-30"]
        primary_docs = [""]          # EDGAR may return empty string

        ref = _find_most_recent_filing(
            forms, accessions, filed_dates, report_dates, "10-K",
            primary_docs=primary_docs,
        )
        assert ref is not None
        assert ref.primary_document is None


# ---------------------------------------------------------------------------
# _extract_from_submissions
# ---------------------------------------------------------------------------

class TestExtractFromSubmissions:
    def test_basic_fields(self):
        subs = _make_submissions()
        meta = _extract_from_submissions(subs, "0000789019")
        assert meta.company_name == "MICROSOFT CORP"
        assert meta.cik == "0000789019"
        assert meta.tickers == ["MSFT"]
        assert meta.sic_code == "7372"
        assert meta.sic_description == "Prepackaged Software"
        assert meta.state_of_incorporation == "WA"
        assert meta.fiscal_year_end == "0630"
        assert meta.category == "large accelerated filer"

    def test_20f_filer_no_quarterly(self):
        subs = _make_submissions(
            forms=["20-F"], filing_dates=["2025-04-25"], report_dates=["2024-12-31"],
            accessions=["0000111111-25-001"],
        )
        meta = _extract_from_submissions(subs, "0000123456")
        assert meta.reporting_form == "20-F"
        assert meta.last_annual is not None
        assert meta.last_annual.form == "20-F"
        assert meta.last_quarterly is None   # no 10-Q for 20-F filers

    def test_no_filings_returns_none_refs(self):
        subs = _make_submissions()
        meta = _extract_from_submissions(subs, "0000789019")
        assert meta.last_annual is None
        assert meta.last_quarterly is None

    def test_fye_fallback_to_1231(self):
        subs = _make_submissions(fye="")
        subs["fiscalYearEnd"] = None
        meta = _extract_from_submissions(subs, "0000789019")
        assert meta.fiscal_year_end == "1231"

    def test_multiple_tickers(self):
        subs = _make_submissions(
            tickers=["GOOGL", "GOOG"], exchanges=["Nasdaq", "Nasdaq"]
        )
        meta = _extract_from_submissions(subs, "0001652044")
        assert "GOOGL" in meta.tickers
        assert "GOOG" in meta.tickers

    def test_primary_document_propagated_to_annual_ref(self):
        """primaryDocument array in submissions API is captured on last_annual."""
        subs = _make_submissions(
            forms=["10-K", "10-Q"],
            filing_dates=["2025-07-30", "2025-05-08"],
            report_dates=["2025-06-30", "2025-03-31"],
            accessions=["0000111111-25-001", "0000111111-25-002"],
            primary_docs=["msft-20250630.htm", "msft-20250331.htm"],
        )
        meta = _extract_from_submissions(subs, "0000789019")
        assert meta.last_annual is not None
        assert meta.last_annual.primary_document == "msft-20250630.htm"

    def test_primary_document_absent_when_not_in_submissions(self):
        """Submissions without primaryDocument still work — field defaults to None."""
        subs = _make_submissions(
            forms=["10-K"],
            filing_dates=["2025-07-30"],
            report_dates=["2025-06-30"],
            accessions=["0000111111-25-001"],
            # primary_docs not passed → not present in submissions dict
        )
        meta = _extract_from_submissions(subs, "0000789019")
        assert meta.last_annual is not None
        assert meta.last_annual.primary_document is None


# ---------------------------------------------------------------------------
# _latest_xbrl_fact
# ---------------------------------------------------------------------------

class TestLatestXbrlFact:
    def _facts(self) -> dict[str, Any]:
        return _make_companyfacts()

    def test_shares_latest_value(self):
        facts = self._facts()
        result = _latest_xbrl_fact(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
        assert result is not None
        assert result.value == 7_500_000_000
        assert result.period_end == date(2025, 6, 30)

    def test_public_float(self):
        facts = self._facts()
        result = _latest_xbrl_fact(facts, "dei", "EntityPublicFloat", "USD")
        assert result is not None
        assert result.value == 2_800_000_000_000.0

    def test_missing_concept_returns_none(self):
        facts: dict[str, Any] = {}
        result = _latest_xbrl_fact(facts, "dei", "NonExistentConcept", "shares")
        assert result is None

    def test_prefers_fy_over_interim(self):
        """FY annual (10-K) values preferred over interim (10-Q) even if older."""
        facts: dict[str, Any] = {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2025-09-30", "val": 8_000_000_000, "form": "10-Q", "filed": "2025-10-01"},
                            {"end": "2025-06-30", "val": 7_500_000_000, "form": "10-K", "filed": "2025-07-30"},
                        ]
                    }
                }
            }
        }
        result = _latest_xbrl_fact(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
        # Should pick the FY annual (10-K) value, the most recent one: 2025-06-30
        assert result is not None
        assert result.form == "10-K"
        assert result.value == 7_500_000_000

    def test_fallback_to_interim_if_no_annual(self):
        facts: dict[str, Any] = {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2025-09-30", "val": 8_000_000_000, "form": "10-Q", "filed": "2025-10-01"},
                        ]
                    }
                }
            }
        }
        result = _latest_xbrl_fact(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
        assert result is not None
        assert result.form == "10-Q"

    def test_skips_entries_missing_val(self):
        facts: dict[str, Any] = {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {"end": "2025-06-30", "val": None, "form": "10-K"},
                            {"end": "2024-06-30", "val": 7_500_000_000, "form": "10-K"},
                        ]
                    }
                }
            }
        }
        result = _latest_xbrl_fact(facts, "dei", "EntityCommonStockSharesOutstanding", "shares")
        assert result is not None
        assert result.period_end == date(2024, 6, 30)


# ---------------------------------------------------------------------------
# _find_primary_html_url
# ---------------------------------------------------------------------------

class TestFindPrimaryHtmlUrl:
    def test_prefers_typed_form(self):
        index = {
            "files": [
                {"name": "other.htm",  "type": "EX-31.1"},
                {"name": "form10k.htm", "type": "10-K"},
            ]
        }
        url = _find_primary_html_url(index, "789019", "000095017025100235", "10-K")
        assert url is not None
        assert "form10k.htm" in url

    def test_falls_back_to_name_match(self):
        index = {
            "files": [
                {"name": "exhibit.htm", "type": "EX-31.1"},
                {"name": "msft10k.htm", "type": ""},
            ]
        }
        url = _find_primary_html_url(index, "789019", "000095017025100235", "10-K")
        assert url is not None
        assert "msft10k.htm" in url

    def test_falls_back_to_first_htm(self):
        index = {
            "files": [
                {"name": "report.htm", "type": ""},
            ]
        }
        url = _find_primary_html_url(index, "789019", "000095017025100235", "10-K")
        assert url is not None
        assert "report.htm" in url

    def test_skips_index_files(self):
        index = {
            "files": [
                {"name": "index.htm",  "type": ""},
                {"name": "main.htm",   "type": ""},
            ]
        }
        url = _find_primary_html_url(index, "789019", "000095017025100235", "10-K")
        # index.htm should be skipped; main.htm should be chosen
        assert "main.htm" in (url or "")

    def test_returns_none_on_no_html(self):
        index = {"files": [{"name": "filing.pdf", "type": "10-K"}]}
        url = _find_primary_html_url(index, "789019", "000095017025100235", "10-K")
        assert url is None

    def test_absolute_url_contains_base(self):
        index = {"files": [{"name": "form10k.htm", "type": "10-K"}]}
        url = _find_primary_html_url(index, "789019", "000095017025100235", "10-K")
        assert url is not None
        assert "789019" in url
        assert "000095017025100235" in url


# ---------------------------------------------------------------------------
# _download_annual_text
# ---------------------------------------------------------------------------

class TestDownloadAnnualText:
    """Unit tests for the HTML download helper."""

    _CIK = "0000789019"
    _ACC = "0000950170-25-100235"
    _PRIMARY_DOC = "msft-20250630.htm"

    def _mock_get(self, html: str = "<html><body>Annual report text</body></html>"):
        """Return a mock that makes _get() return an OK response with *html*."""
        mock_resp = MagicMock()
        mock_resp.raise_for_status.return_value = None
        mock_resp.content = html.encode()
        return mock_resp

    @patch("underlying.edgar_underlying_client._get")
    def test_uses_primary_document_directly(self, mock_get):
        """When primary_document is given, the direct URL is fetched — no index call."""
        mock_get.return_value = self._mock_get()

        result = _download_annual_text(
            self._CIK, self._ACC, "10-K", primary_document=self._PRIMARY_DOC
        )

        assert result is not None
        assert "annual report text" in result.lower()
        # Only one HTTP call should have been made (the direct HTML download)
        assert mock_get.call_count == 1
        called_url: str = mock_get.call_args[0][0]
        assert self._PRIMARY_DOC in called_url
        assert "index.json" not in called_url

    @patch("underlying.edgar_underlying_client._get")
    def test_fallback_to_index_when_no_primary_document(self, mock_get):
        """Without primary_document the index JSON is fetched first."""
        index_payload = {
            "files": [{"name": "msft-20250630.htm", "type": "10-K"}]
        }
        html_payload = "<html><body>Fallback 10-K text</body></html>"

        mock_index_resp = MagicMock()
        mock_index_resp.raise_for_status.return_value = None
        mock_index_resp.json.return_value = index_payload

        mock_html_resp = MagicMock()
        mock_html_resp.raise_for_status.return_value = None
        mock_html_resp.content = html_payload.encode()

        mock_get.side_effect = [mock_index_resp, mock_html_resp]

        result = _download_annual_text(self._CIK, self._ACC, "10-K")

        assert result is not None
        assert "fallback" in result.lower()
        # Two HTTP calls: index + HTML
        assert mock_get.call_count == 2
        index_url: str = mock_get.call_args_list[0][0][0]
        assert "index.json" in index_url

    @patch("underlying.edgar_underlying_client._get")
    def test_index_404_returns_none(self, mock_get):
        """A 404 on the index JSON (no primary_document path) returns None, not an exception."""
        import httpx
        mock_get.return_value = MagicMock(
            raise_for_status=MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "404", request=MagicMock(), response=MagicMock(status_code=404)
                )
            )
        )
        result = _download_annual_text(self._CIK, self._ACC, "10-K")
        assert result is None

    @patch("underlying.edgar_underlying_client._get")
    def test_html_download_failure_returns_none(self, mock_get):
        """If the HTML URL itself returns an error, None is returned."""
        import httpx
        mock_get.return_value = MagicMock(
            raise_for_status=MagicMock(
                side_effect=httpx.HTTPStatusError(
                    "500", request=MagicMock(), response=MagicMock(status_code=500)
                )
            )
        )
        result = _download_annual_text(
            self._CIK, self._ACC, "10-K", primary_document=self._PRIMARY_DOC
        )
        assert result is None

    @patch("underlying.edgar_underlying_client.config")
    @patch("underlying.edgar_underlying_client._get")
    def test_text_truncated_to_max_filing_chars(self, mock_get, mock_config):
        """Very long filing text is truncated to MAX_FILING_CHARS."""
        mock_config.MAX_FILING_CHARS = 20
        long_html = "<html><body>" + ("X" * 200) + "</body></html>"
        mock_get.return_value = self._mock_get(long_html)

        result = _download_annual_text(
            self._CIK, self._ACC, "10-K", primary_document=self._PRIMARY_DOC
        )
        assert result is not None
        assert len(result) <= 20


# ---------------------------------------------------------------------------
# detect_adr
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# C3 — 5xx retry in _get (ingest/edgar_client.py)
# ---------------------------------------------------------------------------

class TestEdgarGetRetry:
    """C3: _get() retries on HTTP 5xx and stops on definitive 4xx."""

    @patch("ingest.edgar_client._wait_rate_limit")
    def test_5xx_retried_then_success(self, _wait):
        """A single 5xx response is retried; the subsequent 200 is returned."""
        import ingest.edgar_client as ec

        five_xx = MagicMock()
        five_xx.status_code = 503

        ok = MagicMock()
        ok.status_code = 200

        with patch("ingest.edgar_client.httpx.get", side_effect=[five_xx, ok]):
            result = ec._get("http://example.com/test")

        assert result.status_code == 200

    @patch("ingest.edgar_client._wait_rate_limit")
    def test_404_not_retried(self, _wait):
        """A 404 is a definitive answer and must not be retried."""
        import ingest.edgar_client as ec

        not_found = MagicMock()
        not_found.status_code = 404

        call_count = 0

        def side_effect(*a, **kw):
            nonlocal call_count
            call_count += 1
            return not_found

        with patch("ingest.edgar_client.httpx.get", side_effect=side_effect):
            result = ec._get("http://example.com/missing")

        assert result.status_code == 404
        assert call_count == 1   # returned immediately, no retry

    @patch("ingest.edgar_client._wait_rate_limit")
    def test_all_5xx_exhausts_retries(self, _wait):
        """When all retries return 5xx, the final response is returned to the caller."""
        import ingest.edgar_client as ec

        five_xx = MagicMock()
        five_xx.status_code = 500

        with patch("ingest.edgar_client.httpx.get", return_value=five_xx):
            result = ec._get("http://example.com/bad")

        # After exhausting retries the last response is returned (caller does raise_for_status)
        assert result.status_code == 500


# ---------------------------------------------------------------------------
# M2 — ADR regex is scoped to cover-page text
# ---------------------------------------------------------------------------

class TestDetectAdrScope:
    """M2: detect_adr() only examines the first _ADR_SCAN_CHARS characters."""

    def test_adr_in_cover_page_detected(self):
        """ADR mention within cover-page range is detected."""
        text = "American Depositary Share " + "x" * 100
        assert detect_adr(text) is True

    def test_adr_beyond_scan_range_not_detected(self):
        """ADR mention beyond _ADR_SCAN_CHARS is not detected (avoids false positives)."""
        padding = "x" * _ADR_SCAN_CHARS
        text = padding + " American Depositary Share "
        assert detect_adr(text) is False

    def test_non_adr_not_detected_anywhere(self):
        """Plain common stock filing never triggers ADR detection."""
        text = "Common Stock, par value $0.00001 per share. " * 100
        assert detect_adr(text) is False


class TestDetectAdr:
    def test_adr_share(self):
        assert detect_adr("Each American Depositary Share represents one ordinary share.") is True

    def test_adr_receipt(self):
        assert detect_adr("American Depositary Receipt Program") is True

    def test_ads_unit(self):
        assert detect_adr("American Depositary Unit") is True

    def test_not_adr(self):
        assert detect_adr("Microsoft common stock, par value $0.00001 per share.") is False

    def test_empty_string(self):
        assert detect_adr("") is False

    def test_none_safe(self):
        assert detect_adr(None) is False   # type: ignore[arg-type]

    def test_case_insensitive(self):
        assert detect_adr("AMERICAN DEPOSITARY SHARE") is True


# ---------------------------------------------------------------------------
# fetch_metadata — integration (fully mocked)
# ---------------------------------------------------------------------------

class TestFetchMetadata:
    def _subs(self) -> dict[str, Any]:
        return _make_submissions(
            forms=["10-K", "10-Q", "10-Q", "10-Q"],
            filing_dates=["2025-07-30", "2025-05-08", "2025-02-14", "2024-11-07"],
            report_dates=["2025-06-30", "2025-03-31", "2024-12-31", "2024-09-30"],
            accessions=["0000111111-25-001", "0000111111-25-002",
                        "0000111111-25-003", "0000111111-24-004"],
        )

    @patch("underlying.edgar_underlying_client._fetch_submissions")
    @patch("underlying.edgar_underlying_client._fetch_companyfacts")
    @patch("underlying.edgar_underlying_client._download_annual_text")
    def test_happy_path(self, mock_text, mock_facts, mock_subs):
        mock_subs.return_value = self._subs()
        mock_facts.return_value = _make_companyfacts()
        mock_text.return_value = "Fiscal year 2025 annual report text..."

        meta = fetch_metadata("0000789019")

        assert meta.company_name == "MICROSOFT CORP"
        assert meta.last_annual is not None
        assert meta.last_annual.form == "10-K"
        assert meta.last_annual.period_end == date(2025, 6, 30)
        assert meta.last_quarterly is not None
        assert meta.last_quarterly.period_end == date(2025, 3, 31)
        assert meta.shares_outstanding == 7_500_000_000
        assert meta.public_float_usd == 2_800_000_000_000.0
        assert meta.annual_filing_text is not None
        assert meta.currentness is not None
        assert not meta.warnings

    @patch("underlying.edgar_underlying_client._fetch_submissions")
    @patch("underlying.edgar_underlying_client._fetch_companyfacts")
    @patch("underlying.edgar_underlying_client._download_annual_text")
    def test_xbrl_failure_is_non_fatal(self, mock_text, mock_facts, mock_subs):
        mock_subs.return_value = self._subs()
        mock_facts.side_effect = RuntimeError("XBRL service unavailable")
        mock_text.return_value = None

        meta = fetch_metadata("0000789019")

        assert meta.shares_outstanding is None
        assert len(meta.warnings) >= 1
        assert any("XBRL" in w for w in meta.warnings)

    @patch("underlying.edgar_underlying_client._fetch_submissions")
    @patch("underlying.edgar_underlying_client._fetch_companyfacts")
    @patch("underlying.edgar_underlying_client._download_annual_text")
    def test_html_download_failure_is_non_fatal(self, mock_text, mock_facts, mock_subs):
        mock_subs.return_value = self._subs()
        mock_facts.return_value = None
        mock_text.side_effect = ConnectionError("timeout")

        meta = fetch_metadata("0000789019")

        assert meta.annual_filing_text is None
        assert any("HTML download" in w or "Annual filing" in w for w in meta.warnings)

    @patch("underlying.edgar_underlying_client._fetch_submissions")
    def test_submissions_http_error_propagates(self, mock_subs):
        import httpx
        mock_subs.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        )
        with pytest.raises(Exception):
            fetch_metadata("9999999999")
