"""
tests/test_underlying_background.py — Unit tests for underlying/background.py

Uses an in-memory SQLite database so no filesystem side effects occur.
All external calls (EDGAR, Claude, yfinance) are mocked.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import database as db
from database import Base, UnderlyingSecurity, UnderlyingJob, UnderlyingFieldResult
from underlying.background import (
    run_ingest_job,
    create_job,
    _get_extraction_value,
    _resolve_adr_flag,
)
from underlying.edgar_underlying_client import (
    UnderlyingMetadata,
    AnnualFilingRef,
)
from underlying.extractor import ExtractionResult, FieldResult
from underlying.market_data_client import MarketDataResult
from underlying.currentness import CurrentnessReport


# ---------------------------------------------------------------------------
# In-memory DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Replace the module-level engine with an in-memory SQLite engine."""
    mem_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(mem_engine)

    # Patch database.engine and database.get_session
    monkeypatch.setattr(db, "engine", mem_engine)
    monkeypatch.setattr(db, "get_session", lambda: Session(mem_engine))

    yield mem_engine


def _get_session(engine) -> Session:
    return Session(engine)


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def _make_metadata(ticker: str = "MSFT") -> UnderlyingMetadata:
    return UnderlyingMetadata(
        cik="0000789019",
        company_name="MICROSOFT CORP",
        tickers=[ticker],
        exchanges=["Nasdaq"],
        entity_type="operating",
        category="large accelerated filer",
        fiscal_year_end="0630",
        reporting_form="10-K",
        sic_code="7372",
        sic_description="Prepackaged Software",
        state_of_incorporation="WA",
        last_annual=AnnualFilingRef(
            form="10-K",
            accession="0000950170-25-001",
            period_end=date(2025, 6, 30),
            filed=date(2025, 7, 30),
        ),
        last_quarterly=AnnualFilingRef(
            form="10-Q",
            accession="0000950170-25-002",
            period_end=date(2025, 3, 31),
            filed=date(2025, 5, 8),
        ),
        currentness=CurrentnessReport(
            status="current",
            eligible=True,
            notes=["All required reports filed within deadline"],
        ),
        shares_outstanding=7_500_000_000,
        shares_outstanding_date=date(2025, 6, 30),
        public_float_usd=2_800_000_000_000.0,
        public_float_date=date(2025, 6, 30),
        annual_filing_text="Microsoft is a technology company...",
        warnings=[],
    )


def _make_extraction(confidence: float = 0.95) -> ExtractionResult:
    fields = [
        FieldResult("share_class_name", "Common Stock, $0.00001 par value", confidence,
                    "Common Stock", confidence < 0.80),
        FieldResult("share_type", "Common Stock", confidence, "Common Stock", confidence < 0.80),
        FieldResult("brief_description",
                    "Microsoft designs software and cloud services.", confidence,
                    "Microsoft designs", confidence < 0.80),
        FieldResult("adr_flag", False, confidence, "", confidence < 0.80),
    ]
    return ExtractionResult(fields=fields)


def _make_market() -> MarketDataResult:
    r = MarketDataResult()
    r.ticker = "MSFT"
    r.initial_value = 100.0
    r.initial_value_date = date(2020, 1, 2)
    r.closing_value = 420.0
    r.closing_value_date = date(2025, 4, 1)
    r.hist_data_series = json.dumps([{"date": "2025-04-01", "close": 420.0, "volume": 0}])
    r.source = "Yahoo Finance (approximate)"
    return r


def _mock_resolution(ticker: str = "MSFT", cik: str = "0000789019"):
    from underlying.identifier_resolver import ResolutionResult, ResolvedSecurity
    sec = ResolvedSecurity(
        cik=cik,
        ticker=ticker,
        company_name="MICROSOFT CORP",
        exchange="Nasdaq",
        source_identifier=ticker,
        source_identifier_type="ticker",
    )
    return ResolutionResult(status="resolved", resolved=sec)


# ---------------------------------------------------------------------------
# create_job
# ---------------------------------------------------------------------------

