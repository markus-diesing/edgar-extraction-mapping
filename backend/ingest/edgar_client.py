"""
SEC EDGAR API client.

Implements:
  - Full-text search for 424B2 filings (by CUSIP or free text)
  - Filing index retrieval
  - Filing HTML download
  - Rate limiting (≤10 req/s) and exponential-backoff retry on 429

All endpoint details from EDGAR_API.md.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import chardet
import httpx
from bs4 import BeautifulSoup

import config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SEARCH_BASE = "https://efts.sec.gov/LATEST/search-index"
SUBMISSIONS_BASE = "https://data.sec.gov/submissions"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

HEADERS = {"User-Agent": config.EDGAR_USER_AGENT}


# ---------------------------------------------------------------------------
# Rate limiter (shared across all client instances)
# ---------------------------------------------------------------------------
_last_request_time: float = 0.0


def _wait_rate_limit() -> None:
    global _last_request_time
    now = time.monotonic()
    elapsed = now - _last_request_time
    if elapsed < config.EDGAR_RATE_LIMIT_DELAY:
        time.sleep(config.EDGAR_RATE_LIMIT_DELAY - elapsed)
    _last_request_time = time.monotonic()


# ---------------------------------------------------------------------------
# Low-level HTTP helper
# ---------------------------------------------------------------------------

def _get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    """Synchronous GET with rate limiting and retry."""
    delay = config.EDGAR_RETRY_BASE_DELAY
    for attempt in range(config.EDGAR_RETRY_MAX):
        _wait_rate_limit()
        try:
            resp = httpx.get(url, params=params, headers=HEADERS, follow_redirects=True, timeout=30)
            if resp.status_code == 429:
                log.warning("EDGAR rate-limited (429), backing off %.1fs", delay)
                time.sleep(min(delay, 30))
                delay *= 2
                continue
            return resp
        except httpx.RequestError as exc:
            log.warning("Request error on attempt %d: %s", attempt + 1, exc)
            if attempt == config.EDGAR_RETRY_MAX - 1:
                raise
            time.sleep(delay)
            delay *= 2
    raise RuntimeError(f"All {config.EDGAR_RETRY_MAX} attempts failed for {url}")


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

def search_424b2(
    query: str,
    start_date: str | None = None,
    end_date: str | None = None,
    page_size: int = 10,
    offset: int = 0,
) -> dict[str, Any]:
    """
    Search EDGAR full-text for 424B2 filings.
    Returns the raw hits dict from the EDGAR search API.
    """
    params: dict[str, Any] = {
        "q": f'"{query}"',
        "forms": "424B2",
        "from": offset,
        "size": page_size,
    }
    if start_date or end_date:
        params["dateRange"] = "custom"
    if start_date:
        params["startdt"] = start_date
    if end_date:
        params["enddt"] = end_date

    log.info("EDGAR search: q=%r start=%s end=%s", query, start_date, end_date)
    resp = _get(SEARCH_BASE, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("hits", {})


# ---------------------------------------------------------------------------
# Filing index
# ---------------------------------------------------------------------------

def get_filing_index(cik: str, accession_number: str) -> list[dict[str, str]]:
    """
    Retrieve the list of documents in a filing from the EDGAR index page.
    Returns a list of dicts: [{name, type, description, url}, ...]
    """
    acc_no_dashes = accession_number.replace("-", "")
    url = f"{ARCHIVES_BASE}/{cik}/{acc_no_dashes}/{accession_number}-index.htm"
    log.info("Fetching filing index: %s", url)

    resp = _get(url)
    if resp.status_code == 404:
        # Try alternate index filename
        url2 = f"{ARCHIVES_BASE}/{cik}/{acc_no_dashes}/"
        resp = _get(url2)

    resp.raise_for_status()
    return _parse_filing_index(resp.content, resp.headers.get("content-type", ""))


def _parse_filing_index(content: bytes, content_type: str) -> list[dict[str, str]]:
    """Parse the EDGAR filing index HTML into a list of document entries."""
    encoding = _detect_encoding(content)
    soup = BeautifulSoup(content.decode(encoding, errors="replace"), "lxml")
    documents = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if "document" not in headers and "type" not in headers:
            continue
        for row in table.find_all("tr")[1:]:
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            link = cells[2].find("a") if len(cells) > 2 else None
            documents.append({
                "sequence": cells[0].get_text(strip=True) if cells else "",
                "description": cells[1].get_text(strip=True) if len(cells) > 1 else "",
                "name": link.get_text(strip=True) if link else "",
                "url": link["href"] if link and link.get("href") else "",
                "type": cells[3].get_text(strip=True) if len(cells) > 3 else "",
            })
    return documents


# ---------------------------------------------------------------------------
# Document download
# ---------------------------------------------------------------------------

def download_document(cik: str, accession_number: str, doc_filename: str) -> tuple[bytes, str]:
    """
    Download a specific document from a filing.
    Returns (raw_bytes, detected_content_type).
    """
    acc_no_dashes = accession_number.replace("-", "")
    url = f"{ARCHIVES_BASE}/{cik}/{acc_no_dashes}/{doc_filename}"
    log.info("Downloading document: %s", url)
    resp = _get(url)
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "")


def download_raw_url(url: str) -> tuple[bytes, str]:
    """Download any EDGAR URL directly (used when we have a full source URL)."""
    # Ensure the URL is absolute
    if url.startswith("sec.gov/"):
        url = "https://www." + url
    elif url.startswith("www.sec.gov/"):
        url = "https://" + url
    log.info("Downloading raw URL: %s", url)
    resp = _get(url)
    resp.raise_for_status()
    return resp.content, resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def _detect_encoding(content: bytes) -> str:
    detected = chardet.detect(content[:10_000])
    return detected.get("encoding") or "utf-8"


def decode_html(content: bytes) -> str:
    """Decode raw HTML bytes to a string, handling encoding quirks."""
    encoding = _detect_encoding(content)
    return content.decode(encoding, errors="replace")


def strip_html(html: str) -> str:
    """
    Strip HTML tags and return plain text, removing scripts/styles.
    Used to prepare text for Claude API calls.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "head", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Collapse runs of blank lines
    import re
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def is_pdf_content_type(content_type: str) -> bool:
    return "pdf" in content_type.lower()


