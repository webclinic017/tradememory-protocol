"""Bearer-token authentication + tenant routing for the REST surface.

Design goals
------------
- **Opt-in.** If `TRADEMEMORY_API_KEYS` is unset, all endpoints stay open
  exactly like v0.5.1. This preserves the localhost-only developer
  experience and any existing self-hosted setup.
- **Minimal.** Bearer token in `Authorization: Bearer <key>` is mapped to
  a `tenant_id`. No JWT, no OAuth, no key rotation — leave those to a
  reverse proxy or a future RBAC layer.
- **Scaffold-only.** Multi-tenant data isolation requires per-row
  `tenant_id` filtering across many queries; v0.5.2 ships the column +
  identity plumbing, not the full filtering rewrite. See LIMITATIONS.md.

Configuration
-------------
Set `TRADEMEMORY_API_KEYS` to a comma-separated list of `key:tenant_id`
pairs. Examples:

    TRADEMEMORY_API_KEYS="abc123:acme,def456:bigfund"

A bare key with no tenant uses the literal `"default"` tenant:

    TRADEMEMORY_API_KEYS="sk-test-1,sk-test-2"

Auth header
-----------
Clients send `Authorization: Bearer <key>`. The middleware attaches
`request.state.tenant_id` for downstream handlers. Anything else returns
HTTP 401.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, Optional

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

API_KEYS_ENV = "TRADEMEMORY_API_KEYS"
DEFAULT_TENANT = "default"

# Paths that bypass auth even when keys are configured. Health checks and
# OpenAPI introspection must remain reachable for monitors / Swagger.
UNAUTHENTICATED_PATHS: frozenset[str] = frozenset({
    "/health",
    "/",
    "/docs",
    "/redoc",
    "/openapi.json",
})
UNAUTHENTICATED_PREFIXES: tuple[str, ...] = (
    "/docs/",
    "/static/",
    "/assets/",
    "/dashboard-assets/",
)


@dataclass(frozen=True)
class AuthContext:
    """Per-request auth state."""

    tenant_id: str
    api_key_prefix: Optional[str]  # first 8 chars of key for log correlation
    is_anonymous: bool


# ---------------------------------------------------------------------------
# Configuration loader
# ---------------------------------------------------------------------------

def _parse_api_keys(raw: str) -> Dict[str, str]:
    """Parse the env value into a {key: tenant_id} map.

    Whitespace-tolerant. Empty entries ignored. A bare key (no colon) maps
    to the default tenant.
    """
    mapping: Dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, _, tenant = entry.partition(":")
            key = key.strip()
            tenant = tenant.strip() or DEFAULT_TENANT
        else:
            key, tenant = entry, DEFAULT_TENANT
        if key:
            mapping[key] = tenant
    return mapping


def load_api_keys() -> Dict[str, str]:
    """Load the configured key -> tenant_id map, or empty if unconfigured."""
    raw = os.environ.get(API_KEYS_ENV, "").strip()
    if not raw:
        return {}
    return _parse_api_keys(raw)


def auth_enabled() -> bool:
    """True iff at least one API key is configured."""
    return bool(load_api_keys())


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Parse 'Bearer <token>' header value. Returns the token, or None."""
    if not authorization:
        return None
    parts = authorization.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def require_auth(request: Request) -> AuthContext:
    """FastAPI dependency: enforce bearer-token auth if configured.

    Behaviour:
      - No keys configured (`TRADEMEMORY_API_KEYS` unset/empty) →
        anonymous access, tenant=`default`. Backwards-compatible with
        v0.5.1.
      - Keys configured + valid header → returns AuthContext with the
        mapped tenant_id.
      - Keys configured + missing/invalid header → HTTPException 401.

    The result is also stashed on `request.state.auth` for handlers that
    want it without re-declaring the dependency.
    """
    keys = load_api_keys()
    if not keys:
        ctx = AuthContext(
            tenant_id=DEFAULT_TENANT, api_key_prefix=None, is_anonymous=True
        )
        request.state.auth = ctx
        return ctx

    token = _extract_bearer(request.headers.get("Authorization"))
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed Authorization: Bearer header.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant = keys.get(token)
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    ctx = AuthContext(
        tenant_id=tenant,
        api_key_prefix=token[:8],
        is_anonymous=False,
    )
    request.state.auth = ctx
    return ctx


# ---------------------------------------------------------------------------
# ASGI middleware — single integration point for the FastAPI app
# ---------------------------------------------------------------------------

def _path_is_exempt(path: str) -> bool:
    if path in UNAUTHENTICATED_PATHS:
        return True
    return any(path.startswith(p) for p in UNAUTHENTICATED_PREFIXES)


class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Global bearer-token gate.

    No-op when `TRADEMEMORY_API_KEYS` is unset (preserves v0.5.1 behaviour).
    When configured, every non-exempt path must carry a valid bearer key.

    The middleware attaches `request.state.auth = AuthContext(...)` so
    downstream handlers can read `request.state.auth.tenant_id`. In
    unconfigured mode every request sees a default-tenant anonymous
    context — handlers can still write tenant_id without conditional code.
    """

    async def dispatch(self, request: Request, call_next):
        keys = load_api_keys()

        if not keys:
            request.state.auth = AuthContext(
                tenant_id=DEFAULT_TENANT,
                api_key_prefix=None,
                is_anonymous=True,
            )
            return await call_next(request)

        if _path_is_exempt(request.url.path):
            request.state.auth = AuthContext(
                tenant_id=DEFAULT_TENANT,
                api_key_prefix=None,
                is_anonymous=True,
            )
            return await call_next(request)

        token = _extract_bearer(request.headers.get("Authorization"))
        if not token:
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Missing or malformed Authorization: Bearer header."
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        tenant = keys.get(token)
        if tenant is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid API key."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        request.state.auth = AuthContext(
            tenant_id=tenant,
            api_key_prefix=token[:8],
            is_anonymous=False,
        )
        return await call_next(request)