class TestCreateJob:
    def test_creates_pending_job(self, in_memory_db):
        job_id = create_job(["MSFT", "AAPL"])
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job is not None
        assert job.status == "pending"
        assert job.total == 2

    def test_returns_string_id(self, in_memory_db):
        job_id = create_job(["MSFT"])
        assert isinstance(job_id, str)
        assert len(job_id) > 0


# ---------------------------------------------------------------------------
# _get_extraction_value
# ---------------------------------------------------------------------------

class TestGetExtractionValue:
    def test_returns_value(self):
        ex = _make_extraction()
        assert _get_extraction_value(ex, "share_type") == "Common Stock"

    def test_returns_none_for_missing_field(self):
        ex = _make_extraction()
        assert _get_extraction_value(ex, "nonexistent") is None

    def test_returns_none_for_no_extraction(self):
        assert _get_extraction_value(None, "share_type") is None


# ---------------------------------------------------------------------------
# _resolve_adr_flag
# ---------------------------------------------------------------------------

class TestResolveAdrFlag:
    def test_prefers_llm_result(self):
        meta = _make_metadata()
        ex = ExtractionResult(fields=[FieldResult("adr_flag", True, 0.95)])
        assert _resolve_adr_flag(meta, ex) is True

    def test_llm_false_not_overridden(self):
        meta = _make_metadata()
        meta.annual_filing_text = "Each American Depositary Share represents one ordinary share."
        ex = ExtractionResult(fields=[FieldResult("adr_flag", False, 0.95)])
        # LLM says False; filing text has ADR keywords — LLM takes precedence
        assert _resolve_adr_flag(meta, ex) is False

    def test_regex_fallback_when_no_extraction(self):
        meta = _make_metadata()
        meta.annual_filing_text = "Each American Depositary Share represents one ordinary share."
        assert _resolve_adr_flag(meta, None) is True

    def test_false_when_no_text_and_no_extraction(self):
        meta = _make_metadata()
        meta.annual_filing_text = None
        assert _resolve_adr_flag(meta, None) is False

    def test_ignores_non_bool_llm_value(self):
        meta = _make_metadata()
        meta.annual_filing_text = None
        ex = ExtractionResult(fields=[FieldResult("adr_flag", None, 0.5)])
        # value is None (not bool) → fall through to regex → no ADR text → False
        assert _resolve_adr_flag(meta, ex) is False


# ---------------------------------------------------------------------------
# run_ingest_job — happy path
# ---------------------------------------------------------------------------

