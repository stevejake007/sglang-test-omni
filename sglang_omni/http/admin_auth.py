# SPDX-License-Identifier: Apache-2.0
"""FastAPI authentication helpers for Omni admin endpoints."""

from __future__ import annotations

import hmac
import os
from typing import Awaitable, Callable

from fastapi import Header, HTTPException

ADMIN_API_KEY_ENV = "SGLANG_OMNI_ADMIN_KEY"


def resolve_admin_api_key(admin_api_key: str | None = None) -> str | None:
    """Resolve the admin API key from explicit override or environment."""
    return admin_api_key or os.environ.get(ADMIN_API_KEY_ENV) or None


def make_admin_auth_dependency(
    admin_api_key: str | None,
) -> Callable[[str | None], Awaitable[None]]:
    """Build a FastAPI dependency that enforces admin-key auth.

    Returns a no-op dependency when no key is configured (auth disabled).
    """
    if not admin_api_key:

        async def _no_auth() -> None:
            return

        return _no_auth

    async def _check_admin_key(
        authorization: str | None = Header(default=None),
    ) -> None:
        token = extract_bearer_token(authorization)
        if token is None:
            raise HTTPException(
                status_code=401,
                detail="Admin API key required: Authorization: Bearer <key>",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(
            token.encode("utf-8"),
            admin_api_key.encode("utf-8"),
        ):
            raise HTTPException(status_code=403, detail="Invalid admin API key")

    return _check_admin_key


def extract_bearer_token(authorization: str | None) -> str | None:
    """Extract the token from an Authorization: Bearer <token> header."""
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        return None
    return parts[1]


__all__ = [
    "ADMIN_API_KEY_ENV",
    "resolve_admin_api_key",
    "make_admin_auth_dependency",
    "extract_bearer_token",
]
