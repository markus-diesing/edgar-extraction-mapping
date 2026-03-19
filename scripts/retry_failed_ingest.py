#!/usr/bin/env python3
"""
Retry ingestion for CUSIPs that failed due to EDGAR 503 maintenance downtime.

Run this script when SEC.gov maintenance is over (typically off-peak 21:00–06:00 ET):

    cd EDGAR-Extraction_Mapping
    python3 scripts/retry_failed_ingest.py

The script:
  1. Checks which CUSIPs are still missing from the DB
  2. Searches EDGAR for each missing CUSIP
  3. Ingests the first matching filing
  4. Respects EDGAR's rate limit (one request every 0.5 s by default)

Exit codes:
  0 — all CUSIPs ingested (or already existed / no EDGAR hits)
  1 — some CUSIPs still failed after retries
"""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://localhost:8000"

# All target CUSIPs (the full 10-per-issuer target set)
TARGET_CUSIPS: dict[str, list[str]] = {
    "Bank of Montreal":    ["06376F6U8","06376F6R5","06376FAE9","06376FBH1","06376F6V6"],
    # Barclays: original target set + 3 additional CUSIPs found in DB during testing
    "Barclays":            ["06749FWP0","06749GBY2","06749FWA3","06749GBC0","06749G6H5","06749GBE6","06749G6G7",
                            "06749G7G6","06749GA56","06749GBT3"],
    "Citigroup":           ["17332UG26","17332UV86","17332UX27","17332UY26","17332UG59","17291W4Z1","17332UW93"],
    # Goldman Sachs: prefix 40447C CUSIPs resolve to HSBC USA INC /MD/ in EDGAR (CUSIP prefix overlap).
    # Keep for diagnostic ingestion; confirmed Goldman CUSIPs use prefix 40058Q / 40058J.
    "Goldman Sachs":       ["40447CXJ4","40058JSZ9","40058JWH4","40058JWZ4","40447CWJ5","40447CWH9","40447CWK2",
                            "09711JQH5","40058Q3Z0","40447CWP1"],
    "JPMorgan Chase":      ["48136G6Q8","48136G3L2","48134V828"],
    "JPMorgan Financial":  ["46660RAG9","46660R7A6","46660RD50","46660RDQ4","46660RDP6","46660RCS1","46660RCM4"],
    "UBS AG":              ["90310EEJ0","90310EGE9","90310EGF6","90310EEV3","90304W558","90310EGJ8","90265W2X7"],
    # Wells Fargo: original set + 3 additional CUSIPs found in DB.
    # NOTE: 95001DP87 is "Fixed Rate Callable Notes" — no underlying, unconditional issuer optional redemption.
    #       Ingest it for availability but exclude from extraction until callable note schema model is added.
    "Wells Fargo":         ["95001DP95","95001DPB0","95001DP87","95001DPA2","95001DPC8","95001DP38","95001DP46",
                            "95001DP79","95001HJH5","95001HJJ1"],
}

DELAY_SECONDS = 0.5   # between EDGAR requests (~2 req/s, well within 10 req/s cap)
MAX_RETRIES   = 3


def post(path: str, payload: dict) -> tuple[dict | None, str | None]:
    data = json.dumps(payload).encode()
    req  = urllib.request.Request(
        f"{BASE}{path}", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r), None
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return None, str(e)


def get_existing_cusips() -> set[str]:
    try:
        with urllib.request.urlopen(f"{BASE}/api/filings", timeout=10) as r:
            return {f["cusip"] for f in json.load(r) if f.get("cusip")}
    except Exception as e:
        print(f"ERROR: Could not reach backend at {BASE}: {e}")
        sys.exit(1)


def ingest_one(cusip: str, issuer: str) -> str:
    """Try to ingest a single CUSIP. Returns status string."""
    for attempt in range(1, MAX_RETRIES + 1):
        resp, err = post("/api/ingest/search", {"query": cusip})
        if err:
            if attempt < MAX_RETRIES:
                time.sleep(2 ** attempt)
                continue
            return f"search_error: {err[:60]}"

        hits = (resp or {}).get("hits", [])
        if not hits:
            return "no_edgar_hits"

        hit = hits[0]
        acc    = hit.get("accession_number", "")
        cik    = hit.get("cik", "")
        entity = hit.get("entity_name", "")
        time.sleep(DELAY_SECONDS)

        resp2, err2 = post("/api/ingest/filing", {
            "accession_number": acc,
            "cik":              cik,
            "cusip":            cusip,
            "issuer_name":      entity or issuer,
            "filing_date":      hit.get("filing_date", ""),
        })
        if err2:
            if "503" in err2 and attempt < MAX_RETRIES:
                wait = 5 * (2 ** attempt)
                print(f"    503 on attempt {attempt}, waiting {wait}s...", flush=True)
                time.sleep(wait)
                continue
            return f"ingest_error: {err2[:60]}"

        return (resp2 or {}).get("status", "ingested")

    return "max_retries_exceeded"


def main() -> int:
    print("Checking backend...", flush=True)
    existing = get_existing_cusips()
    print(f"  Currently stored: {len(existing)} CUSIPs\n")

    all_target = [(cusip, issuer)
                  for issuer, cusips in TARGET_CUSIPS.items()
                  for cusip in cusips]
    missing = [(c, i) for c, i in all_target if c not in existing]

    if not missing:
        print("✅ All target CUSIPs are already ingested. Nothing to do.")
        return 0

    print(f"Missing: {len(missing)} CUSIPs to ingest\n")
    results: list[tuple[str, str, str]] = []

    for idx, (cusip, issuer) in enumerate(missing, 1):
        print(f"[{idx}/{len(missing)}] {cusip} ({issuer})...", flush=True)
        status = ingest_one(cusip, issuer)
        sym = "✅" if status in ("ingested", "already_exists") else (
              "ℹ" if status == "no_edgar_hits" else "❌")
        print(f"  {sym} {status}", flush=True)
        results.append((cusip, issuer, status))
        time.sleep(DELAY_SECONDS)

    # Summary
    print("\n" + "=" * 70)
    ok      = [r for r in results if r[2] in ("ingested", "already_exists")]
    no_hits = [r for r in results if r[2] == "no_edgar_hits"]
    failed  = [r for r in results if r[2] not in ("ingested", "already_exists", "no_edgar_hits")]

    print(f"Ingested:     {len(ok)}")
    print(f"No EDGAR hit: {len(no_hits)}")
    print(f"Failed:       {len(failed)}")

    if failed:
        print("\nStill failing:")
        for cusip, issuer, status in failed:
            print(f"  {cusip:<15} {issuer:<28} {status}")
        return 1

    print("\n✅ All done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