class TestRunIngestJob:
    def _run(self, in_memory_db, identifiers=None, confidence=0.95, with_market=True):
        identifiers = identifiers or ["MSFT"]
        job_id = create_job(identifiers)
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=_make_metadata()),
            patch("underlying.background.extract_underlying_fields",
                  return_value=_make_extraction(confidence)),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market() if with_market else MarketDataResult()),
        ):
            run_ingest_job(job_id, identifiers, fetch_market=with_market)
        return job_id

    def test_job_status_done(self, in_memory_db):
        job_id = self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job.status == "done"
        assert job.success == 1
        assert job.errors == 0

    def test_security_row_created(self, in_memory_db):
        self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            rows = s.query(UnderlyingSecurity).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.cik == "0000789019"
        assert row.ticker == "MSFT"
        assert row.company_name == "MICROSOFT CORP"

    def test_tier1_data_populated(self, in_memory_db):
        self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            row = s.query(UnderlyingSecurity).first()
        assert row.sic_code == "7372"
        assert row.current_status == "current"
        assert row.last_10k_accession == "0000950170-25-001"
        assert row.shares_outstanding == pytest.approx(7_500_000_000)
        assert row.public_float_usd == pytest.approx(2_800_000_000_000.0)

    def test_tier2_data_populated(self, in_memory_db):
        self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            row = s.query(UnderlyingSecurity).first()
        assert row.share_class_name == "Common Stock, $0.00001 par value"
        assert row.share_type == "Common Stock"

    def test_tier3_market_data_populated(self, in_memory_db):
        self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            row = s.query(UnderlyingSecurity).first()
        assert row.closing_value == pytest.approx(420.0)
        assert row.initial_value == pytest.approx(100.0)
        assert row.hist_data_series is not None

    def test_field_results_created(self, in_memory_db):
        self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            results = s.query(UnderlyingFieldResult).all()
        field_names = {r.field_name for r in results}
        assert "share_class_name" in field_names
        assert "share_type" in field_names
        assert "brief_description" in field_names

    def test_low_confidence_sets_needs_review_status(self, in_memory_db):
        self._run(in_memory_db, confidence=0.5)
        with _get_session(in_memory_db) as s:
            row = s.query(UnderlyingSecurity).first()
        assert row.status == "needs_review"

    def test_high_confidence_sets_fetched_status(self, in_memory_db):
        self._run(in_memory_db, confidence=0.95)
        with _get_session(in_memory_db) as s:
            row = s.query(UnderlyingSecurity).first()
        assert row.status == "fetched"

    def test_second_ingest_updates_not_duplicates(self, in_memory_db):
        """Running the same identifier twice should update, not create a duplicate row."""
        self._run(in_memory_db)
        self._run(in_memory_db)
        with _get_session(in_memory_db) as s:
            count = s.query(UnderlyingSecurity).count()
        assert count == 1

    def test_market_data_skipped_when_flag_false(self, in_memory_db):
        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=_make_metadata()),
            patch("underlying.background.extract_underlying_fields",
                  return_value=_make_extraction()),
            patch("underlying.background.fetch_market_data") as mock_mkt,
        ):
            run_ingest_job(job_id, ["MSFT"], fetch_market=False)
        mock_mkt.assert_not_called()

    def test_llm_skipped_when_flag_false(self, in_memory_db):
        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=_make_metadata()),
            patch("underlying.background.extract_underlying_fields") as mock_llm,
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["MSFT"], run_llm=False)
        mock_llm.assert_not_called()

    def test_batch_progress_updated(self, in_memory_db):
        job_id = create_job(["MSFT", "AAPL"])
        def _meta(id):
            m = _make_metadata(ticker=id.upper()[:4])
            return m
        with (
            patch("underlying.background.resolve",
                  side_effect=[_mock_resolution("MSFT"), _mock_resolution("AAPL", "0000320193")]),
            patch("underlying.background.fetch_metadata",
                  side_effect=[_make_metadata("MSFT"), _make_metadata("AAPL")]),
            patch("underlying.background.extract_underlying_fields",
                  return_value=_make_extraction()),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["MSFT", "AAPL"])
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job.done == 2
        assert job.success == 2


# ---------------------------------------------------------------------------
# run_ingest_job — error paths
# ---------------------------------------------------------------------------

class TestRunIngestJobErrors:
    def test_resolution_failure_records_error(self, in_memory_db):
        from underlying.identifier_resolver import ResolutionResult
        job_id = create_job(["BADINPUT"])
        with patch("underlying.background.resolve",
                   return_value=ResolutionResult(status="not_found")):
            run_ingest_job(job_id, ["BADINPUT"])
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job.errors == 1
        results = json.loads(job.results)
        assert results[0]["error"] is not None

    def test_edgar_failure_records_error(self, in_memory_db):
        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata",
                  side_effect=RuntimeError("EDGAR down")),
        ):
            run_ingest_job(job_id, ["MSFT"])
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job.errors == 1
        assert job.status == "error"   # all items failed → error status

    def test_partial_batch_succeeds(self, in_memory_db):
        """First item fails, second succeeds → job status 'done'."""
        from underlying.identifier_resolver import ResolutionResult
        job_id = create_job(["BAD", "MSFT"])
        resolve_results = [
            ResolutionResult(status="not_found"),
            _mock_resolution("MSFT"),
        ]
        with (
            patch("underlying.background.resolve", side_effect=resolve_results),
            patch("underlying.background.fetch_metadata", return_value=_make_metadata()),
            patch("underlying.background.extract_underlying_fields",
                  return_value=_make_extraction()),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["BAD", "MSFT"])
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job.status == "done"   # at least one success
        assert job.success == 1
        assert job.errors == 1

    def test_llm_failure_non_fatal(self, in_memory_db):
        """LLM extraction error should not fail the item."""
        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=_make_metadata()),
            patch("underlying.background.extract_underlying_fields",
                  side_effect=RuntimeError("Claude quota exceeded")),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["MSFT"])
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        # LLM failure is caught inside _process_one; item still succeeds
        assert job.success == 1


