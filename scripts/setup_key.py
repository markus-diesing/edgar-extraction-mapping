#!/usr/bin/env python3
"""
One-time setup: store the Anthropic API key in the OS credential store.

  macOS   → Keychain
  Windows → Windows Credential Manager
  Linux   → Secret Service (GNOME Keyring / KWallet)

Run once per machine / user (venv must be activated):

    cd EDGAR-Extraction_Mapping
    source backend/.venv/bin/activate   # or .venv\\Scripts\\activate on Windows
    python scripts/setup_key.py

The key is never written to any file. The backend reads it automatically on
every startup via backend/credential_loader.py.

To update the key (e.g. after rotation), simply run this script again.
To remove the key from the keyring:
    python -c "import keyring; keyring.delete_password('edgar-extraction', 'anthropic_api_key')"
"""
import getpass
import sys

_SERVICE  = "edgar-extraction"
_USERNAME = "anthropic_api_key"


def main() -> None:
    # ── Check dependency ───────────────────────────────────────────────────────
    try:
        import keyring  # type: ignore[import]
    except ImportError:
        print("ERROR: 'keyring' package is not installed.")
        print("Activate the backend venv first, then run:")
        print("    pip install keyring")
        sys.exit(1)

    # ── Prompt ────────────────────────────────────────────────────────────────
    print()
    print("EDGAR Extraction — Anthropic API Key Setup")
    print("=" * 45)
    print(f"  Keyring service : {_SERVICE}")
    print(f"  Keyring username: {_USERNAME}")
    print()

    existing = keyring.get_password(_SERVICE, _USERNAME)
    if existing:
        print("A key is already stored for this service.")
        overwrite = input("Overwrite it? [y/N]: ").strip().lower()
        if overwrite != "y":
            print("Aborted — existing key unchanged.")
            sys.exit(0)
        print()

    key = getpass.getpass("Paste your Anthropic API key (input hidden): ").strip()

    if not key:
        print("ERROR: No key entered. Aborted.")
        sys.exit(1)

    if not key.startswith("sk-ant-"):
        print("WARNING: Key does not start with 'sk-ant-' — storing anyway.")
        print("         Double-check you pasted the correct value.")

    # ── Store ─────────────────────────────────────────────────────────────────
    try:
        keyring.set_password(_SERVICE, _USERNAME, key)
    except Exception as exc:
        print(f"ERROR: Could not store key in OS keyring: {exc}")
        print()
        print("On Windows, try: pip install pywin32")
        print("On Linux without a desktop session, set the key via:")
        print("    export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    # ── Verify round-trip ─────────────────────────────────────────────────────
    stored = keyring.get_password(_SERVICE, _USERNAME)
    if stored != key:
        print("ERROR: Verification failed — stored value does not match. Try again.")
        sys.exit(1)

    print()
    print("Key stored successfully in the OS keyring.")
    print("Start the backend normally — no 'export' command needed:")
    print()
    print("    uvicorn main:app --reload --port 8000")
    print()


if __name__ == "__main__":
    main()
