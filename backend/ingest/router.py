"""
Ingest API routes.

POST /api/ingest/search   — search EDGAR for 424B2 filings
POST /api/ingest/filing   — ingest (download + persist) a specific filing
GET  /api/filings         — list all ingested filings
GET  /api/filings/{id}    — get one filing record
DELETE /api/filings/{id}  — delete a filing record (and its local files)
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

import config
import database
import schema_loader
from ingest import edgar_client

log = logging.getLogger(__name__)
router = APIRouter(tags=["ingest"])


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str = Field(..., description="CUSIP or free-text search term")
    start_date: str | None = Field(None, description="YYYY-MM-DD")
    end_date:   str | None = Field(None, description="YYYY-MM-DD")
    page_size:  int        = Field(10, ge=1, le=10)
    offset:     int        = Field(0, ge=0)


class SearchHit(BaseModel):
    accession_number: str
    entity_name: str
    filing_date: str
    form_type: str
    cik: str
    cusip_hint: str | None       # from CUSIP mapping if query matched
    known_payout_type: str | None


class SearchResponse(BaseModel):
    total: int
    hits: list[SearchHit]


class IngestRequest(BaseModel):
    accession_number: str = Field(..., description="EDGAR accession number, with or without dashes")
    cik: str               = Field(..., description="Company CIK (no leading zeros required)")
    cusip: str | None      = None
    issuer_name: str | None = None
    filing_date: str | None = None
    edgar_filing_url: str | None = None
    source_url: str | None = Field(None, description="Direct URL to the 424B2 HTML (skips index lookup)")


class FilingRecord(BaseModel):
    id: str
    cusip: str | None
    accession_number: str
    issuer_name: str | None
    filing_date: str | None
    status: str
    payout_type_id: str | None
    classification_confidence: float | None
    ingest_timestamp: str
    filing_folder_path: str | None
    title_excerpt: str | None = None
    product_features: dict | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _filing_to_record(f: database.Filing) -> FilingRecord:
    product_features = None
    if f.classification_product_features:
        try:
            product_features = json.loads(f.classification_product_features)
        except Exception:
            pass
    return FilingRecord(
        id=f.id,
        cusip=f.cusip,
        accession_number=f.accession_number,
        issuer_name=f.issuer_name,
        filing_date=f.filing_date,
        status=f.status,
        payout_type_id=f.payout_type_id,
        classification_confidence=f.classification_confidence,
        ingest_timestamp=f.ingest_timestamp,
        filing_folder_path=f.filing_folder_path,
        title_excerpt=f.classification_title_excerpt or None,
        product_features=product_features,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/ingest/search", response_model=SearchResponse)
def search_edgar(req: SearchRequest):
    """Search EDGAR full-text for 424B2 filings matching the query."""
    cusip_mapping = schema_loader.load_cusip_mapping()
    known = cusip_mapping.get(req.query.strip().upper())

    try:
        hits_data = edgar_client.search_424b2(
            query=req.query,
            start_date=req.start_date,
            end_date=req.end_date,
            page_size=req.page_size,
            offset=req.offset,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"EDGAR search failed: {exc}")

    total = hits_data.get("total", {}).get("value", 0)
    hits: list[SearchHit] = []
    for h in hits_data.get("hits", []):
        src = h.get("_source", {})

        # The EDGAR EFTS API has evolved its response shape over time.
        # Current format (2025+): adsh, ciks (list), display_names (list).
        # Legacy format: accession_no, file_num (str), entity_name.
        # Handle both defensively.

        # Accession number: prefer 'adsh', fall back to 'accession_no',
        # then strip the ':filename' suffix from '_id'.
        acc = (
            src.get("adsh")
            or src.get("accession_no")
            or h.get("_id", "").split(":")[0]
        )

        # Entity name: prefer first entry of 'display_names' (strip CIK suffix),
        # fall back to 'entity_name'.
        display_names = src.get("display_names") or []
        if display_names:
            # e.g. "Goldman Sachs Group Inc  (GS, ...)  (CIK 0000886982)"
            entity = display_names[0].split("  (")[0].strip()
        else:
            entity = src.get("entity_name", "")

        # CIK: prefer first entry of 'ciks', fall back to extracting from 'file_num'.
        ciks = src.get("ciks") or []
        if ciks:
            cik = str(ciks[0]).lstrip("0") or str(ciks[0])
        else:
            fn = src.get("file_num", "")
            if isinstance(fn, list):
                fn = fn[0] if fn else ""
            cik = str(fn).split("-")[0] if fn else ""

        hits.append(SearchHit(
            accession_number=acc,
            entity_name=entity,
            filing_date=src.get("file_date", ""),
            form_type=src.get("file_type") or src.get("form_type", "424B2"),
            cik=cik,
            cusip_hint=known.cusip if known else None,
            known_payout_type=known.payout_type_id if known else None,
        ))

    return SearchResponse(total=total, hits=hits)


@router.post("/ingest/filing", response_model=FilingRecord, status_code=201)
def ingest_filing(req: IngestRequest):
    """
    Download and persist a 424B2 filing.

    If source_url is provided, downloads directly.
    Otherwise looks up the filing index on EDGAR to find the primary HTML document.
    Skips ingestion if the accession_number is already in the database.
    """
    acc = req.accession_number.strip()
    acc_nodash = acc.replace("-", "")
    # Normalise: add dashes if missing (18 digits → XXXXXXXXXX-YY-ZZZZZZ)
    if "-" not in acc and len(acc_nodash) == 18:
        acc = f"{acc_nodash[:10]}-{acc_nodash[10:12]}-{acc_nodash[12:]}"

    # Check duplicate
    with database.get_session() as session:
        existing = session.query(database.Filing).filter_by(accession_number=acc).first()
        if existing:
            return _filing_to_record(existing)

    # Determine download URL
    source_url = req.source_url
    cik = req.cik.lstrip("0") or req.cik

    if not source_url:
        # Try CUSIP mapping first
        cusip_mapping = schema_loader.load_cusip_mapping()
        cusip_key = (req.cusip or "").strip().upper()
        if cusip_key and cusip_key in cusip_mapping:
            mapped = cusip_mapping[cusip_key]
            url = mapped.source_url
            if url and url.lower().endswith((".htm", ".html")):
                source_url = url

    html_bytes: bytes
    content_type: str
    ingest_started_at = _now()   # start of EDGAR download

    if source_url:
        try:
            html_bytes, content_type = edgar_client.download_raw_url(source_url)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download filing from URL: {exc}")
    else:
        # Fetch filing index then pick the primary HTML document
        try:
            documents = edgar_client.get_filing_index(cik, acc)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to fetch filing index: {exc}")

        primary = edgar_client.find_primary_html_document(documents)
        if not primary:
            raise HTTPException(
                status_code=422,
                detail="No HTML document found in filing index. PDF-only filings are not supported in v1.",
            )
        if edgar_client.is_pdf_content_type(primary.get("type", "")):
            raise HTTPException(status_code=422, detail="PDF-only filing — not supported in v1.")

        doc_name = primary["name"]
        try:
            html_bytes, content_type = edgar_client.download_document(cik, acc, doc_name)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Failed to download document: {exc}")

    if edgar_client.is_pdf_content_type(content_type):
        raise HTTPException(status_code=422, detail="PDF filing — not supported in v1.")

    # Decode HTML
    html_str = edgar_client.decode_html(html_bytes)

    # Persist to disk
    folder: Path = config.filing_folder(acc)
    folder.mkdir(parents=True, exist_ok=True)

    raw_html_path = folder / "raw.html"
    raw_html_path.write_text(html_str, encoding="utf-8")

    # Download images referenced by the filing HTML from the same EDGAR folder.
    # Non-fatal: failures are logged; ingest continues regardless.
    images = edgar_client.download_filing_images(html_str, cik, acc, folder)
    if images:
        log.info("Downloaded %d image(s) for %s: %s", len(images), acc, images)

    # Also try to save the index page
    if not source_url:
        try:
            idx_bytes, _ = edgar_client.download_document(cik, acc, f"{acc}-index.htm")
            (folder / "index.htm").write_bytes(idx_bytes)
        except Exception:
            pass   # non-fatal

    # Build metadata
    now = _now()
    metadata = {
        "cusip":            req.cusip,
        "cik":              cik,
        "accession_number": acc,
        "issuer_name":      req.issuer_name,
        "filing_date":      req.filing_date,
        "edgar_filing_url": req.edgar_filing_url or source_url,
        "ingest_timestamp": now,
        "images":           images,   # filenames saved alongside raw.html
    }
    (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    # Relative paths (relative to project root)
    rel_folder = str(folder.relative_to(config.PROJECT_ROOT))
    rel_html   = str(raw_html_path.relative_to(config.PROJECT_ROOT))

    # Persist to DB
    filing = database.Filing(
        id=str(uuid.uuid4()),
        cusip=req.cusip,
        cik=cik,
        accession_number=acc,
        issuer_name=req.issuer_name,
        filing_date=req.filing_date,
        edgar_filing_url=req.edgar_filing_url or source_url,
        filing_folder_path=rel_folder,
        raw_html_path=rel_html,
        ingest_timestamp=now,
        ingest_started_at=ingest_started_at,
        status="ingested",
    )

    with database.get_session() as session:
        session.add(filing)
        session.commit()
        session.refresh(filing)
        record = _filing_to_record(filing)

    log.info("Filing ingested: %s  cusip=%s", acc, req.cusip)
    return record


@router.get("/filings", response_model=list[FilingRecord])
def list_filings(
    status: str | None = None,
    payout_type: str | None = None,
    cusip: str | None = None,
):
    """List all filings, with optional filters."""
    with database.get_session() as session:
        q = session.query(database.Filing)
        if status:
            q = q.filter(database.Filing.status == status)
        if payout_type:
            q = q.filter(database.Filing.payout_type_id == payout_type)
        if cusip:
            q = q.filter(database.Filing.cusip == cusip.upper())
        filings = q.order_by(database.Filing.ingest_timestamp.desc()).all()
        return [_filing_to_record(f) for f in filings]


@router.get("/filings/{filing_id}", response_model=FilingRecord)
def get_filing(filing_id: str):
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        return _filing_to_record(f)


@router.post("/filings/{filing_id}/fetch-images")
def fetch_filing_images(filing_id: str):
    """
    (Re-)download all images referenced in a filing's HTML from the EDGAR folder.
    Safe to call on already-ingested filings — skips files already on disk.
    Returns the list of image filenames now present in the filing folder.
    """
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        if not f.raw_html_path:
            raise HTTPException(status_code=404, detail="Filing has no HTML path")
        cik = f.cik or ""
        acc = f.accession_number or ""
        abs_html = config.PROJECT_ROOT / f.raw_html_path
        abs_folder = config.PROJECT_ROOT / f.filing_folder_path if f.filing_folder_path else abs_html.parent

    if not abs_html.exists():
        raise HTTPException(status_code=404, detail="Filing HTML not found on disk")

    html_str = abs_html.read_text(encoding="utf-8", errors="replace")
    images   = edgar_client.download_filing_images(html_str, cik, acc, abs_folder)

    # Patch metadata.json with the updated image list
    meta_path = abs_folder / "metadata.json"
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
        meta["images"] = images
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception as exc:
        log.warning("Could not update metadata.json for %s: %s", filing_id, exc)

    log.info("fetch-images %s: %d image(s) on disk", acc, len(images))
    return {"filing_id": filing_id, "images": images, "count": len(images)}


class ClassificationOverrideRequest(BaseModel):
    payout_type_id: str = Field(..., description="PRISM model ID to assign")
    reason: str | None  = Field(None, description="Optional explanation for the override")


@router.post("/filings/{filing_id}/reset-classification", response_model=FilingRecord)
def reset_classification(filing_id: str):
    """
    Reset a filing back to 'ingested' status, clearing all classification data.
    Allows re-running the classifier or applying a manual override.
    Blocked if status is 'extracted', 'approved', or 'exported' — re-extract first.
    """
    BLOCKED = {"extracted", "approved", "exported"}
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        if f.status in BLOCKED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot reset classification on a filing with status '{f.status}'. "
                       "Re-extract or unapprove first.",
            )
        f.status                          = "ingested"
        f.payout_type_id                  = None
        f.classification_confidence       = None
        f.matched_schema_version          = None
        f.classified_at                   = None
        f.classification_title_excerpt    = None
        f.classification_product_features = None
        session.commit()
        session.refresh(f)
        record = _filing_to_record(f)
    log.info("Classification reset for filing %s", filing_id)
    return record


@router.post("/filings/{filing_id}/classify-override", response_model=FilingRecord)
def classify_override(filing_id: str, req: ClassificationOverrideRequest):
    """
    Manually set the PRISM model for a filing without running the classifier.
    Sets status to 'classified' with confidence=1.0 and records the override reason
    in the ClassificationFeedback table for audit purposes.
    Blocked on 'approved' or 'exported' — unapprove first.
    """
    BLOCKED = {"approved", "exported"}
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        if f.status in BLOCKED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot override classification on status '{f.status}'. Unapprove first.",
            )

        original_type = f.payout_type_id or "unknown"

        f.payout_type_id            = req.payout_type_id
        f.classification_confidence = 1.0   # manual override = maximum confidence
        f.classified_at             = _now()
        # Move to classified regardless of current state (ingested / classified /
        # needs_review / extracted all allowed)
        if f.status not in {"extracted"}:
            f.status = "classified"

        # Record the override in feedback table for audit trail
        feedback = database.ClassificationFeedback(
            filing_id             = filing_id,
            original_payout_type  = original_type,
            corrected_payout_type = req.payout_type_id,
            correction_reason     = req.reason or "manual override via UI",
            corrected_by          = "ui",
        )
        session.add(feedback)
        session.commit()
        session.refresh(f)
        record = _filing_to_record(f)

    log.info(
        "Classification overridden for %s: %s → %s (reason: %s)",
        filing_id, original_type, req.payout_type_id, req.reason,
    )
    return record


@router.get("/filings/{filing_id}/text")
def get_filing_text(filing_id: str):
    """Return the stripped plain text of a filing (what Claude processed)."""
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        if not f.raw_html_path:
            raise HTTPException(status_code=404, detail="Filing document path not set")
        abs_path = config.PROJECT_ROOT / f.raw_html_path
        if not abs_path.exists():
            raise HTTPException(status_code=404, detail="Filing file not found on disk")

    html = abs_path.read_text(encoding="utf-8", errors="replace")
    text = edgar_client.strip_html(html)
    return {"text": text, "char_count": len(text)}


# ---------------------------------------------------------------------------
# Highlight script injected into every served filing document.
# The iframe posts { type: 'highlight', text: '...' } or { type: 'clear' }.
# ---------------------------------------------------------------------------
_HIGHLIGHT_SCRIPT = r"""
(function () {
  'use strict';

  function clearHighlights() {
    document.querySelectorAll('mark[data-hl]').forEach(function (m) {
      var p = m.parentNode;
      while (m.firstChild) p.insertBefore(m.firstChild, m);
      p.removeChild(m);
      try { p.normalize(); } catch (e) {}
    });
  }

  function findAndHighlight(needle) {
    clearHighlights();
    if (!needle || needle.length < 5) return;

    // Build a flat list of visible text nodes.
    var walker = document.createTreeWalker(
      document.body,
      NodeFilter.SHOW_TEXT,
      {
        acceptNode: function (node) {
          var tag = node.parentElement ? node.parentElement.tagName : '';
          if (['SCRIPT', 'STYLE', 'NOSCRIPT'].indexOf(tag) >= 0)
            return NodeFilter.FILTER_REJECT;
          return NodeFilter.FILTER_ACCEPT;
        }
      }
    );

    var nodes = [], combined = '', offsets = [], node;
    while ((node = walker.nextNode())) {
      offsets.push(combined.length);
      combined += node.textContent;
      nodes.push(node);
    }

    // 1) Exact match.
    var idx = combined.indexOf(needle);
    var matchLen = needle.length;

    // 2) Whitespace-flexible match (Claude uses spaces; filing may have newlines).
    if (idx === -1) {
      try {
        var pat = needle
          .replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
          .replace(/\s+/g, '[\\s\\S]{0,10}');
        var re = new RegExp(pat);
        var m = re.exec(combined);
        if (m) { idx = m.index; matchLen = m[0].length; }
      } catch (e) {}
    }

    // 3) Truncated prefix fallback (40 chars).
    if (idx === -1 && needle.length > 40) {
      var prefix = needle.substring(0, 40);
      idx = combined.indexOf(prefix);
      matchLen = prefix.length;
    }

    if (idx === -1) return;

    var endIdx = idx + matchLen;

    // Find the text node containing the start position.
    var startNI = 0;
    for (var i = 0; i < offsets.length - 1; i++) {
      if (offsets[i] <= idx && offsets[i + 1] > idx) { startNI = i; break; }
      if (i === offsets.length - 2) startNI = offsets.length - 1;
    }

    // Find the text node containing the end position.
    var endNI = startNI;
    for (var j = startNI; j < offsets.length; j++) {
      endNI = j;
      if (j + 1 >= offsets.length || offsets[j + 1] >= endIdx) break;
    }

    var startOff = idx - offsets[startNI];
    var endOff   = Math.min(endIdx - offsets[endNI], nodes[endNI].textContent.length);

    function makeMark() {
      var mk = document.createElement('mark');
      mk.setAttribute('data-hl', '1');
      mk.style.backgroundColor = '#fef08a';
      mk.style.outline = '2px solid #ca8a04';
      mk.style.borderRadius = '2px';
      return mk;
    }

    try {
      var range = document.createRange();
      range.setStart(nodes[startNI], startOff);
      range.setEnd(nodes[endNI], endOff);
      var mark = makeMark();
      range.surroundContents(mark);
      mark.scrollIntoView({ behavior: 'smooth', block: 'center' });
    } catch (e) {
      // surroundContents fails when range crosses element boundaries.
      // Fall back: highlight only within the start node.
      try {
        var sLen = Math.min(needle.length, nodes[startNI].textContent.length - startOff);
        if (sLen > 0) {
          var r2 = document.createRange();
          r2.setStart(nodes[startNI], startOff);
          r2.setEnd(nodes[startNI], startOff + sLen);
          var m2 = makeMark();
          r2.surroundContents(m2);
          m2.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
      } catch (e2) {}
    }
  }

  window.addEventListener('message', function (e) {
    if (!e.data) return;
    if (e.data.type === 'highlight') findAndHighlight(e.data.text);
    if (e.data.type === 'clear')     clearHighlights();
  });
})();
"""


@router.get("/filings/{filing_id}/document", response_class=HTMLResponse)
def get_filing_document(filing_id: str):
    """
    Serve the raw 424B2 HTML filing with two injections:
      1. <base href="...edgar.gov/..."> so relative images load from EDGAR.
      2. A postMessage listener script for excerpt highlighting in the expert view.
    """
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        if not f.raw_html_path:
            raise HTTPException(status_code=404, detail="Filing document path not set")
        cik          = f.cik or ""
        acc          = f.accession_number or ""
        abs_path     = config.PROJECT_ROOT / f.raw_html_path

    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="Filing file not found on disk")

    html = abs_path.read_text(encoding="utf-8", errors="replace")

    # Build the EDGAR base URL so relative resources (images, CSS) resolve correctly.
    acc_nodash = acc.replace("-", "")
    base_url   = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"

    injection = (
        f'<base href="{base_url}">\n'
        f'<script>\n{_HIGHLIGHT_SCRIPT}\n</script>\n'
    )

    # Inject right after <head> (case-insensitive), or prepend if no head tag.
    head_match = re.search(r"<head[^>]*>", html, re.IGNORECASE)
    if head_match:
        pos  = head_match.end()
        html = html[:pos] + "\n" + injection + html[pos:]
    else:
        html = injection + html

    return HTMLResponse(content=html)


def _cost_for_row(row) -> float:
    """
    Calculate USD cost for a single api_usage_log row using model-specific pricing
    from config.CLAUDE_MODEL_REGISTRY.  Falls back to the default model's pricing
    for any row whose model field is absent or unrecognised.

    Prompt caching changes the effective rate:
      - Regular input tokens : full input_price_per_m
      - Cache-write tokens   : 1.25× input (cache population overhead)
      - Cache-read tokens    : 0.10× input (cache hit — the cost saving)
    """
    pricing = config.CLAUDE_MODEL_REGISTRY.get(
        row.model or "",
        config.CLAUDE_MODEL_REGISTRY[config.CLAUDE_MODEL_DEFAULT],
    )
    regular_in = max(
        0,
        (row.prompt_tokens   or 0)
        - (row.cache_read_tokens  or 0)
        - (row.cache_write_tokens or 0),
    )
    return (
        regular_in                       * pricing["input_price_per_m"]  / 1_000_000
        + (row.cache_write_tokens or 0)  * pricing["cache_write_per_m"]  / 1_000_000
        + (row.cache_read_tokens  or 0)  * pricing["cache_read_per_m"]   / 1_000_000
        + (row.completion_tokens  or 0)  * pricing["output_price_per_m"] / 1_000_000
    )


@router.get("/filings/{filing_id}/kpis")
def get_filing_kpis(filing_id: str):
    """Return timing and token-cost KPIs for a filing."""
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")

        # Ingest timing
        ingest: dict[str, Any] = {}
        if f.ingest_started_at and f.ingest_timestamp:
            try:
                start = datetime.fromisoformat(f.ingest_started_at)
                end   = datetime.fromisoformat(f.ingest_timestamp)
                ingest = {
                    "started_at":       f.ingest_started_at,
                    "ended_at":         f.ingest_timestamp,
                    "duration_seconds": round((end - start).total_seconds(), 2),
                }
            except Exception:
                pass

        # API usage — fetch all rows for this filing, then aggregate by group.
        # Classifier writes call_type="classify_stage1" and "classify_stage2".
        # Extractor writes call_type="extract" (single-call) or
        # "extract_{section}" per section (sectioned mode).
        # We aggregate both groups into combined totals.
        usage_rows = (
            session.query(database.ApiUsageLog)
            .filter_by(filing_id=filing_id)
            .order_by(database.ApiUsageLog.called_at.asc())
            .all()
        )

        def _aggregate(rows, prefix: str) -> dict | None:
            """Sum tokens/duration for all rows whose call_type starts with prefix."""
            matching = [r for r in rows if r.call_type.startswith(prefix)]
            if not matching:
                return None
            total_in    = sum(r.prompt_tokens     or 0 for r in matching)
            total_out   = sum(r.completion_tokens or 0 for r in matching)
            total_dur   = sum(r.duration_seconds  or 0 for r in matching)
            cache_read  = sum(r.cache_read_tokens  or 0 for r in matching)
            cache_write = sum(r.cache_write_tokens or 0 for r in matching)
            cost        = round(sum(_cost_for_row(r) for r in matching), 6)
            # Savings = what cache-read tokens would have cost at full input rate minus what they did cost
            pricing = config.CLAUDE_MODEL_REGISTRY.get(
                matching[0].model or "",
                config.CLAUDE_MODEL_REGISTRY[config.CLAUDE_MODEL_DEFAULT],
            )
            cache_savings = round(
                cache_read * (pricing["input_price_per_m"] - pricing["cache_read_per_m"]) / 1_000_000, 6
            )
            return {
                "called_at":        matching[0].called_at,
                "duration_seconds": round(total_dur, 2) if total_dur else None,
                "input_tokens":     total_in,
                "output_tokens":    total_out,
                "cache_read_tokens":  cache_read,
                "cache_write_tokens": cache_write,
                "cost_usd":         cost,
                "cache_savings_usd": cache_savings,
                "call_count":       len(matching),
            }

        classification = _aggregate(usage_rows, "classify")
        extraction     = _aggregate(usage_rows, "extract")

    return {
        "filing_id":      filing_id,
        "ingest":         ingest or None,
        "classification": classification,
        "extraction":     extraction,
    }


@router.delete("/filings/{filing_id}", status_code=204)
def delete_filing(filing_id: str):
    """Delete a filing record and its local files."""
    with database.get_session() as session:
        f = session.get(database.Filing, filing_id)
        if not f:
            raise HTTPException(status_code=404, detail="Filing not found")
        folder_path = f.filing_folder_path
        session.delete(f)
        session.commit()

    if folder_path:
        abs_path = config.PROJECT_ROOT / folder_path
        if abs_path.exists():
            shutil.rmtree(abs_path)
