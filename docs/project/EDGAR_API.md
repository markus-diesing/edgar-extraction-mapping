# EDGAR_API.md
# SEC EDGAR — API Reference & Filing Notes

> **Audience:** Claude Code (development agent)
> **Last updated:** 2026-03-18

---

## 1. Overview

The SEC EDGAR system provides free, unauthenticated public APIs for searching and retrieving filings. No API key is required. All requests must include a valid `User-Agent` header identifying the application and a contact email (SEC requirement).

**Required User-Agent header (all requests):**
```
User-Agent: EDGAR-Extraction-Mapping/1.0 (lpa-internal-tool; contact@lpa.com)
```
Replace `contact@lpa.com` with a valid contact address before use.

---

## 2. Rate Limits

- **Hard limit:** 10 requests per second per IP address
- Exceeding this results in HTTP 429 or temporary IP block
- **Implementation requirement:** enforce a minimum 120ms delay between requests; use exponential backoff on 429 responses (1s, 2s, 4s, max 30s)
- Batch operations must be throttled accordingly

---

## 3. Key Endpoints

### 3.1 Full-Text Search API

Search the full text of EDGAR filings.

```
Base URL: https://efts.sec.gov/LATEST/search-index?
```

**Search for 424B2 filings by text / CUSIP:**
```
GET https://efts.sec.gov/LATEST/search-index?q="{search_term}"&dateRange=custom&startdt={YYYY-MM-DD}&enddt={YYYY-MM-DD}&forms=424B2
```

**Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| `q` | string | Search query (wrap in quotes for exact match) |
| `forms` | string | Filing type filter — use `424B2` |
| `dateRange` | string | `custom` to enable date filtering |
| `startdt` | date | Start date `YYYY-MM-DD` |
| `enddt` | date | End date `YYYY-MM-DD` |
| `from` | int | Pagination offset (default 0) |
| `size` | int | Results per page (max 10, default 10) |

**Example response (abbreviated):**
```json
{
  "hits": {
    "total": { "value": 42 },
    "hits": [
      {
        "_id": "0001234567-26-000001",
        "_source": {
          "period_of_report": "2026-03-15",
          "entity_name": "Goldman Sachs Group Inc",
          "file_num": "333-198735",
          "form_type": "424B2",
          "file_date": "2026-03-15",
          "accession_no": "0001234567-26-000001"
        }
      }
    ]
  }
}
```

---

### 3.2 EDGAR Submissions API

Retrieve all filings for a known CIK (company identifier).

```
GET https://data.sec.gov/submissions/CIK{cik_padded}.json
```

- `cik_padded`: 10-digit zero-padded CIK (e.g., CIK `12345` → `CIK0000012345`)
- Returns company metadata and a list of recent filings with accession numbers, form types, and dates
- For companies with many filings, additional pages are linked in the `files` array

---

### 3.3 Filing Index

Retrieve the index of files within a specific filing.

```
GET https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type=424B2&dateb=&owner=include&count=40
```

Or directly by accession number (preferred):
```
GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number_no_dashes}/{accession_number}-index.htm
```

Example:
```
https://www.sec.gov/Archives/edgar/data/12345/000123456726000001/0001234567-26-000001-index.htm
```

---

### 3.4 Filing Document Download

Download the actual filing document (HTML).

```
GET https://www.sec.gov/Archives/edgar/data/{cik}/{accession_number_no_dashes}/{document_filename}
```

- The document filename is found in the filing index (step 3.3)
- 424B2 filings are typically delivered as a single large HTML file
- Some filings contain multiple documents; the primary document is listed first in the index

**Accession number formatting:**
- Raw: `0001234567-26-000001`
- No-dashes (for URL paths): `000123456726000001`

---

### 3.5 EDGAR Company Search (by name or ticker)

```
GET https://efts.sec.gov/LATEST/search-index?q="{company_name}"&dateRange=custom&forms=424B2
```

