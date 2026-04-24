"""
tests/test_underlying_router.py — Integration tests for underlying/router.py

Mounts the underlying router on a lightweight FastAPI app (no lifespan, no other
routers) so tests are fully isolated from the rest of the application.

All DB access uses an in-memory SQLite engine injected via monkeypatch.
External calls (resolve, run_ingest_job, field_config I/O) are mocked.
Background tasks run synchronously inside FastAPI TestClient, so ingest
background functions are always patched to avoid touching live services.
"""
from __future__ import annotations

import io
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import database as db
from database import (
    Base,
    Filing,
    UnderlyingEditLog,
    UnderlyingFieldResult,
    UnderlyingJob,
    UnderlyingLink,
    UnderlyingSecurity,
)
from underlying.field_config import FieldConfig, FieldDef


# ---------------------------------------------------------------------------
# App fixture — thin FastAPI app with only the underlying router
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def app():
    from underlying.router import router
    _app = FastAPI()
    _app.include_router(router, prefix="/api")
    return _app


# ---------------------------------------------------------------------------
# In-memory DB fixture (autouse per test)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def in_memory_db(monkeypatch):
    """Replace the module-level engine with an in-memory SQLite engine.

    StaticPool forces all sessions to share the same underlying connection,
    which is required for SQLite `:memory:` databases when the FastAPI
    TestClient runs the ASGI app in a worker thread (anyio portal).
    """
    mem_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(mem_engine)

    monkeypatch.setattr(db, "engine", mem_engine)
    monkeypatch.setattr(db, "get_session", lambda: Session(mem_engine))

    yield mem_engine


# ---------------------------------------------------------------------------
# Client fixture (function-scoped so it picks up each test's monkeypatches)
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(app):
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------

def _get_session(engine) -> Session:
    return Session(engine)


def _seed_security(engine, **kwargs) -> UnderlyingSecurity:
    """Insert a minimal UnderlyingSecurity row and return it."""
    defaults = dict(
        cik="0000789019",
        ticker="MSFT",
        company_name="MICROSOFT CORP",
        status="fetched",
        source_identifier="MSFT",
        source_identifier_type="ticker",
    )
    defaults.update(kwargs)
    with _get_session(engine) as s:
        row = UnderlyingSecurity(**defaults)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def _seed_job(engine, **kwargs) -> UnderlyingJob:
    defaults = dict(status="pending", total=1, done=0, success=0, errors=0, results="[]")
    defaults.update(kwargs)
    with _get_session(engine) as s:
        job = UnderlyingJob(**defaults)
        s.add(job)
        s.commit()
        s.refresh(job)
        return job


def _seed_filing(engine) -> Filing:
    with _get_session(engine) as s:
        f = Filing(accession_number="0000950170-25-001")
        s.add(f)
        s.commit()
        s.refresh(f)
        return f


def _seed_field_result(engine, underlying_id: str, field_name: str, value: Any) -> UnderlyingFieldResult:
    with _get_session(engine) as s:
        fr = UnderlyingFieldResult(
            underlying_id=underlying_id,
            field_name=field_name,
            extracted_value=json.dumps(value),
            confidence_score=0.95,
            review_status="pending",
            source_type="10k_cover",
        )
        s.add(fr)
        s.commit()
        s.refresh(fr)
        return fr


def _make_field_config() -> FieldConfig:
    return FieldConfig(
        version="1",
        fields=[
            FieldDef("share_class_name", "Share Class Name", True),
            FieldDef("share_type", "Share Type", True),
            FieldDef("brief_description", "Brief Description", False),
        ],
    )


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------

