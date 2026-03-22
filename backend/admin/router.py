"""
Admin API — application log viewer and cost/usage analytics.
Mounted at /api in main.py → endpoints at /api/admin/...

Tabs served:
  GET /api/admin/logs             — tail + filter the application log file
  GET /api/admin/logs/download    — serve the full log file as a download
  GET /api/admin/usage/summary    — aggregate cost & token stats across all filings
  GET /api/admin/usage/timeline   — time-bucketed spend (day / week / month)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from sqlalchemy import text

import config
import database
import settings_store

router = APIRouter(prefix="/admin", tags=["admin"])

# Pattern matching our application log format:
#   2026-03-21 09:00:27,546  INFO      main  Database initialised …
_LOG_LINE_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+(\w+)\s+(\S+)\s+(.*)"
)

# Minimum token count for a cache block to be eligible (Anthropic requirement: ≥1024 tokens)
_CACHE_MIN_TOKENS = 1024


# ---------------------------------------------------------------------------
# Log viewer
# ---------------------------------------------------------------------------

@router.get("/logs")
def get_logs(
    lines: int = Query(default=200, ge=10, le=5000, description="Number of log entries to return (newest first)"),
    level: str = Query(default="ALL", description="Minimum level filter: ALL, INFO, WARNING, ERROR"),
    module: str = Query(default="", description="Optional substring filter on the logger name"),
):
    """
    Return recent application log entries parsed from logs/app.log.

    Lines that do not match the application log format (uvicorn access lines,
    exception tracebacks) are dropped from the output.  Multi-line tracebacks
    are appended to the preceding ERROR entry.
    """
    log_path = config.LOGS_DIR / "app.log"

    file_size = 0
    raw_lines: list[str] = []
    if log_path.exists():
        file_size = log_path.stat().st_size
        # Tail the file: read only the last chunk rather than the whole log.
        # Each structured log line is at most ~300 bytes; tracebacks add ~1-3 KB.
        # Reading 3× the target byte budget gives ample margin while avoiding
        # loading many MBs after months of use.
        tail_bytes = lines * 400  # generous per-line budget
        try:
            with open(log_path, "rb") as fh:
                fh.seek(0, 2)  # seek to end
                size = fh.tell()
                start = max(0, size - tail_bytes)
                fh.seek(start)
                chunk = fh.read().decode("utf-8", errors="replace")
            # If we seeked mid-line, drop the first (possibly partial) line
            if start > 0:
                chunk = chunk[chunk.find("\n") + 1:]
            raw_lines = chunk.splitlines()
        except OSError:
            raw_lines = []

    # Parse into structured entries (handle multi-line tracebacks)
    entries: list[dict] = []
    for raw in raw_lines:
        m = _LOG_LINE_RE.match(raw)
        if m:
            entries.append({
                "ts":      m.group(1),
                "level":   m.group(2).strip(),
                "name":    m.group(3),
                "message": m.group(4),
            })
        elif entries:
            # Continuation line (traceback) — append to last entry's message
            entries[-1]["message"] += "\n" + raw

    # Apply level filter
    _LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "CRITICAL": 4}
    min_level = _LEVEL_ORDER.get(level.upper(), 0)
    if min_level > 0:
        entries = [e for e in entries if _LEVEL_ORDER.get(e["level"], 0) >= min_level]

    # Apply module filter (case-insensitive substring)
    if module.strip():
        mod_lower = module.strip().lower()
        entries = [e for e in entries if mod_lower in e["name"].lower()]

    total = len(entries)
    # Return the N most recent entries
    entries = entries[-lines:]

    return {
        "entries":        entries,
        "total_matched":  total,
        "file_size_bytes": file_size,
        "log_path":       str(log_path.relative_to(config.PROJECT_ROOT)),
    }


@router.get("/logs/download")
def download_logs():
    """Serve the full application log file as a plain-text download."""
    log_path = config.LOGS_DIR / "app.log"
    if not log_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Log file not found")
    return FileResponse(
        path=str(log_path),
        media_type="text/plain",
        filename="edgar_app.log",
    )


# ---------------------------------------------------------------------------
# Cost & usage helpers
# ---------------------------------------------------------------------------

def _cost_for_row(row) -> float:
    """
    Compute USD cost for one api_usage_log row using model-specific pricing.
    Handles prompt caching token rates correctly.
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


def _cache_savings_for_row(row) -> float:
    """Compute how much was saved vs paying full input price for cache-read tokens."""
    pricing = config.CLAUDE_MODEL_REGISTRY.get(
        row.model or "",
        config.CLAUDE_MODEL_REGISTRY[config.CLAUDE_MODEL_DEFAULT],
    )
    saved_per_token = (
        pricing["input_price_per_m"] - pricing["cache_read_per_m"]
    ) / 1_000_000
    return (row.cache_read_tokens or 0) * saved_per_token


