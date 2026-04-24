"""
Underlying Data Module — Currentness Engine.

Determines whether an underlying security is "current" in its SEC Exchange Act
reporting obligations. This is a prerequisite for the abbreviated disclosure
mechanism used in structured product (424B2) prospectus supplements.

All required inputs are obtained from the EDGAR submissions JSON:
    data.sec.gov/submissions/CIK{id}.json

Status values
-------------
current     All required periodic reports filed within their SEC deadlines
            (including NT-extension window where applicable).
late_nt     Filed within the NT extension window (NT 10-K / NT 10-Q was filed
            in the same period). Warning signal, not yet delinquent.
delinquent  A required filing deadline (including NT extension) has passed
            with no filing on record. The underlying is ineligible for
            abbreviated disclosure while delinquent.
unknown     Insufficient filing history (<4 quarters) to determine status;
            or the company is a new filer.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import calendar
import config
from underlying.utils import detect_reporting_form

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class FilingCheck:
    """Result of checking one required periodic filing."""
    form: str                     # "10-K" | "10-Q" | "20-F"
    period_end: date
    filed: date | None            # None if no filing found
    deadline: date                # expected deadline (before NT extension)
    nt_extended_deadline: date    # deadline including NT +15 days
    nt_filed: bool = False        # True if an NT was found for this period
    within_nt_extension: bool = False
    days_delta: int = 0           # filed - period_end (negative = early)

    @property
    def is_on_time(self) -> bool:
        """True iff the filing was made by the extended deadline (or NT window)."""
        if self.filed is None:
            return False
        if self.filed <= self.deadline:
            return True
        return self.nt_filed and self.filed <= self.nt_extended_deadline

    @property
    def is_overdue(self) -> bool:
        """True iff the extended deadline has passed with no filing."""
        if self.filed is not None:
            return False
        today = date.today()
        if self.nt_filed:
            return today > self.nt_extended_deadline
        return today > self.deadline


@dataclass
class NextFiling:
    """The next periodic report expected from this filer."""
    form: str
    period_end: date
    deadline: date
    days_remaining: int           # negative = already overdue


@dataclass
class CurrentnessReport:
    """Full currentness assessment for one underlying security."""
    status: str                                        # current|late_nt|delinquent|unknown
    eligible: bool                                     # valid for abbreviated disclosure
    last_annual: FilingCheck | None = None             # most recent 10-K / 20-F check
    recent_quarters: list[FilingCheck] = field(default_factory=list)  # last 3 10-Q checks
    nt_accessions: list[str] = field(default_factory=list)            # NT filings in window
    next_due: NextFiling | None = None
    notes: list[str] = field(default_factory=list)    # human-readable explanation bullets


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_fye(fye_str: str) -> tuple[int, int]:
    """Parse fiscal year end string (MMDD) into (month, day) ints.

    Returns (12, 31) as a safe fallback on any parse error.
    """
    try:
        if len(fye_str) == 4:
            return int(fye_str[:2]), int(fye_str[2:])
    except (ValueError, TypeError):
        pass
    log.warning("Could not parse fiscalYearEnd %r; defaulting to 12-31", fye_str)
    return 12, 31


def _last_completed_period_end(fye_month: int, fye_day: int, reference: date | None = None) -> date:
    """Return the most recently completed fiscal year end date on or before *reference*."""
    ref = reference or date.today()
    candidate = date(ref.year, fye_month, fye_day)
    # Handle 52/53-week years that land on e.g. last Saturday of month:
    # we use a tolerance window in the caller
    if candidate > ref:
        candidate = date(ref.year - 1, fye_month, fye_day)
    return candidate


def _quarter_ends_for_fy(fye_month: int, fye_day: int, fy_end: date) -> list[date]:
    """Return the three interim quarter-end dates for the fiscal year ending on *fy_end*.

    For standard calendar-year companies (FYE Dec 31) this yields Mar 31, Jun 30, Sep 30.
    For non-calendar FYEs (e.g. Jun 30) this yields Sep 30, Dec 31, Mar 31.
    """
    ends: list[date] = []
    for months_back in (9, 6, 3):
        # Step back from FYE by 3-month increments
        year = fy_end.year
        month = fy_end.month - months_back
        while month <= 0:
            month += 12
            year -= 1
        # Quarter ends are always last-day-of-month in practice
        import calendar
        _, last_day = calendar.monthrange(year, month)
        ends.append(date(year, month, last_day))
    return ends   # ordered oldest → newest within the FY


def _find_filing(
    forms: list[str],
    filing_dates: list[str],
    report_dates: list[str],
    target_form: str,
    period_end: date,
    tolerance_days: int,
) -> tuple[date | None, str | None]:
    """Scan filing history for a specific form covering *period_end* ± *tolerance_days*.

    Returns (filed_date, accession_number) or (None, None) if not found.
    """
    accessions: list[str] = []
    # Try to get accession numbers if available
    try:
        from ingest.edgar_client import _get  # noqa: F401 — just confirming import path
    except Exception:
        pass

    for i, form in enumerate(forms):
        if form not in (target_form, f"{target_form}/A"):
            continue
        raw_report = report_dates[i] if i < len(report_dates) else ""
        if not raw_report:
            continue
        try:
            rdate = date.fromisoformat(raw_report)
        except ValueError:
            continue
        delta = abs((rdate - period_end).days)
        if delta <= tolerance_days:
            try:
                filed = date.fromisoformat(filing_dates[i])
            except ValueError:
                continue
            return filed, None   # accession number not critical for status

    return None, None


def _has_nt_filing(
    forms: list[str],
    filing_dates: list[str],
    report_dates: list[str],
    target_form: str,
    period_end: date,
    tolerance_days: int,
) -> bool:
    """Return True if an NT form for *target_form* covers *period_end*."""
    nt_form = f"NT {target_form}"
    filed, _ = _find_filing(forms, filing_dates, report_dates, nt_form, period_end, tolerance_days)
    return filed is not None


# ---------------------------------------------------------------------------
# Main public function
# ---------------------------------------------------------------------------

def compute_currentness(submissions: dict[str, Any]) -> CurrentnessReport:
    """Compute the currentness status for an underlying security.

    Parameters
    ----------
    submissions:
        The raw dict from ``data.sec.gov/submissions/CIK{id}.json``.

    Returns
    -------
    CurrentnessReport
        Full assessment including per-filing checks, NT flags, next-due date,
        and the top-level ``status`` / ``eligible`` fields.
    """
    category: str = (submissions.get("category") or "").lower()
    fye_str: str = submissions.get("fiscalYearEnd") or "1231"
    reporting_form: str = _detect_reporting_form(submissions)

    deadlines = config.filing_deadlines(category)
    nt_ext = deadlines.get("NT_EXTENSION", 15)
    tolerance = config.CURRENTNESS_PERIOD_TOLERANCE_DAYS

    # Unpack filing history arrays
    recent = submissions.get("filings", {}).get("recent", {})
    forms: list[str]        = recent.get("form", [])
    filed_dates: list[str]  = recent.get("filingDate", [])
    report_dates: list[str] = recent.get("reportDate", [])

    if not forms:
        return CurrentnessReport(
            status="unknown",
            eligible=False,
            notes=["No filing history available from EDGAR"],
        )

    fye_month, fye_day = _parse_fye(fye_str)
    today = date.today()

    # ── Annual check (10-K or 20-F) ──────────────────────────────────────────
    annual_form = "20-F" if reporting_form == "20-F" else "10-K"
    annual_deadline_days: int = deadlines.get(annual_form, 90)

    fy_end = _last_completed_period_end(fye_month, fye_day)
    annual_deadline = fy_end + timedelta(days=annual_deadline_days)
    annual_nt_deadline = annual_deadline + timedelta(days=nt_ext)

    annual_filed, _ = _find_filing(forms, filed_dates, report_dates, annual_form, fy_end, tolerance)
    annual_nt = _has_nt_filing(forms, filed_dates, report_dates, annual_form, fy_end, tolerance)

    annual_check = FilingCheck(
        form=annual_form,
        period_end=fy_end,
        filed=annual_filed,
        deadline=annual_deadline,
        nt_extended_deadline=annual_nt_deadline,
        nt_filed=annual_nt,
        within_nt_extension=annual_nt and annual_filed is not None and annual_filed > annual_deadline,
        days_delta=(annual_filed - fy_end).days if annual_filed else 0,
    )

    # ── Quarterly checks (10-Q only; 20-F filers have no 10-Q obligation) ────
    quarter_checks: list[FilingCheck] = []
    quarterly_deadline_days: int = deadlines.get("10-Q", 45)

    if annual_form != "20-F" and quarterly_deadline_days > 0:
        qends = _quarter_ends_for_fy(fye_month, fye_day, fy_end)
        for qend in qends:
            q_deadline = qend + timedelta(days=quarterly_deadline_days)
            q_nt_deadline = q_deadline + timedelta(days=nt_ext)
            # Only check quarters whose deadline has already passed
            if q_deadline > today:
                continue
            q_filed, _ = _find_filing(forms, filed_dates, report_dates, "10-Q", qend, tolerance)
            q_nt = _has_nt_filing(forms, filed_dates, report_dates, "10-Q", qend, tolerance)
            quarter_checks.append(FilingCheck(
                form="10-Q",
                period_end=qend,
                filed=q_filed,
                deadline=q_deadline,
                nt_extended_deadline=q_nt_deadline,
                nt_filed=q_nt,
                within_nt_extension=q_nt and q_filed is not None and q_filed > q_deadline,
                days_delta=(q_filed - qend).days if q_filed else 0,
            ))

    # ── Collect NT accession numbers for reporting ────────────────────────────
    nt_accessions: list[str] = [
        filed_dates[i] for i, f in enumerate(forms)
        if f.startswith("NT ") and i < len(filed_dates)
        and _within_18_months(filed_dates[i], today)
    ]

    # ── Determine overall status ──────────────────────────────────────────────
    all_checks = [annual_check] + quarter_checks
    notes: list[str] = []

    # Need at least the annual + 3 quarterly checks to be meaningful
    if not quarter_checks and annual_form != "20-F":
        status = "unknown"
        eligible = False
        notes.append("Fewer than 3 quarters of 10-Q history found — insufficient data")
    elif any(c.is_overdue for c in all_checks):
        status = "delinquent"
        eligible = False
        for c in all_checks:
            if c.is_overdue:
                notes.append(f"{c.form} for period ending {c.period_end} is overdue (deadline {c.deadline})")
    elif any(c.nt_filed and c.filed is not None and not c.is_on_time for c in all_checks):
        # Filed within NT extension window but after original deadline
        status = "late_nt"
        eligible = True
        notes.append("One or more reports filed within NT extension window")
    elif any(c.nt_filed and c.filed is None for c in all_checks):
        # NT filed but underlying report not yet on record
        status = "late_nt"
        eligible = True
        notes.append("NT filing on record; awaiting underlying report")
    elif all(c.is_on_time for c in all_checks if c.deadline <= today):
        status = "current"
        eligible = True
        notes.append("All required reports filed within deadline")
    else:
        status = "unknown"
        eligible = False
        notes.append("Could not conclusively determine currentness from available data")

    # ── Next filing due ───────────────────────────────────────────────────────
    next_due = _compute_next_due(
        annual_form, fye_month, fye_day, fy_end, annual_deadline_days, quarterly_deadline_days, today
    )

    return CurrentnessReport(
        status=status,
        eligible=eligible,
        last_annual=annual_check,
        recent_quarters=quarter_checks,
        nt_accessions=nt_accessions,
        next_due=next_due,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Supplementary helpers
# ---------------------------------------------------------------------------

def _detect_reporting_form(submissions: dict[str, Any]) -> str:
    """Infer the primary reporting form from EDGAR submissions metadata.

    Delegates to :func:`underlying.utils.detect_reporting_form` — the canonical
    implementation shared with ``edgar_underlying_client.py``.
    """
    recent = submissions.get("filings", {}).get("recent", {})
    forms: list[str] = recent.get("form", [])
    return detect_reporting_form(forms)


def _within_18_months(date_str: str, reference: date) -> bool:
    """Return True if *date_str* (ISO) is within 18 months of *reference*."""
    try:
        d = date.fromisoformat(date_str)
        return (reference - d).days <= 548   # ~18 months
    except ValueError:
        return False


def _compute_next_due(
    annual_form: str,
    fye_month: int,
    fye_day: int,
    last_fy_end: date,
    annual_deadline_days: int,
    quarterly_deadline_days: int,
    today: date,
) -> NextFiling | None:
    """Compute the next upcoming periodic report deadline."""
    import calendar as _cal

    candidates: list[NextFiling] = []

    # Next annual
    next_fy_end = date(last_fy_end.year + 1, fye_month, fye_day)
    next_annual_deadline = next_fy_end + timedelta(days=annual_deadline_days)
    candidates.append(NextFiling(
        form=annual_form,
        period_end=next_fy_end,
        deadline=next_annual_deadline,
        days_remaining=(next_annual_deadline - today).days,
    ))

    # Next quarter ends (up to 4 quarters from now)
    if annual_form != "20-F" and quarterly_deadline_days > 0:
        for months_ahead in range(3, 16, 3):
            month = fye_month + months_ahead
            year = last_fy_end.year
            while month > 12:
                month -= 12
                year += 1
            _, last_day = _cal.monthrange(year, month)
            qend = date(year, month, last_day)
            qdeadline = qend + timedelta(days=quarterly_deadline_days)
            if qend < last_fy_end:   # skip quarters already within the last FY
                continue
            candidates.append(NextFiling(
                form="10-Q",
                period_end=qend,
                deadline=qdeadline,
                days_remaining=(qdeadline - today).days,
            ))

    if not candidates:
        return None

    # Return the soonest upcoming deadline
    future = [c for c in candidates if c.deadline >= today]
    return min(future, key=lambda c: c.deadline) if future else None
