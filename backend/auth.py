"""
Microsoft Entra ID (Azure AD) token validation for FastAPI.

In Azure deployments (AZURE_TENANT_ID + AZURE_CLIENT_ID are set) every
incoming request must carry a valid Bearer token issued by Entra.

In local / developer mode (those env vars absent) authentication is bypassed
entirely so the app works without an SSO configuration.  The JWKS public keys
are fetched once and cached for JWKS_TTL_SECONDS.
"""
import time
import logging
from typing import Any, Optional

import httpx
import jwt
from jwt import PyJWKClient, PyJWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

log = logging.getLogger("auth")

# auto_error=False: let the dependency decide whether a missing token is an
# error rather than having HTTPBearer raise 403 unconditionally.
_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# JWKS client — lazily initialised, re-used across requests
# ---------------------------------------------------------------------------
_jwks_client: PyJWKClient | None = None
_jwks_client_created_at: float = 0.0
JWKS_TTL_SECONDS = 3600  # re-fetch keys once per hour


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client, _jwks_client_created_at
    now = time.monotonic()
    if _jwks_client is None or (now - _jwks_client_created_at) > JWKS_TTL_SECONDS:
        jwks_uri = (
            f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}"
            "/discovery/v2.0/keys"
        )
        _jwks_client = PyJWKClient(jwks_uri, cache_keys=True)
        _jwks_client_created_at = now
        log.info("JWKS client initialised for tenant %s", config.AZURE_TENANT_ID)
    return _jwks_client


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict[str, Any]:
    """Validate the Entra Bearer token and return its claims.

    * Local / dev mode (AZURE_TENANT_ID not set): returns ``{}`` — all
      requests are allowed through without a token.
    * Azure deployment: validates the Bearer token; raises HTTP 401 on failure.
    """
    if not config.AZURE_TENANT_ID or not config.AZURE_CLIENT_ID:
        # SSO not configured — local development / CI: open access.
        log.debug("Auth bypass: AZURE_TENANT_ID not configured")
        return {}

    # SSO is configured — a valid Bearer token is required.
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        # Audience: accept both the bare GUID and the "api://<client-id>" URI form.
        # Issuer: accept both v2 (login.microsoftonline.com/.../v2.0) and v1
        # (sts.windows.net/...) — the version depends on the App Registration
        # manifest's accessTokenAcceptedVersion setting (null/1 → v1, 2 → v2).
        valid_issuers = [
            f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}/v2.0",
            f"https://sts.windows.net/{config.AZURE_TENANT_ID}/",
        ]
        last_exc: PyJWTError | None = None
        claims = None
        for issuer in valid_issuers:
            try:
                claims = jwt.decode(
                    token,
                    signing_key.key,
                    algorithms=["RS256"],
                    audience=[
                        config.AZURE_CLIENT_ID,
                        f"api://{config.AZURE_CLIENT_ID}",
                    ],
                    issuer=issuer,
                )
                break
            except PyJWTError as exc:
                last_exc = exc
        if claims is None:
            raise last_exc  # type: ignore[misc]
    except PyJWTError as exc:
        log.warning("Token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return claims
