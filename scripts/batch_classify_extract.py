"""
batch_classify_extract.py
─────────────────────────
Batch classify + extract runner for the full 79-filing dataset.

What it does
────────────
1. Fetches all filings from the local backend API.
2. Classifies every filing in `ingested` status (one at a time, with a
   configurable delay so the LLM calls don't hammer the API).
3. After classification, extracts every filing that ended up in `classified`
   status with confidence ≥ CLASSIFICATION_GATE_CONFIDENCE (0.80).
   Filings that fell below the gate land in `needs_review` — those are
   intentionally skipped and listed for manual follow-up.
4. Skips filings already at `extracted`, `approved`, or `exported` status
   unless --reextract is passed.
5. Prints a per-issuer summary table at the end.

Usage
─────
    # From project root, with venv activated:
    python3 scripts/batch_classify_extract.py

    # Re-extract filings that are already in 'extracted' status:
    python3 scripts/batch_classify_extract.py --reextract

    # Classify only (skip extraction step):
    python3 scripts/batch_classify_extract.py --classify-only

    # Dry-run: show what would be processed, no API calls:
    python3 scripts/batch_classify_extract.py --dry-run

Options
───────
    --base-url       Backend API base URL (default: http://localhost:8000)
    --classify-delay Seconds between classification calls (default: 2.0)
    --extract-delay  Seconds between extraction calls (default: 3.0)
    --reextract      Re-run extraction on already-extracted filings
    --classify-only  Stop after classification, skip extraction
    --dry-run        Print plan, make no API calls
"""
from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field

import requests

# ─────────────────────────────────────────────────────────────────────────────
# Config defaults
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL       = "http://localhost:8000"
CLASSIFY_DELAY_S       = 2.0   # seconds between classification API calls
EXTRACT_DELAY_S        = 3.0   # seconds between extraction API calls
CLASSIFICATION_GATE    = 0.80  # filings below this go to needs_review (no extraction)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class FilingRecord:
    id: str
    cusip: str
    issuer_name: str
    status: str
    payout_type_id: str | None
    classification_confidence: float | None


@dataclass
class RunStats:
    classify_attempted:  int = 0
    classify_ok:         int = 0
    classify_needs_review: int = 0
    classify_unknown:    int = 0
    classify_failed:     int = 0
    extract_attempted:   int = 0
    extract_ok:          int = 0
    extract_gate_blocked: int = 0
    extract_failed:      int = 0
    skipped_already_done: int = 0
    per_issuer: dict = field(default_factory=lambda: defaultdict(lambda: {
        "classified": 0, "needs_review": 0, "extracted": 0, "failed": 0,
    }))


def _get(base: str, path: str) -> dict | list:
    r = requests.get(f"{base}{path}", timeout=30)
    r.raise_for_status()
    return r.json()


def _post(base: str, path: str) -> dict:
    r = requests.post(f"{base}{path}", timeout=120)
    if r.status_code == 400:
        # classification gate or similar — non-fatal
        return {"__error__": r.json().get("detail", "blocked"), "__status__": 400}
    r.raise_for_status()
    return r.json()


def _fmt_conf(c: float | None) -> str:
    return f"{c*100:.0f}%" if c is not None else "—"