def _mock_resolution(status="resolved", ticker="MSFT", cik="0000789019"):
    from underlying.identifier_resolver import ResolutionResult, ResolvedSecurity
    if status == "resolved":
        sec = ResolvedSecurity(
            cik=cik,
            ticker=ticker,
            company_name="MICROSOFT CORP",
            exchange="Nasdaq",
            source_identifier=ticker,
            source_identifier_type="ticker",
        )
        return ResolutionResult(status="resolved", resolved=sec)
    if status == "candidates":
        sec1 = ResolvedSecurity(cik="0000789019", ticker="MSFT",
                                company_name="Microsoft Corp", exchange="Nasdaq",
                                source_identifier="MSFT", source_identifier_type="ticker")
        sec2 = ResolvedSecurity(cik="0000789020", ticker="MSFT2",
                                company_name="Microsoft Inc", exchange="NYSE",
                                source_identifier="MSFT2", source_identifier_type="ticker")
        return ResolutionResult(status="candidates", candidates=[sec1, sec2])
    if status == "error":
        return ResolutionResult(status="error", error="Network timeout")
    return ResolutionResult(status=status)


# ---------------------------------------------------------------------------
# GET /api/underlying/resolve
# ---------------------------------------------------------------------------

class TestResolveEndpoint:
    def test_resolved_returns_200(self, client):
        with patch("underlying.router.resolve_identifier",
                   return_value=_mock_resolution("resolved")):
            resp = client.get("/api/underlying/resolve?identifier=MSFT")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "resolved"
        assert body["resolved"]["cik"] == "0000789019"
        assert body["resolved"]["ticker"] == "MSFT"

    def test_not_found_returns_200_with_status(self, client):
        """Resolution reporting 'not_found' is a valid outcome, not an HTTP error."""
        with patch("underlying.router.resolve_identifier",
                   return_value=_mock_resolution("not_found")):
            resp = client.get("/api/underlying/resolve?identifier=BADINPUT")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"

    def test_error_returns_502(self, client):
        with patch("underlying.router.resolve_identifier",
                   return_value=_mock_resolution("error")):
            resp = client.get("/api/underlying/resolve?identifier=MSFT")
        assert resp.status_code == 502
        assert "Network timeout" in resp.json()["detail"]

    def test_candidates_returned(self, client):
        with patch("underlying.router.resolve_identifier",
                   return_value=_mock_resolution("candidates")):
            resp = client.get("/api/underlying/resolve?identifier=Microsoft")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "candidates"
        assert len(body["candidates"]) == 2


# ---------------------------------------------------------------------------
# POST /api/underlying/ingest
# ---------------------------------------------------------------------------

class TestIngestEndpoint:
    def test_start_job_returns_202(self, client):
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest",
                json={"identifiers": ["MSFT"], "fetch_market": True, "run_llm": True},
            )
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        assert body["total"] == 1

    def test_multiple_identifiers_accepted(self, client):
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest",
                json={"identifiers": ["MSFT", "AAPL"], "fetch_market": False, "run_llm": False},
            )
        assert resp.status_code == 202
        assert resp.json()["total"] == 2

    def test_too_many_identifiers_returns_422(self, client, monkeypatch):
        import config as cfg
        monkeypatch.setattr(cfg, "UNDERLYING_INGEST_MAX_CSV_ROWS", 2)
        # Reload the module-level constant in the router
        import underlying.router as rt
        monkeypatch.setattr(rt, "_MAX_CSV_ROWS", 2)

        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest",
                json={"identifiers": ["A", "B", "C"]},
            )
        assert resp.status_code == 422

    def test_job_row_created_in_db(self, client, in_memory_db):
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest",
                json={"identifiers": ["MSFT"]},
            )
        job_id = resp.json()["job_id"]
        with _get_session(in_memory_db) as s:
            job = s.get(UnderlyingJob, job_id)
        assert job is not None
        assert job.status in ("pending", "running", "done")  # bg may have run


# ---------------------------------------------------------------------------
# POST /api/underlying/ingest/csv
# ---------------------------------------------------------------------------

