"""
Credential loader — injects ANTHROPIC_API_KEY into os.environ from the first
available source before the rest of the application reads config.py.

Source priority:
  1. Already present in os.environ  (CI/CD pipelines, explicit shell export)
  2. OS keyring                      (macOS Keychain, Windows Credential Manager,
                                      Linux Secret Service)
  3. .env file in project root       (developer convenience fallback)

If none of the above provides a value, the function returns silently.
The server will start and work for non-AI operations; classify/extract
endpoints will surface a clear error when the key is first needed.

One-time setup:
    python scripts/setup_key.py
"""
import os
from pathlib import Path

_SERVICE   = "edgar-extraction"
_USERNAME  = "anthropic_api_key"
_KEY_NAME  = "ANTHROPIC_API_KEY"
# .env is expected at the project root (one level above backend/)
_ENV_FILE  = Path(__file__).parent.parent / ".env"


def load_api_key() -> None:
    """
    Inject ANTHROPIC_API_KEY into os.environ using the first available source.
    Safe to call before logging is configured — no logging calls are made here.
    """
    # ── 1. Already in environment ─────────────────────────────────────────────
    if os.environ.get(_KEY_NAME):
        return

    # ── 2. OS keyring ─────────────────────────────────────────────────────────
    try:
        import keyring  # type: ignore[import]
        key = keyring.get_password(_SERVICE, _USERNAME)
        if key:
            os.environ[_KEY_NAME] = key
            return
    except Exception:
        pass  # keyring unavailable or lookup failed — continue to next source

    # ── 3. .env file ──────────────────────────────────────────────────────────
    if _ENV_FILE.exists():
        try:
            from dotenv import load_dotenv  # type: ignore[import]
            load_dotenv(_ENV_FILE, override=False)
            # load_dotenv writes directly into os.environ; check again
            if os.environ.get(_KEY_NAME):
                return
        except Exception:
            pass  # python-dotenv unavailable — silently skip
