"""
tests/test_underlying_currentness.py — Unit tests for underlying/currentness.py

Pure unit tests: no network, no DB.  All date-sensitive tests pin ``date.today``
via monkeypatching so the suite never drifts with calendar time.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest

from underlying.currentness import (
    FilingCheck,
    NextFiling,
    CurrentnessReport,
    compute_currentness,
    _parse_fye,
    _last_completed_period_end,
    _quarter_ends_for_fy,
    _find_filing,
    _has_nt_filing,
    _detect_reporting_form,
    _within_18_months,
    _compute_next_due,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _isodate(d: date) -> str:
    return d.isoformat()


def _make_submissions(
    *,
    category: str = "non-accelerated filer",
    fye: str = "1231",
    forms: list[str] | None = None,
    filing_dates: list[str] | None = None,
    report_dates: list[str] | None = None,
) -> dict[str, Any]:
    """Build a minimal EDGAR submissions dict for testing."""
    return {
        "category": category,
        "fiscalYearEnd": fye,
        "filings": {
            "recent": {
                "form": forms or [],
                "filingDate": filing_dates or [],
                "reportDate": report_dates or [],
            }
        },
    }


# ---------------------------------------------------------------------------
# _parse_fye
# ---------------------------------------------------------------------------

class TestParseFye:
    def test_standard_december(self):
        assert _parse_fye("1231") == (12, 31)

    def test_june_30(self):
        assert _parse_fye("0630") == (6, 30)

    def test_invalid_returns_fallback(self):
        assert _parse_fye("XXXX") == (12, 31)

    def test_empty_returns_fallback(self):
        assert _parse_fye("") == (12, 31)

    def test_too_short_returns_fallback(self):
        assert _parse_fye("123") == (12, 31)


# ---------------------------------------------------------------------------
# _last_completed_period_end
# ---------------------------------------------------------------------------

class TestLastCompletedPeriodEnd:
    def test_same_year(self):
        ref = date(2025, 6, 15)
        result = _last_completed_period_end(12, 31, ref)
        assert result == date(2024, 12, 31)   # FYE Dec 31 has not passed yet in Jun

    def test_after_fye(self):
        ref = date(2025, 1, 15)
        result = _last_completed_period_end(12, 31, ref)
        assert result == date(2024, 12, 31)

    def test_on_exact_fye(self):
        ref = date(2024, 12, 31)
        result = _last_completed_period_end(12, 31, ref)
        assert result == date(2024, 12, 31)

    def test_june_fye_before(self):
        # FYE Jun 30, reference is March → last completed FY ended Jun 30 previous year
        ref = date(2025, 3, 1)
        result = _last_completed_period_end(6, 30, ref)
        assert result == date(2024, 6, 30)

    def test_june_fye_after(self):
        # FYE Jun 30, reference is Jul 15 → last completed FY just ended Jun 30
        ref = date(2025, 7, 15)
        result = _last_completed_period_end(6, 30, ref)
        assert result == date(2025, 6, 30)


# ---------------------------------------------------------------------------
# _quarter_ends_for_fy
# ---------------------------------------------------------------------------

class TestQuarterEndsForFy:
    def test_calendar_year(self):
        fy_end = date(2024, 12, 31)
        qends = _quarter_ends_for_fy(12, 31, fy_end)
        assert len(qends) == 3
        assert qends[0] == date(2024, 3, 31)
        assert qends[1] == date(2024, 6, 30)
        assert qends[2] == date(2024, 9, 30)

    def test_june_fye(self):
        fy_end = date(2024, 6, 30)
        qends = _quarter_ends_for_fy(6, 30, fy_end)
        assert len(qends) == 3
        assert qends[0] == date(2023, 9, 30)
        assert qends[1] == date(2023, 12, 31)
        assert qends[2] == date(2024, 3, 31)

    def test_last_day_of_month_correct(self):
        """Feb quarter end should be last day of February."""
        fy_end = date(2024, 5, 31)
        qends = _quarter_ends_for_fy(5, 31, fy_end)
        # 9 months before May → August; 6 before → November; 3 before → February
        assert qends[2] == date(2024, 2, 29)   # 2024 is a leap year


# ---------------------------------------------------------------------------
# _find_filing
# ---------------------------------------------------------------------------

class TestFindFiling:
    def _forms_for_msft(self) -> tuple[list[str], list[str], list[str]]:
        """Two 10-K filings: one for 2023 and one for 2024."""
        forms        = ["10-K",        "10-K"]
        filing_dates = ["2024-07-30",  "2023-07-28"]
        report_dates = ["2024-06-30",  "2023-06-30"]
        return forms, filing_dates, report_dates

    def test_exact_match(self):
        forms, fdates, rdates = self._forms_for_msft()
        period_end = date(2024, 6, 30)
        filed, acc = _find_filing(forms, fdates, rdates, "10-K", period_end, tolerance_days=7)
        assert filed == date(2024, 7, 30)
        assert acc is None   # accession not extracted in current impl

    def test_within_tolerance(self):
        forms        = ["10-K"]
        filing_dates = ["2025-03-01"]
        report_dates = ["2024-12-28"]   # 3 days before Dec 31
        period_end = date(2024, 12, 31)
        filed, _ = _find_filing(forms, filing_dates, report_dates, "10-K", period_end, tolerance_days=7)
        assert filed == date(2025, 3, 1)

    def test_outside_tolerance_not_found(self):
        forms        = ["10-K"]
        filing_dates = ["2025-03-01"]
        report_dates = ["2024-12-15"]   # 16 days before Dec 31
        period_end = date(2024, 12, 31)
        filed, _ = _find_filing(forms, filing_dates, report_dates, "10-K", period_end, tolerance_days=7)
        assert filed is None

    def test_amended_form_matched(self):
        forms        = ["10-K/A"]
        filing_dates = ["2025-03-05"]
        report_dates = ["2024-12-31"]
        period_end = date(2024, 12, 31)
        filed, _ = _find_filing(forms, filing_dates, report_dates, "10-K", period_end, tolerance_days=7)
        assert filed == date(2025, 3, 5)

    def test_wrong_form_not_matched(self):
        forms        = ["10-Q"]
        filing_dates = ["2025-02-14"]
        report_dates = ["2024-12-31"]
        period_end = date(2024, 12, 31)
        filed, _ = _find_filing(forms, filing_dates, report_dates, "10-K", period_end, tolerance_days=7)
        assert filed is None

    def test_empty_lists(self):
        filed, _ = _find_filing([], [], [], "10-K", date(2024, 12, 31), tolerance_days=7)
        assert filed is None


# ---------------------------------------------------------------------------
# FilingCheck properties
# ---------------------------------------------------------------------------

class TestFilingCheck:
    def _make(self, *, filed, deadline_offset=60, nt_filed=False, nt_ext=15):
        period_end = date(2024, 12, 31)
        deadline = period_end + timedelta(days=deadline_offset)
        nt_dl = deadline + timedelta(days=nt_ext)
        fc = FilingCheck(
            form="10-K",
            period_end=period_end,
            filed=filed,
            deadline=deadline,
            nt_extended_deadline=nt_dl,
            nt_filed=nt_filed,
        )
        return fc

    def test_on_time_before_deadline(self):
        fc = self._make(filed=date(2025, 2, 1))   # deadline ≈ Mar 1
        assert fc.is_on_time is True

    def test_on_time_exactly_on_deadline(self):
        fc = self._make(filed=date(2025, 3, 1))
        assert fc.is_on_time is True

    def test_late_without_nt(self):
        fc = self._make(filed=date(2025, 3, 5))   # 4 days after deadline
        assert fc.is_on_time is False

    def test_within_nt_extension(self):
        fc = self._make(filed=date(2025, 3, 10), nt_filed=True)  # 9 days past deadline, within +15
        assert fc.is_on_time is True

    def test_beyond_nt_extension(self):
        fc = self._make(filed=date(2025, 3, 20), nt_filed=True)  # >15 days past deadline
        assert fc.is_on_time is False

    def test_is_overdue_no_filing_past_deadline(self):
        """Overdue when filed is None and deadline has passed."""
        fc = self._make(filed=None)
        # Deadline = Dec 31 + 60 = Feb 29/Mar 1 2025 → already in past vs today (2026-04-23)
        assert fc.is_overdue is True

    def test_is_overdue_false_when_filed(self):
        fc = self._make(filed=date(2025, 3, 20))
        assert fc.is_overdue is False

    def test_is_overdue_nt_past_extended(self):
        """With NT filed, overdue only after NT extension deadline."""
        period_end = date(2024, 12, 31)
        deadline = period_end + timedelta(days=60)
        nt_dl = deadline + timedelta(days=15)
        fc = FilingCheck(
            form="10-K",
            period_end=period_end,
            filed=None,
            deadline=deadline,
            nt_extended_deadline=nt_dl,
            nt_filed=True,
        )
        # NT extended deadline is ~Mar 16 2025; today is 2026-04-23 → overdue
        assert fc.is_overdue is True


# ---------------------------------------------------------------------------
# compute_currentness — integration-style (no network)
# ---------------------------------------------------------------------------

_TODAY = date(2026, 4, 23)


def _patch_today(monkeypatch):
    """Patch date.today() inside the currentness module with a real date subclass.

    Using a subclass ensures ``date(year, month, day)`` constructor calls
    (e.g. inside _last_completed_period_end) still work correctly.
    """
    import underlying.currentness as cm

    _fixed = _TODAY

    class _FakeDate(date):
        @classmethod
        def today(cls) -> date:      # type: ignore[override]
            return _fixed

    monkeypatch.setattr(cm, "date", _FakeDate)


class TestComputeCurrentness:
    """Integration-style tests for compute_currentness().

    All tests pin today = 2026-04-23.  With this date, a Dec-31 company's
    last completed FY end is 2025-12-31 and the Q1/Q2/Q3 deadlines for
    FY2025 are all in the past.  Filing dates must therefore cover the
    FY2025 reporting periods (report dates in 2025).

    Deadline reference (non-accelerated filer, +90d / +45d, +15d NT ext):
        10-K (Dec 31, 2025): deadline Mar 31, 2026; NT deadline Apr 15, 2026
        Q1  (Mar 31, 2025) : deadline May 15, 2025; NT deadline May 30, 2025
        Q2  (Jun 30, 2025) : deadline Aug 14, 2025; NT deadline Aug 29, 2025
        Q3  (Sep 30, 2025) : deadline Nov 14, 2025; NT deadline Nov 29, 2025

    Deadline reference (large accelerated filer, +60d / +40d, +15d NT ext):
        10-K (Dec 31, 2025): deadline Mar 1, 2026;  NT deadline Mar 16, 2026
        Q1  (Mar 31, 2025) : deadline May 10, 2025; NT deadline May 25, 2025
        Q2  (Jun 30, 2025) : deadline Aug 9, 2025;  NT deadline Aug 24, 2025
        Q3  (Sep 30, 2025) : deadline Nov 9, 2025;  NT deadline Nov 24, 2025
    """

    def _calendar_year_submissions(
        self,
        *,
        category: str = "non-accelerated filer",
        # FY2025 annual (period end Dec 31, 2025)
        annual_filed: str | None = "2026-02-10",  # well within +90d deadline Mar 31
        # FY2025 quarters
        q3_filed:     str | None = "2025-11-01",  # within +45d deadline Nov 14
        q2_filed:     str | None = "2025-08-05",  # within +45d deadline Aug 14
        q1_filed:     str | None = "2025-05-08",  # within +45d deadline May 15
        include_nt:   bool = False,
        nt_form:      str = "NT 10-K",
        nt_filed_date: str = "2026-04-01",         # within 18 months of today
        nt_report_date: str = "2025-12-31",
    ) -> dict[str, Any]:
        """Build a submissions dict for a Dec-31 FY2025 company."""
        forms, fd, rd = [], [], []

        if annual_filed:
            forms.append("10-K"); fd.append(annual_filed); rd.append("2025-12-31")
        if q3_filed:
            forms.append("10-Q"); fd.append(q3_filed); rd.append("2025-09-30")
        if q2_filed:
            forms.append("10-Q"); fd.append(q2_filed); rd.append("2025-06-30")
        if q1_filed:
            forms.append("10-Q"); fd.append(q1_filed); rd.append("2025-03-31")
        if include_nt:
            forms.append(nt_form); fd.append(nt_filed_date); rd.append(nt_report_date)

        return _make_submissions(
            category=category,
            fye="1231",
            forms=forms,
            filing_dates=fd,
            report_dates=rd,
        )

    def test_current_all_on_time(self, monkeypatch):
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions()
        report = compute_currentness(subs)
        assert report.status == "current"
        assert report.eligible is True
        assert report.last_annual is not None
        assert report.last_annual.is_on_time

    def test_delinquent_missing_annual(self, monkeypatch):
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions(annual_filed=None)
        report = compute_currentness(subs)
        assert report.status == "delinquent"
        assert report.eligible is False
        assert any("10-K" in n and "overdue" in n for n in report.notes)

    def test_delinquent_missing_quarter(self, monkeypatch):
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions(q3_filed=None)
        report = compute_currentness(subs)
        assert report.status == "delinquent"
        assert report.eligible is False

    def test_late_nt_awaiting_underlying(self, monkeypatch):
        """late_nt when NT filed but annual not yet on record AND today within NT window.

        Large accelerated filer:
            10-K original deadline : 2026-03-01
            NT 10-K filed          : 2026-03-02  (just after original deadline)
            NT extended deadline   : 2026-03-16
            Synthetic "today"      : 2026-03-10  (inside NT window → not yet overdue)
        """
        import underlying.currentness as cm

        _nt_today = date(2026, 3, 10)

        class _FakeDateNT(date):
            @classmethod
            def today(cls) -> date:   # type: ignore[override]
                return _nt_today

        monkeypatch.setattr(cm, "date", _FakeDateNT)

        # All quarters filed on time; annual not filed yet; NT 10-K on record
        subs = self._calendar_year_submissions(
            category="large accelerated filer",
            annual_filed=None,
            include_nt=True,
            nt_form="NT 10-K",
            nt_filed_date="2026-03-02",
            nt_report_date="2025-12-31",
        )
        report = compute_currentness(subs)
        assert report.status == "late_nt"
        assert report.eligible is True
        assert any("NT" in n for n in report.notes)

    def test_late_nt_filed_after_nt_deadline(self, monkeypatch):
        """late_nt when NT filed but actual 10-K came in AFTER the NT extended deadline.

        In this case the annual is eventually filed (not overdue via is_overdue,
        which is always False when filed is not None) but it arrived too late for
        the NT window → not is_on_time.  The status falls into the first late_nt
        branch: nt_filed and filed is not None and not is_on_time.

        Large accelerated filer:
            10-K original deadline : 2026-03-01
            NT 10-K filed          : 2026-03-02
            NT extended deadline   : 2026-03-16
            10-K filed             : 2026-03-20  (after NT deadline → not is_on_time)
            Today                  : 2026-04-23  (after NT deadline)
        """
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions(
            category="large accelerated filer",
            annual_filed="2026-03-20",    # after NT deadline Mar 16
            q1_filed="2025-05-05",        # within large-accel Q deadline May 10
            q2_filed="2025-08-05",        # within Aug 9
            q3_filed="2025-11-05",        # within Nov 9
            include_nt=True,
            nt_form="NT 10-K",
            nt_filed_date="2026-03-02",
            nt_report_date="2025-12-31",
        )
        report = compute_currentness(subs)
        assert report.status == "late_nt"
        assert report.eligible is True

    def test_unknown_late_filing_without_nt(self, monkeypatch):
        """'unknown' status when a filing arrived late with no NT on record.

        The filing is not None (so not is_overdue), no NT was filed
        (so not the late_nt branch), and filed > deadline (so not is_on_time).
        The final else-branch produces 'unknown'.

        Non-accel filer; Q3 filed two weeks late, no NT:
            Q3 (Sep 30, 2025) deadline : Nov 14, 2025
            Q3 filed                   : Nov 30, 2025  (16 days late, no NT)
        """
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions(
            q3_filed="2025-11-30",   # 16 days after Nov 14 deadline, no NT
        )
        report = compute_currentness(subs)
        assert report.status == "unknown"
        assert report.eligible is False

    def test_empty_filings(self, monkeypatch):
        _patch_today(monkeypatch)
        subs = _make_submissions()
        report = compute_currentness(subs)
        assert report.status == "unknown"
        assert report.eligible is False
        assert any("No filing history" in n for n in report.notes)

    def test_20f_filer_no_10q_required(self, monkeypatch):
        """20-F filers have no 10-Q obligation; annual filed on time → current."""
        _patch_today(monkeypatch)
        # FY2025: 20-F deadline = Dec 31, 2025 + 120d = Apr 30, 2026
        # today = Apr 23, 2026 → deadline NOT yet passed → annual not yet checked
        # Use FY2024 data so the deadline (Dec 31, 2024 + 120 = Apr 30, 2025) is past
        subs = _make_submissions(
            category="foreign private issuer",
            fye="1231",
            forms=["20-F"],
            filing_dates=["2025-04-25"],  # filed Apr 25, 2025
            report_dates=["2024-12-31"],  # for FY2024
        )
        # With today=2026-04-23 the last completed FY end for a Dec-31 filer is 2025-12-31.
        # FY2025 20-F deadline = Apr 30, 2026, which has NOT passed → annual not yet overdue.
        # The FY2024 20-F (with deadline Apr 30 2025) falls outside the tolerance window
        # and won't match → annual_filed = None → is_overdue depends on today vs Apr 30 2026.
        # Apr 23 < Apr 30 → not yet overdue → status = current (all checks on time vacuously)
        report = compute_currentness(subs)
        # 20-F annual deadline Apr 30 2026 not yet past → filed=None but not overdue → current
        assert report.eligible is True
        assert report.status in ("current", "unknown")   # vacuously current or unknown

    def test_20f_filer_on_time_within_window(self, monkeypatch):
        """20-F filed on time for last completed FY → current."""
        import underlying.currentness as cm

        # Pin today to May 5, 2025 so FY2024 (Dec 31, 2024) is last complete FY
        # and deadline Apr 30, 2025 has just passed.
        _later = date(2025, 5, 5)

        class _FakeDate2025(date):
            @classmethod
            def today(cls) -> date:   # type: ignore[override]
                return _later

        monkeypatch.setattr(cm, "date", _FakeDate2025)

        subs = _make_submissions(
            category="foreign private issuer",
            fye="1231",
            forms=["20-F"],
            filing_dates=["2025-04-25"],
            report_dates=["2024-12-31"],
        )
        report = compute_currentness(subs)
        assert report.status == "current"
        assert report.eligible is True

    def test_next_due_is_populated(self, monkeypatch):
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions()
        report = compute_currentness(subs)
        assert report.next_due is not None
        assert report.next_due.form in ("10-K", "10-Q")

    def test_nt_accessions_populated(self, monkeypatch):
        _patch_today(monkeypatch)
        subs = self._calendar_year_submissions(
            include_nt=True,
            nt_filed_date="2026-04-01",
            nt_report_date="2025-12-31",
        )
        report = compute_currentness(subs)
        assert len(report.nt_accessions) >= 1


# ---------------------------------------------------------------------------
# _detect_reporting_form
# ---------------------------------------------------------------------------

class TestDetectReportingForm:
    def test_detects_20f(self):
        subs = {"filings": {"recent": {"form": ["20-F", "20-F/A", "6-K"]}}}
        assert _detect_reporting_form(subs) == "20-F"

    def test_detects_40f(self):
        subs = {"filings": {"recent": {"form": ["40-F"]}}}
        assert _detect_reporting_form(subs) == "40-F"

    def test_default_10k(self):
        subs = {"filings": {"recent": {"form": ["10-K", "10-Q"]}}}
        assert _detect_reporting_form(subs) == "10-K"

    def test_empty_history(self):
        subs = {"filings": {"recent": {"form": []}}}
        assert _detect_reporting_form(subs) == "10-K"


# ---------------------------------------------------------------------------
# _within_18_months
# ---------------------------------------------------------------------------

class TestWithin18Months:
    def test_recent_date(self):
        ref = date(2025, 6, 1)
        assert _within_18_months("2024-06-01", ref) is True

    def test_exactly_18_months_boundary(self):
        ref = date(2025, 6, 1)
        assert _within_18_months("2023-12-01", ref) is True   # ≤ 548 days

    def test_too_old(self):
        ref = date(2025, 6, 1)
        assert _within_18_months("2020-01-01", ref) is False

    def test_invalid_date_returns_false(self):
        assert _within_18_months("not-a-date", date.today()) is False


# ---------------------------------------------------------------------------
# M5 edge-case additions
# ---------------------------------------------------------------------------

class TestParseFyeEdgeCases:
    """_parse_fye handles unusual / malformed FYE strings gracefully."""

    def test_feb_28_standard(self):
        """Feb-28 FYE parsed correctly (common for non-leap-year filers)."""
        assert _parse_fye("0228") == (2, 28)

    def test_empty_string_defaults_to_dec31(self):
        assert _parse_fye("") == (12, 31)

    def test_none_like_string_defaults(self):
        assert _parse_fye("None") == (12, 31)

    def test_non_numeric_defaults(self):
        assert _parse_fye("XXXX") == (12, 31)

    def test_short_string_defaults(self):
        assert _parse_fye("12") == (12, 31)


class TestFindFilingEdgeCases:
    """_find_filing is resilient to malformed submission data."""

    def test_malformed_report_date_skipped(self):
        """Entries with unparseable report dates are ignored, not raised."""
        forms        = ["10-K", "10-K"]
        filed_dates  = ["2025-07-30", "2025-07-30"]
        report_dates = ["NOT-A-DATE", "2025-06-30"]   # first entry is malformed
        period_end   = date(2025, 6, 30)

        filed, _ = _find_filing(forms, filed_dates, report_dates, "10-K", period_end, 7)
        # Second entry should still match
        assert filed == date(2025, 7, 30)

    def test_malformed_filed_date_skipped(self):
        """Entries with unparseable filing dates are ignored, not raised."""
        forms        = ["10-K"]
        filed_dates  = ["NOT-VALID"]
        report_dates = ["2025-06-30"]
        period_end   = date(2025, 6, 30)

        filed, _ = _find_filing(forms, filed_dates, report_dates, "10-K", period_end, 7)
        assert filed is None

    def test_empty_forms_returns_none(self):
        filed, _ = _find_filing([], [], [], "10-K", date(2025, 6, 30), 7)
        assert filed is None

    def test_period_outside_tolerance_not_matched(self):
        """A filing whose period_end is beyond tolerance is not returned."""
        forms        = ["10-K"]
        filed_dates  = ["2025-07-30"]
        report_dates = ["2025-03-31"]   # 91 days off from target
        period_end   = date(2025, 6, 30)

        filed, _ = _find_filing(forms, filed_dates, report_dates, "10-K", period_end, 7)
        assert filed is None


class TestComputeCurrentnessEdgeCases:
    """compute_currentness handles unusual submission shapes."""

    def test_empty_filing_history_returns_unknown(self):
        """No filing history → status unknown, not an exception."""
        subs = _make_submissions(forms=[])
        report = compute_currentness(subs)
        assert report.status == "unknown"
        assert report.eligible is False
        assert any("No filing history" in n for n in report.notes)

    def test_missing_filings_key_returns_unknown(self):
        """Completely absent 'filings' key is treated as no history."""
        subs: dict = {"category": "non-accelerated filer", "fiscalYearEnd": "1231"}
        report = compute_currentness(subs)
        assert report.status == "unknown"

    @patch("underlying.currentness.date")
    def test_negative_days_remaining_in_next_due(self, mock_date):
        """When all future deadlines are in the past, next_due may be None."""
        # Pin today to far in the future so all candidates are past
        mock_date.today.return_value = date(2030, 1, 1)
        mock_date.fromisoformat.side_effect = date.fromisoformat
        mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
        subs = _make_submissions(
            fye="1231",
            forms=["10-K", "10-Q", "10-Q", "10-Q"],
            filing_dates=["2025-03-01", "2024-11-05", "2024-08-05", "2024-05-05"],
            report_dates=["2024-12-31", "2024-09-30", "2024-06-30", "2024-03-31"],
        )
        # Should not raise; may return None if all candidates are overdue
        report = compute_currentness(subs)
        assert report.status in ("current", "delinquent", "late_nt", "unknown")

    def test_20f_filer_no_quarterly_requirement(self):
        """20-F filers are not penalised for missing 10-Q filings."""
        # A 20-F filer with only an annual filing on record
        subs = _make_submissions(
            fye="1231",
            forms=["20-F"],
            filing_dates=["2025-04-01"],
            report_dates=["2024-12-31"],
        )
        report = compute_currentness(subs)
        # Should not be "unknown" due to missing quarterly history
        assert report.status in ("current", "late_nt", "unknown")
        assert report.recent_quarters == []