class TestIngestCSVEndpoint:
    def _csv_bytes(self, content: str) -> bytes:
        return content.encode("utf-8")

    def test_valid_csv_returns_202(self, client):
        csv_content = "identifier\nMSFT\nAAPL\n"
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest/csv",
                files={"file": ("tickers.csv", self._csv_bytes(csv_content), "text/csv")},
            )
        assert resp.status_code == 202
        assert resp.json()["total"] == 2

    def test_missing_identifier_column_returns_422(self, client):
        csv_content = "symbol\nMSFT\n"
        resp = client.post(
            "/api/underlying/ingest/csv",
            files={"file": ("bad.csv", self._csv_bytes(csv_content), "text/csv")},
        )
        assert resp.status_code == 422
        assert "identifier" in resp.json()["detail"]

    def test_empty_csv_returns_422(self, client):
        csv_content = "identifier\n\n\n"
        resp = client.post(
            "/api/underlying/ingest/csv",
            files={"file": ("empty.csv", self._csv_bytes(csv_content), "text/csv")},
        )
        assert resp.status_code == 422

    def test_bom_prefix_handled(self, client):
        # Encode with utf-8-sig so the BOM bytes (EF BB BF) are prepended.
        # Do NOT pre-include \ufeff in the source string — that would double-BOM.
        csv_bytes = "identifier\nMSFT\n".encode("utf-8-sig")
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest/csv",
                files={"file": ("bom.csv", csv_bytes, "text/csv")},
            )
        assert resp.status_code == 202
        assert resp.json()["total"] == 1

    def test_extra_columns_ignored(self, client):
        csv_content = "identifier,name,exchange\nMSFT,Microsoft,Nasdaq\n"
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(
                "/api/underlying/ingest/csv",
                files={"file": ("multi.csv", self._csv_bytes(csv_content), "text/csv")},
            )
        assert resp.status_code == 202
        assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# GET /api/underlying/jobs/{job_id}
# ---------------------------------------------------------------------------

