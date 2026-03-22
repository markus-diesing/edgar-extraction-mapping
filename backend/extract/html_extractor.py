"""
html_extractor.py — Tier 0 (registry) + Tier 1 (HTML table) extraction.

Extracts PRISM fields deterministically from filing HTML before the LLM
is involved.  Two extraction tiers:

  Tier 0 — EDGAR registry metadata (confidence = 1.0)
      Fields sourced from the DB filing record itself (CUSIP, issuer name,
      filing date) — available with certainty before any parsing.

  Tier 1 — HTML Key Terms table (confidence = 0.97)
      Parses the two-column label:value HTML table in the Key Terms section.
      Uses label_mapper to resolve label text → PRISM field path and
      field_parsers to convert raw cell text → typed Python values.

Returns a list of ExtractionField objects (same type as extractor.py uses),
tagged with source="registry" or source="html_table".

These results are merged with the LLM output in extractor.py:
  •  Tier 0/1 values overwrite the LLM value for the same field.
  •  Every conflict is logged at INFO level for analytics.
  •  Unmatched fields are left for the LLM to handle.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, NamedTuple

from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)


class LabelMiss(NamedTuple):
    """An unmatched label observed during HTML extraction."""
    label_raw:    str   # original text from the cell
    label_norm:   str   # normalized (lowercase, stripped)
    sample_value: str   # the value cell text (for context)


# Deferred import to avoid circular dependencies — extractor imports us
# and we import ExtractionField from extractor would create a cycle.
# Instead we define a parallel minimal dataclass here that extractor.py
# converts into its own ExtractionField when merging.


@dataclass
class HtmlField:
    """Minimal field result produced by the HTML extractor."""
    field_name: str
    extracted_value: Any
    confidence_score: float
    source_excerpt: str
    source: str          # "registry" | "html_table" | "html_title"
    not_found: bool = False
    validation_error: str | None = None


# ---------------------------------------------------------------------------
# Default Key Terms headings (cross-issuer fallback order)
# ---------------------------------------------------------------------------

_DEFAULT_TABLE_HEADINGS = [
    "key terms and assumptions",
    "key terms",
    "terms of the notes",
    "supplemental terms",
    "product terms",
    "offering terms",
    "summary of terms",
]

# ---------------------------------------------------------------------------
# Tier 0 — Registry metadata extraction
# ---------------------------------------------------------------------------

def extract_registry_fields(filing_record: dict[str, Any]) -> list[HtmlField]:
    """
    Return fields that can be populated from EDGAR registry metadata
    available on the Filing DB row — before any document parsing.

    Args:
        filing_record:  A plain dict with Filing row attributes:
                        {cusip, issuer_name, filing_date, cik, ...}

    Returns:
        list of HtmlField with source="registry" and confidence=1.0
    """
    results: list[HtmlField] = []

    cusip = (filing_record.get("cusip") or "").strip()
    if cusip:
        results.append(HtmlField(
            field_name="identifiers.cusip",
            extracted_value=cusip,
            confidence_score=1.0,
            source_excerpt=f"EDGAR registry CUSIP: {cusip}",
            source="registry",
        ))

    issuer = (filing_record.get("issuer_name") or "").strip()
    if issuer:
        results.append(HtmlField(
            field_name="parties.issuer.name",
            extracted_value=issuer,
            confidence_score=1.0,
            source_excerpt=f"EDGAR registry issuer: {issuer}",
            source="registry",
        ))

    return results


# ---------------------------------------------------------------------------
# Tier 1 — HTML table extraction
# ---------------------------------------------------------------------------

def _find_key_terms_table(
    soup: BeautifulSoup,
    issuer_table_heading: str | None,
) -> Tag | None:
    """
    Locate the Key Terms HTML <table> element.

    Strategy:
      1. If issuer_table_heading is given, search for a tag that contains
         that text (case-insensitive), then return its nearest ancestor/
         sibling <table>.
      2. Fall back through _DEFAULT_TABLE_HEADINGS in order.
      3. Return None if no table is found.
    """
    headings_to_try: list[str] = []
    if issuer_table_heading:
        headings_to_try.append(issuer_table_heading.lower())
    headings_to_try.extend(h for h in _DEFAULT_TABLE_HEADINGS
                           if h != (issuer_table_heading or "").lower())

    for heading_text in headings_to_try:
        table = _search_for_table_near_heading(soup, heading_text)
        if table is not None:
            log.debug("Found Key Terms table via heading %r", heading_text)
            return table

    return None


def _search_for_table_near_heading(soup: BeautifulSoup, heading_text: str) -> Tag | None:
    """
    Find a <table> that contains or immediately follows a heading tag matching
    `heading_text` (case-insensitive).

    Lookup order:
      1. A <table> whose header cell (th or first td) contains the heading.
      2. A <table> whose caption contains the heading.
      3. A <th>, <td>, or <div>/<p>/<span> containing the heading,
         then search for the nearest following or ancestor <table>.
    """
    # 1. Check table header rows
    for table in soup.find_all("table"):
        # Check first row / header cells
        first_th = table.find("th")
        if first_th and heading_text in first_th.get_text(separator=" ").lower():
            return table
        caption = table.find("caption")
        if caption and heading_text in caption.get_text(separator=" ").lower():
            return table
        # Check if any cell in the first row matches (common in Key Terms tables
        # where the heading is a full-width merged first row)
        first_row = table.find("tr")
        if first_row:
            cells = first_row.find_all(["th", "td"])
            for cell in cells:
                if heading_text in cell.get_text(separator=" ").lower():
                    return table

    # 2. Find a heading-like element and walk to nearest table
    for tag in soup.find_all(["th", "td", "div", "p", "span", "h1", "h2", "h3", "h4"]):
        if heading_text in tag.get_text(separator=" ").lower():
            # Look for a sibling or ancestor table
            candidate = _nearest_table(tag)
            if candidate is not None:
                return candidate

    return None


def _nearest_table(tag: Tag) -> Tag | None:
    """
    Walk up + forward in DOM tree to find the nearest <table> to `tag`.
    Checks: next siblings, parent next siblings, up to 3 levels.
    """
    # Check next siblings first (heading row above a table)
    for sibling in tag.next_siblings:
        if getattr(sibling, "name", None) == "table":
            return sibling

    # Walk up to ancestor and check siblings of ancestor
    parent = tag.parent
    for _ in range(3):
        if parent is None:
            break
        if getattr(parent, "name", None) == "table":
            return parent
        for sibling in parent.next_siblings:
            if getattr(sibling, "name", None) == "table":
                return sibling
        parent = parent.parent

    return None


def _extract_two_column_rows(table: Tag) -> list[tuple[str, str]]:
    """
    Extract (label, value) pairs from a two-column HTML table.

    Handles:
      - Simple <tr><td>Label</td><td>Value</td></tr>
      - Tables where the label column has a background colour (header-style)
      - Tables with colspan=2 header rows (skip those rows)
      - Rows with more than 2 data cells (skip — not a label:value row)

    Returns:
        list of (label_text, value_text) pairs — already stripped
    """
    pairs: list[tuple[str, str]] = []

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        # Skip header / full-width rows
        if len(cells) == 1:
            continue
        # For multi-column tables (>2), only process the first two columns
        label_cell  = cells[0]
        value_cell  = cells[1]

        label_text = label_cell.get_text(separator=" ", strip=True)
        value_text = value_cell.get_text(separator=" ", strip=True)

        # Skip empty rows
        if not label_text or not value_text:
            continue
        # Skip rows where both cells look like column header labels (purely short words
        # without any digit or special char in the value).  A CUSIP value like "06749FWA3"
        # contains digits so it passes through even though it's a single token.
        if (len(label_text.split()) <= 1
                and len(value_text.split()) <= 1
                and not any(c.isdigit() for c in value_text)
                and value_text.upper() == value_text):
            continue

        pairs.append((label_text, value_text))

    return pairs


def extract_from_html(
    html: str,
    issuer_hints: dict | None,
    label_map: dict[str, str],
) -> tuple[list[HtmlField], list[LabelMiss]]:
    """
    Tier 1 extraction: parse the HTML Key Terms table and return typed fields.

    Args:
        html:           Raw HTML of the filing.
        issuer_hints:   Per-issuer hints block (from hints_loader), may contain
                        `key_terms_table_heading` and `table_labels`.
        label_map:      Merged label → field_path dict from label_mapper.build_label_map().

    Returns:
        Tuple of:
          fields  — list of HtmlField with source="html_table" and confidence=0.97
          misses  — list of LabelMiss for labels that had no mapping (for miss-log persistence)

        Both lists are empty if no Key Terms table could be found or parsed.
    """
    from extract.label_mapper import resolve_label, get_parser, _norm as norm

    soup = BeautifulSoup(html, "lxml")

    issuer_heading: str | None = None
    if issuer_hints:
        issuer_heading = issuer_hints.get("key_terms_table_heading")

    table = _find_key_terms_table(soup, issuer_heading)
    if table is None:
        log.info("html_extractor: no Key Terms table found in filing HTML")
        return [], []

    pairs = _extract_two_column_rows(table)
    if not pairs:
        log.info("html_extractor: Key Terms table found but no 2-column rows extracted")
        return [], []

    log.info("html_extractor: found %d label:value rows in Key Terms table", len(pairs))

    results: list[HtmlField] = []
    misses:  list[LabelMiss] = []
    seen_fields: set[str] = set()
    seen_misses: set[str] = set()

    for raw_label, raw_value in pairs:
        field_path = resolve_label(raw_label, label_map)
        if field_path is None:
            label_n = norm(raw_label)
            if label_n not in seen_misses:
                log.debug("html_extractor: no mapping for label %r", raw_label)
                misses.append(LabelMiss(
                    label_raw=raw_label,
                    label_norm=label_n,
                    sample_value=raw_value[:200],
                ))
                seen_misses.add(label_n)
            continue

        # Avoid duplicate entries for the same field (take first match)
        if field_path in seen_fields:
            log.debug("html_extractor: duplicate field %s — keeping first", field_path)
            continue

        parser = get_parser(field_path)
        if parser is None:
            # No typed parser defined — store as raw text
            parsed_value = raw_value.strip() or None
        else:
            try:
                parsed_value = parser(raw_value)
            except Exception as exc:
                log.warning("html_extractor: parser error for %s=%r: %s", field_path, raw_value, exc)
                parsed_value = None

        if parsed_value is None:
            log.debug(
                "html_extractor: parser returned None for %s (raw=%r) — skipping",
                field_path, raw_value,
            )
            continue

        # Build a compact source excerpt
        excerpt = f"{raw_label}: {raw_value[:200]}"

        results.append(HtmlField(
            field_name=field_path,
            extracted_value=parsed_value,
            confidence_score=0.97,
            source_excerpt=excerpt,
            source="html_table",
        ))
        seen_fields.add(field_path)
        log.debug("html_extractor: %s = %r (from label %r)", field_path, parsed_value, raw_label)

    log.info(
        "html_extractor: extracted %d/%d fields; %d unmatched labels",
        len(results), len(pairs), len(misses),
    )
    return results, misses