# Human-readable labels for call_type values stored in the database
_CALL_TYPE_LABELS: dict[str, str] = {
    "classify_stage1":       "Classify — stage 1",
    "classify_stage2":       "Classify — stage 2 (fallback overhead)",
    "extract":               "Extract — single call",
    "extract_identifiers":   "Extract — identifiers",
    "extract_product_generic": "Extract — product generic",
    "extract_underlying_terms": "Extract — underlying terms",
    "extract_protection":    "Extract — protection / barrier",
    "extract_autocall":      "Extract — autocall",
    "extract_coupon":        "Extract — coupon",
    "extract_parties":       "Extract — parties",
}


# ---------------------------------------------------------------------------
# Usage summary endpoint
# ---------------------------------------------------------------------------

@router.get("/usage/summary")
def get_usage_summary():
    """
    Return aggregate cost and token statistics across all filings.

    Sections returned:
      - totals         — lifetime spend and call counts
      - week/month     — rolling 7-day and 30-day spend
      - by_step        — cost breakdown per call_type with cache savings
      - by_payout_type — cost grouped by PRISM model (joined to filings)
      - by_issuer      — cost grouped by issuer_name
      - unit_economics — cost/filing, cost/field, ratios, cache hit rate
      - projection     — monthly run rate and per-100-filings estimate
      - model_comparison — hypothetical cost for each registry model
      - available_models — full registry for the UI model selector dropdown
      - active_model   — currently configured Claude model
    """
    now = datetime.now(timezone.utc)
    week_ago  = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    with database.get_session() as session:

        # Single left-outer-join query — avoids scanning api_usage_log twice.
        # rows_with_filing is the canonical list used for all per-row iteration.
        rows_with_filing = (
            session.query(database.ApiUsageLog, database.Filing)
            .outerjoin(database.Filing, database.ApiUsageLog.filing_id == database.Filing.id)
            .all()
        )

        if not rows_with_filing:
            return _empty_summary()

        # ------------------------------------------------------------------
        # Single pass: compute all accumulators simultaneously
        # ------------------------------------------------------------------
        total_cost     = 0.0
        total_savings  = 0.0
        total_calls    = 0
        total_in       = 0
        total_out      = 0
        total_cache_rd = 0
        total_cache_wr = 0
        filing_ids: set[str] = set()

        week_cost  = 0.0
        month_cost = 0.0
        week_filing_ids:  set[str] = set()
        month_filing_ids: set[str] = set()

        step_buckets:   dict[str, dict[str, Any]] = {}
        payout_buckets: dict[str, dict] = {}
        issuer_buckets: dict[str, dict] = {}

        classify_cost = 0.0
        stage2_cost   = 0.0

        # For model comparison: accumulate total tokens once (O(N), not O(M×N))
        total_prompt_tokens_for_cmp     = 0
        total_completion_tokens_for_cmp = 0

        for usage_row, filing in rows_with_filing:
            cost    = _cost_for_row(usage_row)
            savings = _cache_savings_for_row(usage_row)

            total_cost     += cost
            total_savings  += savings
            total_calls    += 1
            total_in       += usage_row.prompt_tokens     or 0
            total_out      += usage_row.completion_tokens or 0
            total_cache_rd += usage_row.cache_read_tokens  or 0
            total_cache_wr += usage_row.cache_write_tokens or 0
            if usage_row.filing_id:
                filing_ids.add(usage_row.filing_id)

            # Rolling windows — ISO string comparison is valid for UTC timestamps
            ts = usage_row.called_at or ""
            if ts >= week_ago:
                week_cost += cost
                if usage_row.filing_id:
                    week_filing_ids.add(usage_row.filing_id)
            if ts >= month_ago:
                month_cost += cost
                if usage_row.filing_id:
                    month_filing_ids.add(usage_row.filing_id)

            # By step
            ct = usage_row.call_type or "unknown"
            if ct not in step_buckets:
                step_buckets[ct] = {
                    "call_type":         ct,
                    "label":             _CALL_TYPE_LABELS.get(ct, ct),
                    "calls":             0,
                    "input_tokens":      0,
                    "output_tokens":     0,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "cost_usd":          0.0,
                    "cache_savings_usd": 0.0,
                }
            b = step_buckets[ct]
            b["calls"]              += 1
            b["input_tokens"]       += usage_row.prompt_tokens     or 0
            b["output_tokens"]      += usage_row.completion_tokens or 0
            b["cache_read_tokens"]  += usage_row.cache_read_tokens  or 0
            b["cache_write_tokens"] += usage_row.cache_write_tokens or 0
            b["cost_usd"]           += cost
            b["cache_savings_usd"]  += savings

            # By payout_type and issuer
            ptype  = (filing.payout_type_id if filing else None) or "unknown"
            issuer = (filing.issuer_name    if filing else None) or "Unknown"
            if ptype not in payout_buckets:
                payout_buckets[ptype] = {"payout_type_id": ptype, "calls": 0, "cost_usd": 0.0}
            payout_buckets[ptype]["calls"]    += 1
            payout_buckets[ptype]["cost_usd"] += cost
            if issuer not in issuer_buckets:
                issuer_buckets[issuer] = {"issuer_name": issuer, "calls": 0, "cost_usd": 0.0}
            issuer_buckets[issuer]["calls"]    += 1
            issuer_buckets[issuer]["cost_usd"] += cost

            # Classify cost breakdown
            if usage_row.call_type and usage_row.call_type.startswith("classify"):
                classify_cost += cost
                if usage_row.call_type == "classify_stage2":
                    stage2_cost += cost

            # Model comparison token accumulators (O(N) instead of O(M×N))
            total_prompt_tokens_for_cmp     += usage_row.prompt_tokens     or 0
            total_completion_tokens_for_cmp += usage_row.completion_tokens or 0

        total_filings = len(filing_ids)

        # ------------------------------------------------------------------
        # Finalize by_step
        # ------------------------------------------------------------------
        by_step = sorted(step_buckets.values(), key=lambda s: -s["cost_usd"])
        for s in by_step:
            s["cost_usd"]          = round(s["cost_usd"], 6)
            s["cache_savings_usd"] = round(s["cache_savings_usd"], 6)
            s["pct_of_total"]      = round(s["cost_usd"] / total_cost * 100, 1) if total_cost else 0
            s["avg_cost_per_call"] = round(s["cost_usd"] / s["calls"], 6) if s["calls"] else 0

        by_payout_type = sorted(
            [{"payout_type_id": k, "calls": v["calls"], "cost_usd": round(v["cost_usd"], 6)}
             for k, v in payout_buckets.items()],
            key=lambda x: -x["cost_usd"],
        )
        by_issuer = sorted(
            [{"issuer_name": k, "calls": v["calls"], "cost_usd": round(v["cost_usd"], 6)}
             for k, v in issuer_buckets.items()],
            key=lambda x: -x["cost_usd"],
        )

        # ------------------------------------------------------------------
        # Unit economics
        # ------------------------------------------------------------------
        total_fields_found = session.query(database.FieldResult).filter_by(not_found=False).count()

        cache_hit_rate = (
            round(total_cache_rd / max(total_in, 1) * 100, 1) if total_cache_rd else 0.0
        )

        unit_economics = {
            "cost_per_filing":        round(total_cost / total_filings, 6)       if total_filings else None,
            "cost_per_field_found":   round(total_cost / total_fields_found, 6)  if total_fields_found else None,
            "avg_input_per_filing":   round(total_in   / total_filings, 0)       if total_filings else None,
            "output_input_ratio_pct": round(total_out  / max(total_in, 1) * 100, 1),
            "classify_overhead_pct":  round(classify_cost / total_cost * 100, 1) if total_cost else 0,
            "stage2_overhead_pct":    round(stage2_cost / max(classify_cost, 0.000001) * 100, 1),
            "stage2_cost_usd":        round(stage2_cost, 6),
            "cache_hit_rate_pct":     cache_hit_rate,
            "cache_savings_usd":      round(total_savings, 6),
            "total_cache_read_tokens":  total_cache_rd,
            "total_cache_write_tokens": total_cache_wr,
        }

        # ------------------------------------------------------------------
        # Projection (based on last 30 days)
        # ------------------------------------------------------------------
        month_filings    = len(month_filing_ids)
        monthly_run_rate = round(month_cost, 4) if month_filing_ids else None
        per_100_filings  = round(total_cost / total_filings * 100, 4) if total_filings else None

        projection = {
            "monthly_run_rate_usd":    monthly_run_rate,
            "month_filings_processed": month_filings,
            "per_100_filings_usd":     per_100_filings,
            "annual_estimate_usd":     round(monthly_run_rate * 12, 2) if monthly_run_rate else None,
        }

        # ------------------------------------------------------------------
        # Model comparison — O(M+N): token totals pre-computed above, one multiply per model
        # ------------------------------------------------------------------
        model_comparison = []
        for model_id, info in config.CLAUDE_MODEL_REGISTRY.items():
            est_cost = (
                total_prompt_tokens_for_cmp     * info["input_price_per_m"]  / 1_000_000
                + total_completion_tokens_for_cmp * info["output_price_per_m"] / 1_000_000
            )
            model_comparison.append({
                "model_id":     model_id,
                "display_name": info["display_name"],
                "est_cost_usd": round(est_cost, 4),
                "delta_usd":    round(est_cost - total_cost, 4),
                "delta_pct":    round((est_cost - total_cost) / total_cost * 100, 1) if total_cost else 0,
            })

    active_model = settings_store.get_settings().get("claude_model", config.CLAUDE_MODEL_DEFAULT)

    return {
        "total_cost_usd":   round(total_cost, 4),
        "week_cost_usd":    round(week_cost, 4),
        "month_cost_usd":   round(month_cost, 4),
        "total_calls":      total_calls,
        "total_filings":    total_filings,
        "by_step":          by_step,
        "by_payout_type":   by_payout_type,
        "by_issuer":        by_issuer,
        "unit_economics":   unit_economics,
        "projection":       projection,
        "model_comparison": model_comparison,
        "available_models": [
            {
                "model_id":          mid,
                "display_name":      info["display_name"],
                "input_price_per_m": info["input_price_per_m"],
                "output_price_per_m": info["output_price_per_m"],
                "cache_write_per_m": info["cache_write_per_m"],
                "cache_read_per_m":  info["cache_read_per_m"],
                "context_tokens":    info["context_tokens"],
                "note":              info["note"],
            }
            for mid, info in config.CLAUDE_MODEL_REGISTRY.items()
        ],
        "active_model": active_model,
    }


