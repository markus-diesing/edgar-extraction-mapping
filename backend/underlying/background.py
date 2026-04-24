"""
Underlying Data Module — Background Ingest Pipeline.

Orchestrates the full ingest pipeline for one or more underlying securities
in a background thread (via FastAPI ``BackgroundTasks``).

Pipeline per security
---------------------
1.  Resolve identifier → CIK + ticker (``identifier_resolver``)
2.  Fetch EDGAR metadata, XBRL facts, 10-K HTML (``edgar_underlying_client``)
3.  LLM-extract cover page fields (``extractor``)
4.  Fetch market data (``market_data_client``)
5.  Upsert ``UnderlyingSecurity`` row
6.  Upsert ``UnderlyingFieldResult`` rows for Tier 2 fields
7.  Update ``UnderlyingJob`` progress counters

Status lifecycle
----------------
``ingested`` → ``fetching`` → ``fetched`` → ``needs_review``
(if any Tier 2 field has confidence < threshold)

Error handling
--------------
Per-item errors are caught and recorded in ``UnderlyingJob.results``.
The batch continues; the job only fails if *all* items error.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

import config
import database as db
from database import (
    UnderlyingSecurity,
    UnderlyingFieldResult,
    UnderlyingJob,
)
from underlying.edgar_underlying_client import (
    UnderlyingMetadata,
    fetch_metadata,
    detect_adr,
)
from underlying.extractor import (
    ExtractionResult,
    extract_underlying_fields,
)
from underlying.identifier_resolver import resolve, ResolutionResult
from underlying.market_data_client import MarketDataResult, fetch_market_data

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Confidence scores for Tier 1 data (structured, authoritative)
# ---------------------------------------------------------------------------
_TIER1_CONFIDENCE = 1.0
_TIER3_CONFIDENCE = 0.7   # market data is approximate

# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_ingest_job(
    job_id: str,
    identifiers: list[str],
    *,
    fetch_market: bool = True,
    run_llm: bool = True,
) -> None:
    """Execute a batch ingest job (called in a background thread).

    Parameters
    ----------
    job_id:
        UUID of the :class:`~database.UnderlyingJob` row to update.
    identifiers:
        List of raw identifier strings (tickers, ISINs, CIKs, …).
    fetch_market:
        Whether to fetch Tier 3 market data (yfinance).
    run_llm:
        Whether to run the Tier 2 LLM extraction pass.
    """
    log.info("Starting ingest job %s (%d identifiers)", job_id, len(identifiers))

    results_log: list[dict[str, Any]] = []
    success_count = 0
    error_count = 0

    _update_job(job_id, status="running", total=len(identifiers), done=0,
                success=0, errors=0, results=[])

    for i, raw_id in enumerate(identifiers):
        item_result: dict[str, Any] = {"identifier": raw_id}
        try:
            underlying_id = _process_one(
                raw_id,
                fetch_market=fetch_market,
                run_llm=run_llm,
            )
            item_result["underlying_id"] = underlying_id
            success_count += 1
        except Exception as exc:
            log.error("Ingest error for %r: %s", raw_id, exc, exc_info=True)
            item_result["error"] = str(exc)
            error_count += 1

        results_log.append(item_result)
        _update_job(
            job_id,
            done=i + 1,
            success=success_count,
            errors=error_count,
            results=results_log,
        )

    final_status = "done" if error_count < len(identifiers) else "error"
    _update_job(job_id, status=final_status)
    log.info(
        "Ingest job %s finished: %d success, %d errors",
        job_id, success_count, error_count,
    )


# ---------------------------------------------------------------------------
# Per-item pipeline
# ---------------------------------------------------------------------------

def _process_one(
    raw_id: str,
    *,
    fetch_market: bool,
    run_llm: bool,
) -> str:
    """Ingest one identifier.  Returns the ``UnderlyingSecurity.id``."""

    # Step 1 — Resolve identifier
    resolution = resolve(raw_id)
    if resolution.status == "not_found":
        raise ValueError(f"Identifier not found: {raw_id!r}")
    if resolution.status == "error":
        raise RuntimeError(f"Resolver error for {raw_id!r}: {resolution.error}")
    if resolution.status in ("candidates", "multi_class"):
        raise ValueError(
            f"Ambiguous identifier {raw_id!r}: use a more specific identifier "
            f"(status={resolution.status})"
        )

    sec = resolution.resolved
    if sec is None:
        raise ValueError(
            f"Resolution returned status='resolved' but resolved field is None for {raw_id!r}"
        )
    cik = sec.cik
    ticker = sec.ticker

    # Step 2 — Fetch EDGAR metadata
    meta = fetch_metadata(cik)

    # Step 3 — LLM extraction from 10-K text
    extraction: ExtractionResult | None = None
    if run_llm and meta.annual_filing_text:
        try:
            extraction = extract_underlying_fields(
                filing_text=meta.annual_filing_text,
                company_name=meta.company_name,
                form=meta.reporting_form,
            )
            # C4: surface JSON parse / API errors so they appear in fetch_error
            # rather than silently producing zero field_results.
            if extraction.error:
                log.warning(
                    "LLM extraction returned an error for CIK %s: %s", cik, extraction.error
                )
                meta.warnings.append(f"LLM extraction failed: {extraction.error}")
                extraction = None   # prevent writing empty field_results row-set
        except Exception as exc:
            meta.warnings.append(f"LLM extraction failed: {exc}")
            log.warning("LLM extraction failed for CIK %s: %s", cik, exc)

    # ADR flag — combine LLM + regex
    adr_flag = _resolve_adr_flag(meta, extraction)

    # Step 4 — Market data
    market: MarketDataResult | None = None
    if fetch_market:
        try:
            market = fetch_market_data(ticker)
        except Exception as exc:
            log.warning("Market data fetch failed for %s: %s", ticker, exc)

    # Step 5 — Upsert DB record
    underlying_id = _upsert_security(raw_id, sec.source_identifier_type, meta, extraction, adr_flag, market, ticker, sec)

    # Step 6 — Upsert Tier 2 field results
    if extraction is not None:
        _upsert_field_results(underlying_id, extraction, meta)

    return underlying_id


# ---------------------------------------------------------------------------
# DB write helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _upsert_security(
    raw_id: str,
    id_type: str,
    meta: UnderlyingMetadata,
    extraction: ExtractionResult | None,
    adr_flag: bool,
    market: MarketDataResult | None,
    ticker: str,
    resolved_sec: Any,
) -> str:
    """Upsert the ``UnderlyingSecurity`` row.  Returns the row UUID."""
    cfg_version = _load_field_config_version()

    # Pull LLM-extracted values (defaults to None if extraction unavailable)
    share_class_name = _get_extraction_value(extraction, "share_class_name")
    share_type = _get_extraction_value(extraction, "share_type")
    brief_description = _get_extraction_value(extraction, "brief_description")

    # Currentness
    cr = meta.currentness
    needs_review = False
    if extraction is not None:
        needs_review = any(f.needs_review for f in extraction.fields)

    def _status() -> str:
        if needs_review:
            return "needs_review"
        return "fetched"

    with db.get_session() as session:
        existing = (
            session.query(UnderlyingSecurity)
            .filter_by(cik=meta.cik, ticker=ticker)
            .first()
        )

        if existing is None:
            row = UnderlyingSecurity(
                cik=meta.cik,
                ticker=ticker,
                source_identifier=raw_id,
                source_identifier_type=id_type,
            )
            session.add(row)
            try:
                # Flush early to detect a concurrent-insert UNIQUE violation
                # before we write the remaining 30+ column updates.
                session.flush()
            except IntegrityError:
                # C2: another thread/job inserted the same (cik, ticker) between
                # our SELECT and this INSERT.  Roll back the failed insert and
                # fall through to the existing row.
                session.rollback()
                row = (
                    session.query(UnderlyingSecurity)
                    .filter_by(cik=meta.cik, ticker=ticker)
                    .first()
                )
                if row is None:
                    raise  # Unexpected — neither INSERT nor SELECT found a row
                log.debug(
                    "Concurrent upsert detected for CIK=%s ticker=%s — using existing row",
                    meta.cik, ticker,
                )
        else:
            row = existing

        # ── Tier 1 — submissions API ──────────────────────────────────
        row.company_name           = meta.company_name
        row.exchange               = (meta.exchanges[0] if meta.exchanges else "")
        row.reporting_form         = meta.reporting_form
        row.filer_category         = meta.category
        row.fiscal_year_end        = meta.fiscal_year_end
        row.sic_code               = meta.sic_code
        row.sic_description        = meta.sic_description
        row.state_of_incorporation = meta.state_of_incorporation
        row.entity_type            = meta.entity_type
        row.adr_flag               = adr_flag

        if meta.last_annual:
            row.last_10k_accession = meta.last_annual.accession
            row.last_10k_filed     = meta.last_annual.filed.isoformat()
            row.last_10k_period    = meta.last_annual.period_end.isoformat()

        if meta.last_quarterly:
            row.last_10q_accession = meta.last_quarterly.accession
            row.last_10q_filed     = meta.last_quarterly.filed.isoformat()
            row.last_10q_period    = meta.last_quarterly.period_end.isoformat()

        if cr:
            row.current_status       = cr.status
            row.nt_flag              = bool(cr.nt_accessions)
            if cr.next_due:
                row.next_expected_filing = cr.next_due.deadline.isoformat()
                row.next_expected_form   = cr.next_due.form

        # ── Tier 1 — XBRL ────────────────────────────────────────────
        if meta.shares_outstanding is not None:
            row.shares_outstanding      = float(meta.shares_outstanding)
            row.shares_outstanding_date = meta.shares_outstanding_date.isoformat() if meta.shares_outstanding_date else None
        if meta.public_float_usd is not None:
            row.public_float_usd  = float(meta.public_float_usd)
            row.public_float_date = meta.public_float_date.isoformat() if meta.public_float_date else None

        # ── Tier 2 — LLM ─────────────────────────────────────────────
        if share_class_name is not None:
            row.share_class_name = share_class_name
        if share_type is not None:
            row.share_type = share_type
        # brief_description stored only in field_results (no direct DB column)

        # ── Tier 3 — market data ──────────────────────────────────────
        if market and market.is_ok():
            row.closing_value       = market.closing_value
            row.closing_value_date  = market.closing_value_date.isoformat() if market.closing_value_date else None
            row.initial_value       = market.initial_value
            row.initial_value_date  = market.initial_value_date.isoformat() if market.initial_value_date else None
            row.hist_data_series    = market.hist_data_series
            row.market_data_source  = market.source
            row.market_data_fetched_at = _now()

        # ── Lifecycle ─────────────────────────────────────────────────
        row.status               = _status()
        row.last_fetched_at      = _now()
        row.field_config_version = cfg_version
        row.fetch_error          = (
            "; ".join(meta.warnings) if meta.warnings else None
        )

        session.flush()   # ensure id is assigned
        underlying_id = row.id
        session.commit()

    return underlying_id


def _upsert_field_results(
    underlying_id: str,
    extraction: ExtractionResult,
    meta: UnderlyingMetadata,
) -> None:
    """Upsert UnderlyingFieldResult rows for all Tier 2 extracted fields."""
    cfg_version = _load_field_config_version()

    with db.get_session() as session:
        for fr in extraction.fields:
            existing = (
                session.query(UnderlyingFieldResult)
                .filter_by(underlying_id=underlying_id, field_name=fr.field_name)
                .first()
            )
            value_json = json.dumps(fr.value)

            if existing is None:
                row = UnderlyingFieldResult(
                    underlying_id=underlying_id,
                    field_name=fr.field_name,
                    extracted_value=value_json,
                    confidence_score=fr.confidence,
                    source_excerpt=fr.source_excerpt,
                    source_type=fr.source_type,
                    is_approximate=False,
                    review_status="needs_review" if fr.needs_review else "pending",
                    field_config_version=cfg_version,
                )
                session.add(row)
            else:
                # Re-fetch: update extracted value but preserve any reviewer override
                existing.extracted_value  = value_json
                existing.confidence_score = fr.confidence
                existing.source_excerpt   = fr.source_excerpt
                existing.field_config_version = cfg_version
                # Only reset review_status if the field was not already accepted/corrected
                if existing.review_status not in ("accepted", "corrected"):
                    existing.review_status = "needs_review" if fr.needs_review else "pending"

        session.commit()


def _update_job(job_id: str, **kwargs: Any) -> None:
    """Update UnderlyingJob columns in place."""
    with db.get_session() as session:
        job = session.get(UnderlyingJob, job_id)
        if job is None:
            log.warning("Job %s not found in DB — skipping update", job_id)
            return
        for k, v in kwargs.items():
            if k == "results":
                setattr(job, k, json.dumps(v))
            else:
                setattr(job, k, v)
        job.updated_at = _now()
        session.commit()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_extraction_value(extraction: ExtractionResult | None, field_name: str) -> Any:
    if extraction is None:
        return None
    fr = extraction.get(field_name)
    return fr.value if fr else None


def _resolve_adr_flag(meta: UnderlyingMetadata, extraction: ExtractionResult | None) -> bool:
    """Determine ADR status from LLM extraction or regex fallback."""
    # Prefer LLM result (higher accuracy)
    if extraction is not None:
        fr = extraction.get("adr_flag")
        if fr is not None and isinstance(fr.value, bool):
            return fr.value

    # Fallback: regex on filing text
    if meta.annual_filing_text:
        return detect_adr(meta.annual_filing_text)

    return False


def _load_field_config_version() -> str:
    """Load the current field config version string (best-effort)."""
    try:
        from underlying.field_config import load as load_cfg
        return load_cfg().version
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Job factory (used by the router to create the initial DB row)
# ---------------------------------------------------------------------------

def create_job(identifiers: list[str]) -> str:
    """Create a pending UnderlyingJob row and return its ID."""
    with db.get_session() as session:
        job = UnderlyingJob(
            status="pending",
            total=len(identifiers),
            done=0,
            success=0,
            errors=0,
            results=json.dumps([]),
        )
        session.add(job)
        session.commit()
        return job.id