# ---------------------------------------------------------------------------
# Image download helpers
# ---------------------------------------------------------------------------

# Maximum images to download per filing (safety cap).
MAX_IMAGES_PER_FILING = 30
# Minimum file size — skip tracking pixels and 1×1 spacers.
MIN_IMAGE_BYTES = 200
# Image file extensions we want to keep.
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".svg", ".bmp", ".webp"}


def download_filing_images(
    html_str: str,
    cik: str,
    acc: str,
    dest_folder: "Path",  # pathlib.Path — quoted to avoid circular import at module level
) -> list[str]:
    """
    Parse <img> tags from filing HTML and download images that come from the
    same EDGAR filing folder (same CIK + accession number).

    Saves each file into `dest_folder/`.  Already-present files are skipped.
    Tiny images (< MIN_IMAGE_BYTES) and non-image extensions are skipped.
    All failures are non-fatal — errors are logged; ingestion continues.

    Returns the list of filenames that are now on disk (downloaded + pre-existing).
    """
    from pathlib import Path as _Path

    acc_nodash   = acc.replace("-", "")
    filing_base  = f"{ARCHIVES_BASE}/{cik}/{acc_nodash}/"

    soup         = BeautifulSoup(html_str, "lxml")
    downloaded: list[str] = []
    seen:        set[str] = set()

    for img in soup.find_all("img", src=True):
        if len(downloaded) >= MAX_IMAGES_PER_FILING:
            log.warning("Image cap (%d) reached for %s", MAX_IMAGES_PER_FILING, acc)
            break

        src = img["src"].strip()
        if not src or src.startswith("data:"):
            continue  # skip inline data URIs

        # Resolve relative src to absolute URL
        if src.startswith("http://") or src.startswith("https://"):
            url = src
        else:
            url = filing_base + src.lstrip("/")

        # Only download from *this* filing's EDGAR folder
        if filing_base not in url:
            continue

        raw_name = url.split("/")[-1].split("?")[0]
        if not raw_name:
            continue

        suffix = _Path(raw_name).suffix.lower()
        if suffix and suffix not in IMAGE_EXTS:
            continue

        if raw_name in seen:
            continue
        seen.add(raw_name)

        dest = _Path(dest_folder) / raw_name
        if dest.exists():
            downloaded.append(raw_name)
            continue  # already on disk

        try:
            img_bytes, _ = download_raw_url(url)
            if len(img_bytes) < MIN_IMAGE_BYTES:
                log.debug("Skipping tiny image %s (%d B)", raw_name, len(img_bytes))
                continue
            dest.write_bytes(img_bytes)
            downloaded.append(raw_name)
            log.info("Image saved: %s (%d B)", raw_name, len(img_bytes))
        except Exception as exc:
            log.warning("Failed to download image %s: %s", raw_name, exc)

    return downloaded


# ---------------------------------------------------------------------------
# Resolve best HTML document from a filing index
# ---------------------------------------------------------------------------

def find_primary_html_document(documents: list[dict[str, str]]) -> dict[str, str] | None:
    """
    Given the list of documents in a filing, pick the primary 424B2 HTML document.
    Returns None if only PDF is available.
    """
    # Prefer documents explicitly typed as 424B2
    for doc in documents:
        name = doc.get("name", "")
        if name.lower().endswith((".htm", ".html")) and "424b2" in doc.get("type", "").lower():
            return doc
    # Fall back to first HTML document
    for doc in documents:
        name = doc.get("name", "")
        if name.lower().endswith((".htm", ".html")):
            return doc
    return None
