#!/usr/bin/env python3
"""
Backfill image downloads for already-ingested filings.

Calls POST /api/filings/{id}/fetch-images for every filing in the database
that does not yet have a 'images' key in its metadata.json, or where the
images list is empty.

Usage:
    cd EDGAR-Extraction_Mapping
    python3 scripts/backfill_images.py [--all]

Options:
    --all   Re-run for every filing regardless of whether images were already
            downloaded (useful after adding new image-extension support).

Exit codes:
    0 — all succeeded
    1 — one or more requests failed
"""
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE         = "http://localhost:8000"
DELAY        = 0.6   # seconds between requests to respect EDGAR rate limit


def get_filings() -> list[dict]:
    try:
        with urllib.request.urlopen(f"{BASE}/api/filings", timeout=10) as r:
            return json.load(r)
    except Exception as exc:
        print(f"ERROR: Cannot reach backend at {BASE}: {exc}")
        sys.exit(1)


def needs_backfill(filing: dict, force_all: bool) -> bool:
    if force_all:
        return True
    folder = filing.get("filing_folder_path")
    if not folder:
        return True  # no folder → definitely no images
    meta_path = Path(folder) / "metadata.json"
    if not meta_path.exists():
        return True
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return not meta.get("images")  # empty list or missing key
    except Exception:
        return True


def fetch_images(filing_id: str) -> tuple[int, str | None]:
    req = urllib.request.Request(
        f"{BASE}/api/filings/{filing_id}/fetch-images",
        data=b"",
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = json.load(r)
            return data.get("count", 0), None
    except urllib.error.HTTPError as e:
        return 0, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as exc:
        return 0, str(exc)


def main() -> int:
    force_all = "--all" in sys.argv

    print("Fetching filing list from backend...", flush=True)
    filings = get_filings()
    print(f"  Total filings in DB: {len(filings)}")

    targets = [f for f in filings if needs_backfill(f, force_all)]
    print(f"  Need image backfill: {len(targets)}\n")

    if not targets:
        print("Nothing to do.")
        return 0

    ok_count      = 0
    fail_count    = 0
    total_images  = 0

    for idx, f in enumerate(targets, 1):
        fid    = f["id"]
        cusip  = f.get("cusip") or f.get("accession_number", "?")
        issuer = (f.get("issuer_name") or "")[:30]
        print(f"[{idx}/{len(targets)}] {cusip:<12} {issuer}...", end=" ", flush=True)

        count, err = fetch_images(fid)
        if err:
            print(f"❌ {err[:80]}")
            fail_count += 1
        else:
            sym = "✅" if count > 0 else "—"
            print(f"{sym} {count} image(s)")
            ok_count     += 1
            total_images += count

        time.sleep(DELAY)

    print("\n" + "=" * 60)
    print(f"Processed:   {ok_count + fail_count}")
    print(f"Images saved:{total_images}")
    print(f"Errors:      {fail_count}")

    if fail_count:
        return 1
    print("\n✅ All done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
