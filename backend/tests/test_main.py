"""
tests/test_main.py — Tests for main.py API endpoints (health cache, chat history).

Uses FastAPI TestClient so no real Anthropic calls are made.
"""
import time
import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    """Create a TestClient for the FastAPI app.

    We patch anthropic.Anthropic so the module-level _docs_chat_client is
    constructed without a real API key.
    """
    with patch("anthropic.Anthropic"):
        import main  # noqa — import after patch
        yield TestClient(main.app)


# ---------------------------------------------------------------------------
# /api/health — cache behaviour
# ---------------------------------------------------------------------------

class TestHealthCache:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "prism_models" in body
        assert "cusip_mapping_count" in body
        assert "anthropic_key_set" in body

    def test_health_uses_cache(self, client):
        """Second call within TTL must not re-invoke schema_loader (cached)."""
        import main as m
        import schema_loader

        # Reset cache
        m._health_cache = None
        m._health_cache_at = 0.0

        with patch.object(schema_loader, "list_models", return_value=["testModel"]) as mock_models, \
             patch.object(schema_loader, "load_cusip_mapping", return_value={"A": "B"}) as mock_map:
            # First call populates cache
            r1 = client.get("/api/health")
            assert r1.status_code == 200
            assert mock_models.call_count == 1

            # Second call within TTL — schema_loader must NOT be called again
            r2 = client.get("/api/health")
            assert r2.status_code == 200
            assert mock_models.call_count == 1  # still 1

    def test_health_cache_expires(self, client):
        """After TTL, the next call must refresh."""
        import main as m
        import schema_loader

        m._health_cache = {"status": "ok", "prism_models": [], "cusip_mapping_count": 0, "anthropic_key_set": False}
        m._health_cache_at = time.monotonic() - m._HEALTH_TTL - 1.0  # force expiry

        with patch.object(schema_loader, "list_models", return_value=["refreshedModel"]) as mock_models, \
             patch.object(schema_loader, "load_cusip_mapping", return_value={}) as mock_map:
            resp = client.get("/api/health")
            assert resp.status_code == 200
            assert mock_models.call_count == 1  # refreshed


# ---------------------------------------------------------------------------
# /api/docs/chat — history parity fix
# ---------------------------------------------------------------------------

class TestDocsChatHistory:
    @pytest.fixture(autouse=True)
    def mock_anthropic(self):
        """Patch the module-level client so no real API calls are made."""
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text="Test reply")]
        with patch("main._docs_chat_client") as mock_client:
            mock_client.messages.create.return_value = mock_resp
            self.mock_client = mock_client
            yield

    def test_basic_message(self, client):
        resp = client.post("/api/docs/chat", json={"message": "Hello"})
        assert resp.status_code == 200
        assert resp.json()["reply"] == "Test reply"

    def test_history_leading_assistant_stripped(self, client):
        """If history[-10:] starts with an assistant message, it must be dropped."""
        history = [
            {"role": "assistant", "content": "I am the assistant"},  # leading assistant
            {"role": "user", "content": "previous user question"},
            {"role": "assistant", "content": "previous answer"},
        ]
        resp = client.post("/api/docs/chat", json={"message": "New question", "history": history})
        assert resp.status_code == 200
        # Verify the messages sent to the API start with a user turn
        call_args = self.mock_client.messages.create.call_args
        sent_messages = call_args.kwargs.get("messages") or call_args.args[0] if call_args.args else []
        if call_args.kwargs.get("messages"):
            sent_messages = call_args.kwargs["messages"]
        assert sent_messages[0]["role"] == "user"

    def test_history_already_starting_with_user(self, client):
        """Well-formed history (starts with user) must not be modified."""
        history = [
            {"role": "user", "content": "first question"},
            {"role": "assistant", "content": "first answer"},
        ]
        resp = client.post("/api/docs/chat", json={"message": "Second question", "history": history})
        assert resp.status_code == 200
        call_args = self.mock_client.messages.create.call_args
        sent_messages = call_args.kwargs["messages"]
        assert sent_messages[0]["role"] == "user"
        assert sent_messages[-1] == {"role": "user", "content": "Second question"}

    def test_empty_history(self, client):
        resp = client.post("/api/docs/chat", json={"message": "Hello", "history": []})
        assert resp.status_code == 200
        sent = self.mock_client.messages.create.call_args.kwargs["messages"]
        assert len(sent) == 1
        assert sent[0] == {"role": "user", "content": "Hello"}


# ---------------------------------------------------------------------------
# /api/docs/manifest
# ---------------------------------------------------------------------------

class TestDocsManifest:
    def test_returns_categories_list(self, client):
        resp = client.get("/api/docs/manifest")
        assert resp.status_code == 200
        body = resp.json()
        assert "categories" in body
        assert isinstance(body["categories"], list)