Or to look up a CIK by company name:
```
GET https://www.sec.gov/cgi-bin/browse-edgar?company={name}&CIK=&type=424B2&dateb=&owner=include&count=10&search_text=&action=getcompany
```

---

## 4. CUSIP Lookup

EDGAR does not provide a direct CUSIP-to-accession-number index. The recommended approach:

1. Search the full-text search API with the CUSIP as the query term: `q="{cusip}"`
2. CUSIP numbers frequently appear in the text of 424B2 filings
3. Filter results by `forms=424B2`

Note: A 424B2 may contain multiple CUSIPs (e.g., for a series of products filed together in one supplement). This is a **series filing** — see §8 below.

---

## 5. 424B2 Filing Structure

A 424B2 is a prospectus supplement filed under an existing shelf registration. Key characteristics:

- Delivered as a single HTML document (occasionally PDF; focus on HTML for v1)
- Typical sections (order varies by issuer):
  - Cover page (product name, CUSIP, ISIN, issuer, trade/settlement dates)
  - Key terms table (underlier, barrier level, coupon rate, maturity)
  - Risk factors
  - Tax treatment
  - Hypothetical payout examples
  - Issuer information
- Field values are often in structured HTML tables but sometimes in running prose
- Some issuers use proprietary templates (Goldman, MS, JPM templates differ significantly)

**Extraction implication:** The extraction prompt must be robust to layout variation across issuers. Source excerpt capture (FR-3.3) helps reviewers verify correct extraction.

---

## 6. Useful Reference URLs

| Resource | URL |
|----------|-----|
| EDGAR Full-Text Search (UI) | https://efts.sec.gov/LATEST/search-index |
| EDGAR XBRL Viewer | https://www.sec.gov/cgi-bin/viewer |
| EDGAR Filing Search (UI) | https://www.sec.gov/cgi-bin/srqsb |
| SEC EDGAR API documentation | https://www.sec.gov/developer |
| 424B2 form type description | https://www.sec.gov/fast-answers/answersform424htm.html |

---

## 7. Known Quirks

- **HTML encoding:** Some filings use non-standard character encoding. Use `chardet` or force UTF-8 with fallback to latin-1 when reading raw HTML.
- **Embedded XBRL:** Some 424B2 filings include inline XBRL tags. These can be stripped for extraction purposes (use `BeautifulSoup` with `lxml` parser).
- **File size:** Large filings can be 2–10MB of HTML. Truncate to a configurable character limit before sending to Claude API to manage token costs.
- **Redirects:** Some EDGAR URLs redirect; use `httpx` with `follow_redirects=True`.
- **PDF filings:** A minority of 424B2s are filed as PDF. Detect content type from the filing index and skip/flag in v1 (do not attempt PDF extraction in v1).

---

## 8. Series Filings (Multiple CUSIPs in One 424B2)

Some issuers file a single 424B2 supplement covering a **series** of products with different economic terms under one accession number. Each product in the series has its own CUSIP and its own set of parameters (different barrier levels, coupons, maturities, underliers).

**Risk:** Extracting a series filing as a single document will produce mixed or averaged field values — the extractor cannot reliably distinguish which parameter belongs to which CUSIP.

**Current behaviour:** The pipeline ingests the full HTML of the matching filing regardless of how many CUSIPs are embedded. PRISM expects one CUSIP → one extraction result.

**Detection:** A series filing can be identified during ingest or classification by the presence of multiple distinct CUSIP strings in the filing HTML. The ingest layer currently stores whichever CUSIP was used to search EDGAR.

**Frontend:** Series filings should be visually flagged in the filing list and detail view (e.g. a warning badge "Series filing — multiple CUSIPs detected"). The reviewer should be aware that extraction results may contain mixed parameters.

**Future work (backlog):** "Break series filing to individual datasets" — decompose a series 424B2 into N separate filing records, one per CUSIP, each containing only the relevant section of the HTML. This requires identifying the per-CUSIP sections within the document (typically separated by product headers or table rows).

*End of EDGAR_API.md*