def _banner(msg: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {msg}")
    print(f"{'─'*60}")


# ─────────────────────────────────────────────────────────────────────────────
# Main runner
# ─────────────────────────────────────────────────────────────────────────────

def run(
    base_url: str,
    classify_delay: float,
    extract_delay: float,
    reextract: bool,
    classify_only: bool,
    dry_run: bool,
) -> None:
    stats = RunStats()

    # ── 0. Health check ──────────────────────────────────────────────────────
    try:
        health = _get(base_url, "/api/health")
    except Exception as exc:
        print(f"ERROR: Cannot reach backend at {base_url} — {exc}")
        sys.exit(1)

    if not health.get("anthropic_key_set"):
        print("ERROR: ANTHROPIC_API_KEY is not set in the backend. Aborting.")
        sys.exit(1)

    print(f"Backend OK · model count: {len(health.get('prism_models', []))}")

    # ── 1. Load filings ──────────────────────────────────────────────────────
    raw = _get(base_url, "/api/filings")
    all_filings = [
        FilingRecord(
            id=f["id"],
            cusip=f.get("cusip") or "—",
            issuer_name=f.get("issuer_name") or "Unknown",
            status=f["status"],
            payout_type_id=f.get("payout_type_id"),
            classification_confidence=f.get("classification_confidence"),
        )
        for f in raw
    ]

    to_classify = [f for f in all_filings if f.status == "ingested"]
    already_classified = [f for f in all_filings if f.status == "classified"]
    needs_review = [f for f in all_filings if f.status == "needs_review"]
    already_extracted = [
        f for f in all_filings if f.status in ("extracted", "approved", "exported")
    ]

    _banner("FILING STATUS SNAPSHOT")
    print(f"  ingested (→ will classify):          {len(to_classify)}")
    print(f"  classified (→ will extract):         {len(already_classified)}")
    print(f"  needs_review (→ skipped, manual):    {len(needs_review)}")
    print(f"  extracted / approved / exported:     {len(already_extracted)}")
    if reextract:
        print(f"  (--reextract: will re-run extraction on {len(already_extracted)} done filings)")

    if dry_run:
        print("\nDRY RUN — no API calls will be made.")
        print(f"\nWould classify {len(to_classify)} filings.")
        if not classify_only:
            total_extract = len(already_classified) + len(to_classify)
            if reextract:
                total_extract += len(already_extracted)
            print(f"Would extract up to {total_extract} filings (subject to gate).")
        return

    # ── 2. Classify ingested filings ─────────────────────────────────────────
    if to_classify:
        _banner(f"STEP 1 — CLASSIFY ({len(to_classify)} filings)")

    newly_classified: list[FilingRecord] = []

    for i, filing in enumerate(to_classify, 1):
        stats.classify_attempted += 1
        prefix = f"[{i:>2}/{len(to_classify)}] {filing.cusip:<12} {filing.issuer_name[:30]:<30}"

        try:
            result = _post(base_url, f"/api/classify/{filing.id}")
        except Exception as exc:
            print(f"{prefix}  ERROR: {exc}")
            stats.classify_failed += 1
            stats.per_issuer[filing.issuer_name]["failed"] += 1
            if i < len(to_classify):
                time.sleep(classify_delay)
            continue

        model   = result.get("payout_type_id", "—")
        conf    = result.get("confidence_score")
        status  = result.get("status", "—")
        stage   = result.get("classification_stage", 1)
        stage_s = f" (stage {stage})" if stage > 1 else ""
        conf_s  = _fmt_conf(conf)

        if status == "classified" and conf is not None and conf >= CLASSIFICATION_GATE:
            marker = "✓"
            stats.classify_ok += 1
            stats.per_issuer[filing.issuer_name]["classified"] += 1
            filing.status = "classified"
            filing.payout_type_id = model
            filing.classification_confidence = conf
            newly_classified.append(filing)
        elif status == "needs_review":
            marker = "⚠"
            stats.classify_needs_review += 1
            stats.per_issuer[filing.issuer_name]["needs_review"] += 1
        elif model == "unknown":
            marker = "?"
            stats.classify_unknown += 1
            stats.per_issuer[filing.issuer_name]["needs_review"] += 1
        else:
            marker = "·"
            stats.classify_ok += 1
            stats.per_issuer[filing.issuer_name]["classified"] += 1
            filing.status = "classified"
            filing.payout_type_id = model
            filing.classification_confidence = conf
            newly_classified.append(filing)

        print(f"{prefix}  {marker} {model:<45} {conf_s}{stage_s}")

        if i < len(to_classify):
            time.sleep(classify_delay)

    # ── 3. Extract classified filings ────────────────────────────────────────
    if classify_only:
        _banner("CLASSIFY-ONLY MODE — skipping extraction")
    else:
        to_extract = already_classified + newly_classified
        if reextract:
            to_extract += already_extracted

        _banner(f"STEP 2 — EXTRACT ({len(to_extract)} filings)")

        for i, filing in enumerate(to_extract, 1):
            stats.extract_attempted += 1
            prefix = f"[{i:>2}/{len(to_extract)}] {filing.cusip:<12} {filing.issuer_name[:30]:<30}"
            conf_s = _fmt_conf(filing.classification_confidence)

            endpoint = (
                f"/api/extract/{filing.id}/reextract"
                if reextract and filing.status in ("extracted", "approved", "exported")
                else f"/api/extract/{filing.id}"
            )

            try:
                result = _post(base_url, endpoint)
            except Exception as exc:
                print(f"{prefix}  ERROR: {exc}")
                stats.extract_failed += 1
                stats.per_issuer[filing.issuer_name]["failed"] += 1
                if i < len(to_extract):
                    time.sleep(extract_delay)
                continue

            if "__error__" in result:
                err = result["__error__"]
                if "gate" in err.lower() or "confidence" in err.lower():
                    print(f"{prefix}  ⛔ gate blocked ({conf_s}): {err[:60]}")
                    stats.extract_gate_blocked += 1
                else:
                    print(f"{prefix}  ✗ blocked: {err[:80]}")
                    stats.extract_failed += 1
                if i < len(to_extract):
                    time.sleep(extract_delay)
                continue

            found = result.get("fields_found", "?")
            total = result.get("field_count", "?")
            fill  = f"{found}/{total}" if isinstance(found, int) and isinstance(total, int) else "?"
            if isinstance(found, int) and isinstance(total, int) and total > 0:
                pct = f" ({found/total*100:.0f}%)"
            else:
                pct = ""

            print(f"{prefix}  ✓ {filing.payout_type_id or '—':<40} {fill}{pct}")
            stats.extract_ok += 1
            stats.per_issuer[filing.issuer_name]["extracted"] += 1

            if i < len(to_extract):
                time.sleep(extract_delay)

    # ── 4. Summary ───────────────────────────────────────────────────────────
    _banner("RUN SUMMARY")
    print(f"  Classification:  {stats.classify_ok} ok | "
          f"{stats.classify_needs_review} needs_review | "
          f"{stats.classify_unknown} unknown | "
          f"{stats.classify_failed} failed")
    if not classify_only:
        print(f"  Extraction:      {stats.extract_ok} ok | "
              f"{stats.extract_gate_blocked} gate-blocked | "
              f"{stats.extract_failed} failed")

    if stats.classify_needs_review or stats.classify_unknown:
        _banner("NEEDS MANUAL REVIEW (skipped extraction)")
        for f in all_filings:
            if f.status == "needs_review":
                print(f"  {f.cusip:<12} {f.issuer_name[:40]:<40} conf={_fmt_conf(f.classification_confidence)}")
        for f in to_classify:
            if f.status == "ingested":  # still ingested = classify failed
                print(f"  {f.cusip:<12} {f.issuer_name[:40]:<40} CLASSIFY FAILED")

    print()
    print("  Per-issuer breakdown:")
    print(f"  {'Issuer':<40} {'Classified':>10} {'NeedsRev':>9} {'Extracted':>10} {'Failed':>7}")
    print(f"  {'─'*40} {'─'*10} {'─'*9} {'─'*10} {'─'*7}")
    for issuer, counts in sorted(stats.per_issuer.items()):
        print(f"  {issuer[:40]:<40} {counts['classified']:>10} "
              f"{counts['needs_review']:>9} {counts['extracted']:>10} {counts['failed']:>7}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Batch classify + extract all ingested filings."
    )
    parser.add_argument("--base-url",       default=DEFAULT_BASE_URL)
    parser.add_argument("--classify-delay", type=float, default=CLASSIFY_DELAY_S)
    parser.add_argument("--extract-delay",  type=float, default=EXTRACT_DELAY_S)
    parser.add_argument("--reextract",      action="store_true",
                        help="Re-run extraction on already-extracted filings")
    parser.add_argument("--classify-only",  action="store_true",
                        help="Classify only, skip extraction step")
    parser.add_argument("--dry-run",        action="store_true",
                        help="Show plan, make no API calls")
    args = parser.parse_args()

    run(
        base_url=args.base_url,
        classify_delay=args.classify_delay,
        extract_delay=args.extract_delay,
        reextract=args.reextract,
        classify_only=args.classify_only,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