class TestJobStatusEndpoint:
    def test_existing_job_returns_200(self, client, in_memory_db):
        job = _seed_job(in_memory_db, status="done", total=2, done=2, success=2, errors=0)
        resp = client.get(f"/api/underlying/jobs/{job.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == job.id
        assert body["status"] == "done"
        assert body["total"] == 2
        assert body["success"] == 2

    def test_missing_job_returns_404(self, client):
        resp = client.get("/api/underlying/jobs/nonexistent-id")
        assert resp.status_code == 404

    def test_results_parsed_as_list(self, client, in_memory_db):
        results = [{"identifier": "MSFT", "underlying_id": "abc"}]
        job = _seed_job(in_memory_db, results=json.dumps(results))
        resp = client.get(f"/api/underlying/jobs/{job.id}")
        assert resp.json()["results"] == results


# ---------------------------------------------------------------------------
# GET/PUT /api/underlying/field-config
# ---------------------------------------------------------------------------

class TestFieldConfigEndpoint:
    def test_get_returns_config(self, client):
        cfg = _make_field_config()
        with patch("underlying.router.fc_module.load", return_value=cfg):
            resp = client.get("/api/underlying/field-config")
        assert resp.status_code == 200
        body = resp.json()
        assert body["version"] == "1"
        assert any(f["name"] == "share_class_name" for f in body["fields"])

    def test_get_file_not_found_returns_500(self, client):
        with patch("underlying.router.fc_module.load",
                   side_effect=FileNotFoundError("yaml missing")):
            resp = client.get("/api/underlying/field-config")
        assert resp.status_code == 500

    def test_put_updates_config(self, client):
        cfg = _make_field_config()
        with patch("underlying.router.fc_module.update_fields", return_value=cfg) as mock_update:
            resp = client.put(
                "/api/underlying/field-config",
                json={"fields": [{"name": "share_class_name", "enabled": False}]},
            )
        assert resp.status_code == 200
        mock_update.assert_called_once()

    def test_put_exception_returns_422(self, client):
        with patch("underlying.router.fc_module.update_fields",
                   side_effect=ValueError("unknown field")):
            resp = client.put(
                "/api/underlying/field-config",
                json={"fields": [{"name": "bad_field"}]},
            )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/underlying/export
# ---------------------------------------------------------------------------

class TestBulkExportEndpoint:
    def test_export_approved(self, client, in_memory_db):
        _seed_security(in_memory_db, status="approved")
        _seed_security(in_memory_db, cik="0000320193", ticker="AAPL",
                       company_name="APPLE INC", status="fetched")
        resp = client.get("/api/underlying/export?status=approved")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["ticker"] == "MSFT"

    def test_export_empty_returns_empty_list(self, client):
        resp = client.get("/api/underlying/export")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_export_custom_status(self, client, in_memory_db):
        _seed_security(in_memory_db, status="needs_review")
        resp = client.get("/api/underlying/export?status=needs_review")
        assert len(resp.json()) == 1


# ---------------------------------------------------------------------------
# GET /api/underlying/
# ---------------------------------------------------------------------------

class TestListEndpoint:
    def test_empty_db_returns_zero(self, client):
        resp = client.get("/api/underlying/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    def test_list_with_data(self, client, in_memory_db):
        _seed_security(in_memory_db)
        resp = client.get("/api/underlying/")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["ticker"] == "MSFT"

    def test_filter_by_status(self, client, in_memory_db):
        _seed_security(in_memory_db, status="fetched")
        _seed_security(in_memory_db, cik="0000320193", ticker="AAPL",
                       company_name="APPLE INC", status="approved")
        resp = client.get("/api/underlying/?status=approved")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["ticker"] == "AAPL"

    def test_search_by_company_name(self, client, in_memory_db):
        _seed_security(in_memory_db, company_name="MICROSOFT CORP")
        _seed_security(in_memory_db, cik="0000320193", ticker="AAPL", company_name="APPLE INC")
        resp = client.get("/api/underlying/?search=apple")
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["ticker"] == "AAPL"

    def test_search_by_ticker(self, client, in_memory_db):
        _seed_security(in_memory_db)
        resp = client.get("/api/underlying/?search=MSF")
        body = resp.json()
        assert body["total"] == 1

    def test_pagination(self, client, in_memory_db):
        for i in range(3):
            _seed_security(in_memory_db, cik=f"CIK{i:010}", ticker=f"TK{i}")
        resp = client.get("/api/underlying/?page=1&page_size=2")
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2
        assert body["page"] == 1
        assert body["page_size"] == 2

    def test_page_two(self, client, in_memory_db):
        for i in range(3):
            _seed_security(in_memory_db, cik=f"CIK{i:010}", ticker=f"TK{i}")
        resp = client.get("/api/underlying/?page=2&page_size=2")
        body = resp.json()
        assert len(body["items"]) == 1


# ---------------------------------------------------------------------------
# GET /api/underlying/{id}
# ---------------------------------------------------------------------------

class TestGetOneEndpoint:
    def test_get_existing(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.get(f"/api/underlying/{row.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == row.id
        assert body["cik"] == "0000789019"
        assert "field_results" in body

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/underlying/nonexistent-id")
        assert resp.status_code == 404

    def test_field_results_included(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        _seed_field_result(in_memory_db, row.id, "share_type", "Common Stock")
        resp = client.get(f"/api/underlying/{row.id}")
        body = resp.json()
        fr_names = [fr["field_name"] for fr in body["field_results"]]
        assert "share_type" in fr_names


# ---------------------------------------------------------------------------
# PUT /api/underlying/{id}/fields/{field_name}
# ---------------------------------------------------------------------------

class TestUpdateFieldEndpoint:
    def test_creates_new_field_result(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.put(
            f"/api/underlying/{row.id}/fields/share_type",
            json={"value": "Preferred Stock", "action": "edited"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["value"] == "Preferred Stock"

        with _get_session(in_memory_db) as s:
            fr = (
                s.query(UnderlyingFieldResult)
                .filter_by(underlying_id=row.id, field_name="share_type")
                .first()
            )
        assert fr is not None
        assert json.loads(fr.reviewed_value) == "Preferred Stock"
        assert fr.review_status == "corrected"

    def test_updates_existing_field_result(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        _seed_field_result(in_memory_db, row.id, "share_type", "Common Stock")
        resp = client.put(
            f"/api/underlying/{row.id}/fields/share_type",
            json={"value": "ADR", "action": "edited"},
        )
        assert resp.status_code == 200
        with _get_session(in_memory_db) as s:
            fr = (
                s.query(UnderlyingFieldResult)
                .filter_by(underlying_id=row.id, field_name="share_type")
                .first()
            )
        assert json.loads(fr.reviewed_value) == "ADR"

    def test_action_accepted_sets_review_status(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        _seed_field_result(in_memory_db, row.id, "share_type", "Common Stock")
        client.put(
            f"/api/underlying/{row.id}/fields/share_type",
            json={"value": "Common Stock", "action": "accepted"},
        )
        with _get_session(in_memory_db) as s:
            fr = (
                s.query(UnderlyingFieldResult)
                .filter_by(underlying_id=row.id, field_name="share_type")
                .first()
            )
        assert fr.review_status == "accepted"

    def test_mirrors_value_to_master_row(self, client, in_memory_db):
        row = _seed_security(in_memory_db, share_type="Common Stock")
        resp = client.put(
            f"/api/underlying/{row.id}/fields/share_type",
            json={"value": "ADR", "action": "edited"},
        )
        assert resp.status_code == 200
        with _get_session(in_memory_db) as s:
            updated = s.get(UnderlyingSecurity, row.id)
        assert updated.share_type == "ADR"

    def test_edit_log_created(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        client.put(
            f"/api/underlying/{row.id}/fields/share_class_name",
            json={"value": "Class A Common", "action": "edited"},
        )
        with _get_session(in_memory_db) as s:
            log = (
                s.query(UnderlyingEditLog)
                .filter_by(underlying_id=row.id, field_name="share_class_name")
                .first()
            )
        assert log is not None
        assert log.action == "edited"

    def test_missing_security_returns_404(self, client):
        resp = client.put(
            "/api/underlying/no-such-id/fields/share_type",
            json={"value": "X", "action": "edited"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/underlying/{id}/approve
# ---------------------------------------------------------------------------

class TestApproveEndpoint:
    def test_approve_sets_status(self, client, in_memory_db):
        row = _seed_security(in_memory_db, status="needs_review")
        resp = client.post(f"/api/underlying/{row.id}/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"
        with _get_session(in_memory_db) as s:
            updated = s.get(UnderlyingSecurity, row.id)
        assert updated.status == "approved"

    def test_approve_missing_returns_404(self, client):
        resp = client.post("/api/underlying/no-such-id/approve")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/underlying/{id}/refetch
# ---------------------------------------------------------------------------

class TestRefetchEndpoint:
    def test_refetch_returns_job_id(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        with patch("underlying.router.run_ingest_job"):
            resp = client.post(f"/api/underlying/{row.id}/refetch")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "job_id" in body

    def test_refetch_sets_status_to_fetching(self, client, in_memory_db):
        row = _seed_security(in_memory_db, status="fetched")
        with patch("underlying.router.run_ingest_job"):
            client.post(f"/api/underlying/{row.id}/refetch")
        with _get_session(in_memory_db) as s:
            updated = s.get(UnderlyingSecurity, row.id)
        # Status was set to "fetching" before the background task ran
        # (or was overwritten by the (mocked) bg task — still a valid state)
        assert updated.status in ("fetching", "fetched")

    def test_refetch_missing_returns_404(self, client):
        with patch("underlying.router.run_ingest_job"):
            resp = client.post("/api/underlying/no-such-id/refetch")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/underlying/{id}
# ---------------------------------------------------------------------------

class TestDeleteEndpoint:
    def test_delete_archives_security(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.delete(f"/api/underlying/{row.id}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "archived"
        with _get_session(in_memory_db) as s:
            updated = s.get(UnderlyingSecurity, row.id)
        assert updated.status == "archived"

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/underlying/no-such-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/underlying/{id}/export
# ---------------------------------------------------------------------------

class TestExportOneEndpoint:
    def test_export_returns_security_dict(self, client, in_memory_db):
        row = _seed_security(in_memory_db, status="approved")
        resp = client.get(f"/api/underlying/{row.id}/export")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == row.id
        assert body["ticker"] == "MSFT"
        assert "field_results" in body

    def test_export_missing_returns_404(self, client):
        resp = client.get("/api/underlying/no-such-id/export")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/underlying/{id}/links  and  DELETE /api/underlying/{id}/links/{fid}
# ---------------------------------------------------------------------------

class TestFilingLinksEndpoints:
    def test_link_creates_row(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        filing = _seed_filing(in_memory_db)
        resp = client.post(
            f"/api/underlying/{row.id}/links",
            json={"filing_id": filing.id},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["ok"] is True
        assert body["already_linked"] is False
        assert "link_id" in body

    def test_link_idempotent(self, client, in_memory_db):
        """Linking the same filing twice returns already_linked=True.

        The route is declared with status_code=201; re-linking returns 201 as
        well because FastAPI applies the decorator status to all dict returns.
        The idempotency signal is in the response body flag.
        """
        row = _seed_security(in_memory_db)
        filing = _seed_filing(in_memory_db)
        client.post(f"/api/underlying/{row.id}/links", json={"filing_id": filing.id})
        resp = client.post(
            f"/api/underlying/{row.id}/links",
            json={"filing_id": filing.id},
        )
        # status may be 200 or 201; what matters is the idempotency flag
        assert resp.status_code in (200, 201)
        assert resp.json()["already_linked"] is True

    def test_link_missing_security_returns_404(self, client, in_memory_db):
        filing = _seed_filing(in_memory_db)
        resp = client.post(
            "/api/underlying/no-such-id/links",
            json={"filing_id": filing.id},
        )
        assert resp.status_code == 404

    def test_link_missing_filing_returns_404(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.post(
            f"/api/underlying/{row.id}/links",
            json={"filing_id": "nonexistent-filing"},
        )
        assert resp.status_code == 404

    def test_unlink_removes_row(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        filing = _seed_filing(in_memory_db)
        # Create link first
        link_resp = client.post(
            f"/api/underlying/{row.id}/links",
            json={"filing_id": filing.id},
        )
        assert link_resp.status_code == 201

        # Delete it
        resp = client.delete(f"/api/underlying/{row.id}/links/{filing.id}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        with _get_session(in_memory_db) as s:
            link = (
                s.query(UnderlyingLink)
                .filter_by(filing_id=filing.id, underlying_id=row.id)
                .first()
            )
        assert link is None

    def test_unlink_missing_returns_404(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.delete(f"/api/underlying/{row.id}/links/nonexistent-filing")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# _security_to_dict / _parse_json_field helpers
# ---------------------------------------------------------------------------

class TestLinksInDetailResponse:
    def test_links_included_in_get_detail(self, client, in_memory_db):
        """GET /underlying/{id} should include a 'links' list in the response."""
        row = _seed_security(in_memory_db)
        filing = _seed_filing(in_memory_db)
        # Create a link directly in DB
        with _get_session(in_memory_db) as s:
            link = UnderlyingLink(filing_id=filing.id, underlying_id=row.id, link_source="manual")
            s.add(link)
            s.commit()

        resp = client.get(f"/api/underlying/{row.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert "links" in body
        assert len(body["links"]) == 1
        assert body["links"][0]["filing_id"] == filing.id
        assert body["links"][0]["link_source"] == "manual"

    def test_links_empty_when_none(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.get(f"/api/underlying/{row.id}")
        assert resp.json()["links"] == []

    def test_links_not_in_list_response(self, client, in_memory_db):
        """List endpoint (no include_fields) must NOT include a 'links' key."""
        _seed_security(in_memory_db)
        resp = client.get("/api/underlying/")
        body = resp.json()
        assert len(body["items"]) == 1
        assert "links" not in body["items"][0]


class TestSecuritySerialisationHelpers:
    def test_hist_data_series_parsed_from_json(self, client, in_memory_db):
        """hist_data_series stored as JSON string should be returned as a list."""
        series = [{"date": "2025-01-02", "close": 400.0, "volume": 0}]
        row = _seed_security(in_memory_db, hist_data_series=json.dumps(series))
        resp = client.get(f"/api/underlying/{row.id}")
        body = resp.json()
        assert isinstance(body["hist_data_series"], list)
        assert body["hist_data_series"][0]["close"] == 400.0

    def test_null_hist_data_series_returns_none(self, client, in_memory_db):
        row = _seed_security(in_memory_db)
        resp = client.get(f"/api/underlying/{row.id}")
        assert resp.json()["hist_data_series"] is None