# ---------------------------------------------------------------------------
# M5 additions — C4 extraction error propagation and C2 upsert robustness
# ---------------------------------------------------------------------------

class TestExtractionErrorPropagation:
    """C4: LLM extraction errors surface in fetch_error, not silently vanish."""

    def test_extraction_error_stored_in_fetch_error(self, in_memory_db):
        """When ExtractionResult.error is set, the message appears in fetch_error."""
        from underlying.extractor import ExtractionResult

        meta = _make_metadata()
        meta.annual_filing_text = "Some filing text"

        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=meta),
            patch("underlying.background.extract_underlying_fields",
                  return_value=ExtractionResult(error="JSON parse error: line 1")),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["MSFT"])

        # The job should still succeed (LLM error is non-fatal)
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
            assert job.success == 1

            # But fetch_error on the security row should record the LLM failure
            sec = s.query(db.UnderlyingSecurity).first()
            assert sec is not None
            assert sec.fetch_error is not None
            assert "LLM extraction failed" in sec.fetch_error

            # And no field results should have been created
            frs = s.query(db.UnderlyingFieldResult).filter_by(
                underlying_id=sec.id
            ).all()
            assert frs == []

    def test_extraction_exception_stored_in_fetch_error(self, in_memory_db):
        """When extract_underlying_fields() raises, the error also surfaces."""
        meta = _make_metadata()
        meta.annual_filing_text = "Some text"

        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=meta),
            patch("underlying.background.extract_underlying_fields",
                  side_effect=RuntimeError("API quota exceeded")),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["MSFT"])

        with _get_session(in_memory_db) as s:
            sec = s.query(db.UnderlyingSecurity).first()
            assert sec is not None
            assert sec.fetch_error is not None
            assert "LLM extraction failed" in sec.fetch_error

    def test_no_extraction_error_when_text_absent(self, in_memory_db):
        """When annual_filing_text is None, LLM is skipped — no fetch_error."""
        meta = _make_metadata()
        meta.annual_filing_text = None  # override the default non-None value

        job_id = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=meta),
            patch(
                "underlying.background.extract_underlying_fields",
                side_effect=AssertionError("LLM should not be called when filing text is absent"),
            ),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id, ["MSFT"])

        with _get_session(in_memory_db) as s:
            sec = s.query(db.UnderlyingSecurity).first()
            assert sec is not None
            # No LLM error (LLM was never called)
            assert sec.fetch_error is None


class TestUpsertRobustness:
    """C2: Second ingest of same ticker updates the existing row, not duplicate."""

    def test_reingest_updates_existing_row(self, in_memory_db):
        """Ingesting the same ticker twice produces exactly one security row."""
        job_id1 = create_job(["MSFT"])
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=_make_metadata()),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id1, ["MSFT"])

        job_id2 = create_job(["MSFT"])
        updated_meta = _make_metadata()
        updated_meta.company_name = "MICROSOFT CORP (updated)"
        with (
            patch("underlying.background.resolve", return_value=_mock_resolution()),
            patch("underlying.background.fetch_metadata", return_value=updated_meta),
            patch("underlying.background.fetch_market_data",
                  return_value=_make_market()),
        ):
            run_ingest_job(job_id2, ["MSFT"])

        with _get_session(in_memory_db) as s:
            rows = s.query(db.UnderlyingSecurity).all()
            assert len(rows) == 1                        # only one row
            assert rows[0].company_name == "MICROSOFT CORP (updated)"  # updated value
