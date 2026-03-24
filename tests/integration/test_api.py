"""
Integration tests for the running FastAPI backend.

Requires the server to be running on http://localhost:8000.
Tests are skipped automatically if the server is unreachable.
"""
import json
import time
import unittest

import httpx

BASE = "http://localhost:8000"
TIMEOUT = 10.0


def _server_available() -> bool:
    try:
        httpx.get(f"{BASE}/api/health", timeout=3.0)
        return True
    except Exception:
        return False


@unittest.skipUnless(_server_available(), "Backend server not running on :8000")
class TestHealthEndpoint(unittest.TestCase):

    def test_health_returns_ok(self):
        r = httpx.get(f"{BASE}/api/health", timeout=TIMEOUT)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")

    def test_health_lists_prism_models(self):
        r = httpx.get(f"{BASE}/api/health", timeout=TIMEOUT)
        body = r.json()
        self.assertIn("prism_models", body)
        self.assertIsInstance(body["prism_models"], list)
        self.assertGreater(len(body["prism_models"]), 0)

    def test_health_anthropic_key_set(self):
        r = httpx.get(f"{BASE}/api/health", timeout=TIMEOUT)
        body = r.json()
        self.assertTrue(body.get("anthropic_key_set"),
                        "ANTHROPIC_API_KEY must be configured")


@unittest.skipUnless(_server_available(), "Backend server not running on :8000")
class TestDocsManifest(unittest.TestCase):

    def setUp(self):
        self.r = httpx.get(f"{BASE}/api/docs/manifest", timeout=TIMEOUT)

    def test_returns_200(self):
        self.assertEqual(self.r.status_code, 200)

    def test_has_categories(self):
        body = self.r.json()
        self.assertIn("categories", body)
        self.assertIsInstance(body["categories"], list)
        self.assertGreater(len(body["categories"]), 0)

    def test_guides_category_present(self):
        body = self.r.json()
        keys = [c["key"] for c in body["categories"]]
        self.assertIn("guides", keys)

    def test_each_file_has_required_fields(self):
        body = self.r.json()
        for cat in body["categories"]:
            for f in cat.get("files", []):
                self.assertIn("name", f, f"Missing 'name' in {f}")
                self.assertIn("url",  f, f"Missing 'url' in {f}")
                self.assertIn("last_modified", f, f"Missing 'last_modified' in {f}")
                self.assertIn("abstract", f, f"Missing 'abstract' in {f}")

    def test_markdown_urls_start_with_docs(self):
        body = self.r.json()
        for cat in body["categories"]:
            for f in cat.get("files", []):
                if f.get("type") == "markdown":
                    self.assertTrue(
                        f["url"].startswith("/docs/"),
                        f"Markdown URL should start with /docs/: {f['url']}"
                    )

    def test_html_docs_accessible(self):
        """HTML docs referenced in the manifest should be fetchable."""
        body = self.r.json()
        for cat in body["categories"]:
            if cat["key"] == "guides":
                for f in cat["files"]:
                    url = BASE + f["url"]
                    r = httpx.get(url, timeout=TIMEOUT)
                    self.assertEqual(
                        r.status_code, 200,
                        f"Expected 200 for {url}, got {r.status_code}"
                    )


@unittest.skipUnless(_server_available(), "Backend server not running on :8000")
class TestDocsChat(unittest.TestCase):

    def test_chat_returns_reply(self):
        payload = {"message": "What is the Expert view?", "history": []}
        r = httpx.post(f"{BASE}/api/docs/chat", json=payload, timeout=30.0)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("reply", body)
        self.assertIsInstance(body["reply"], str)
        self.assertGreater(len(body["reply"]), 10)

    def test_chat_respects_history(self):
        history = [
            {"role": "user",      "content": "What does Ingest do?"},
            {"role": "assistant", "content": "Ingest fetches 424B2 filings from SEC EDGAR."},
        ]
        payload = {"message": "And Extract?", "history": history}
        r = httpx.post(f"{BASE}/api/docs/chat", json=payload, timeout=30.0)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn("reply", body)


@unittest.skipUnless(_server_available(), "Backend server not running on :8000")
class TestFilingsEndpoint(unittest.TestCase):

    def test_filings_list_returns_array(self):
        r = httpx.get(f"{BASE}/api/filings", timeout=TIMEOUT)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIsInstance(body, list)

    def test_each_filing_has_required_fields(self):
        r = httpx.get(f"{BASE}/api/filings", timeout=TIMEOUT)
        filings = r.json()
        if not filings:
            self.skipTest("No filings in database")
        for f in filings[:5]:  # spot-check first 5
            for field in ("id", "cusip", "status"):
                self.assertIn(field, f, f"Missing '{field}' in filing {f.get('id')}")

    def test_extraction_field_schema(self):
        """Extracted field records use extracted_value (not 'value')."""
        r = httpx.get(f"{BASE}/api/filings", timeout=TIMEOUT)
        filings = r.json()
        extracted = [f for f in filings if f.get("status") == "extracted"]
        if not extracted:
            self.skipTest("No extracted filings in database")
        fid = extracted[0]["id"]
        r2 = httpx.get(f"{BASE}/api/filings/{fid}", timeout=TIMEOUT)
        detail = r2.json()
        fields = detail.get("fields", [])
        if fields:
            # Field records must use 'extracted_value' not 'value'
            self.assertIn("extracted_value", fields[0],
                          "Field records must have 'extracted_value' key")
            self.assertIn("field_name", fields[0])

    def test_filing_detail_reachable(self):
        r = httpx.get(f"{BASE}/api/filings", timeout=TIMEOUT)
        filings = r.json()
        if not filings:
            self.skipTest("No filings in database")
        fid = filings[0]["id"]
        r2 = httpx.get(f"{BASE}/api/filings/{fid}", timeout=TIMEOUT)
        self.assertEqual(r2.status_code, 200)
        detail = r2.json()
        self.assertIn("id", detail)


@unittest.skipUnless(_server_available(), "Backend server not running on :8000")
class TestStaticDocs(unittest.TestCase):
    """Verify the /docs static mount serves files correctly."""

    def test_user_manual_html(self):
        r = httpx.get(f"{BASE}/docs/user_manual.html", timeout=TIMEOUT)
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/html", r.headers.get("content-type", ""))

    def test_index_html(self):
        r = httpx.get(f"{BASE}/docs/index.html", timeout=TIMEOUT)
        self.assertEqual(r.status_code, 200)

    def test_shared_markdown_js(self):
        r = httpx.get(f"{BASE}/docs/js/markdown.js", timeout=TIMEOUT)
        self.assertEqual(r.status_code, 200)
        self.assertIn("renderMarkdown", r.text)

    def test_architecture_html(self):
        r = httpx.get(f"{BASE}/docs/architecture.html", timeout=TIMEOUT)
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
