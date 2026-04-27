"""
Microsoft Entra ID (Azure AD) token validation for FastAPI.

Every incoming request must carry a valid Bearer token issued by Entra.
The JWKS public keys are fetched once and cached for JWKS_TTL_SECONDS.
"""
import time
import logging
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient, PyJWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

import config

log = logging.getLogger("auth")

_bearer = HTTPBearer(auto_error=True)

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
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict[str, Any]:
    """Validate the Entra Bearer token and return its claims.

    Raises HTTP 401 if the token is missing, expired, or has wrong audience/issuer.
    Raises HTTP 503 if Entra config is not set (deployment misconfiguration).
    """
    if not config.AZURE_TENANT_ID or not config.AZURE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Entra SSO not configured — set AZURE_TENANT_ID and AZURE_CLIENT_ID.",
        )

    token = credentials.credentials
    try:
        signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
        # Entra access tokens for custom scopes carry aud = "api://<client-id>"
        # (the Application ID URI).  Accept both forms so the check works
        # whether or not the "api://" prefix was used when registering the app.
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=[
                config.AZURE_CLIENT_ID,
                f"api://{config.AZURE_CLIENT_ID}",
            ],
            issuer=f"https://login.microsoftonline.com/{config.AZURE_TENANT_ID}/v2.0",
        )
    except PyJWTError as exc:
        log.warning("Token validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return claims