def _empty_summary() -> dict:
    """Return a zeroed summary when no usage data exists yet."""
    active_model = settings_store.get_settings().get("claude_model", config.CLAUDE_MODEL_DEFAULT)
    return {
        "total_cost_usd": 0.0, "week_cost_usd": 0.0, "month_cost_usd": 0.0,
        "total_calls": 0, "total_filings": 0,
        "by_step": [], "by_payout_type": [], "by_issuer": [],
        "unit_economics": {}, "projection": {},
        "model_comparison": [],
        "available_models": [
            {"model_id": mid, "display_name": info["display_name"],
             "input_price_per_m": info["input_price_per_m"],
             "output_price_per_m": info["output_price_per_m"],
             "cache_write_per_m": info["cache_write_per_m"],
             "cache_read_per_m": info["cache_read_per_m"],
             "context_tokens": info["context_tokens"],
             "note": info["note"]}
            for mid, info in config.CLAUDE_MODEL_REGISTRY.items()
        ],
        "active_model": active_model,
    }


# ---------------------------------------------------------------------------
# Usage timeline endpoint
# ---------------------------------------------------------------------------

@router.get("/usage/timeline")
def get_usage_timeline(
    granularity: str = Query(default="week", description="Bucketing: day, week, or month"),
):
    """
    Return time-bucketed spend grouped by day / ISO week / month.

    Each bucket breaks spend into classify and extract categories so the
    frontend can render a stacked bar chart.
    """
    # SQLite strftime format strings per granularity
    fmt_map = {
        "day":   "%Y-%m-%d",
        "week":  "%Y-W%W",
        "month": "%Y-%m",
    }
    fmt = fmt_map.get(granularity, "%Y-W%W")

    with database.get_session() as session:
        rows = session.query(database.ApiUsageLog).order_by(
            database.ApiUsageLog.called_at.asc()
        ).all()

    if not rows:
        return {"buckets": [], "granularity": granularity}

    # Group rows into time buckets
    buckets: dict[str, dict] = {}
    for r in rows:
        if not r.called_at:
            continue
        # Parse ISO timestamp; strftime on the date portion
        try:
            dt = datetime.fromisoformat(r.called_at.replace("Z", "+00:00"))
            label = dt.strftime(fmt)
        except Exception:
            continue

        if label not in buckets:
            buckets[label] = {
                "label":            label,
                "classify_cost_usd": 0.0,
                "extract_cost_usd":  0.0,
                "cache_savings_usd": 0.0,
                "total_cost_usd":    0.0,
                "calls":             0,
            }
        b = buckets[label]
        cost    = _cost_for_row(r)
        savings = _cache_savings_for_row(r)
        b["total_cost_usd"]    += cost
        b["cache_savings_usd"] += savings
        b["calls"]             += 1
        if r.call_type and r.call_type.startswith("classify"):
            b["classify_cost_usd"] += cost
        else:
            b["extract_cost_usd"] += cost

    result = [
        {
            "label":             k,
            "classify_cost_usd": round(v["classify_cost_usd"], 6),
            "extract_cost_usd":  round(v["extract_cost_usd"],  6),
            "cache_savings_usd": round(v["cache_savings_usd"], 6),
            "total_cost_usd":    round(v["total_cost_usd"],    6),
            "calls":             v["calls"],
        }
        for k, v in sorted(buckets.items())
    ]
    return {"buckets": result, "granularity": granularity}
