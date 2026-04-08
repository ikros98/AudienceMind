from __future__ import annotations

import hmac

from fastapi import HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import Settings


bearer_scheme = HTTPBearer(auto_error=False)


def get_auth_dependency(settings: Settings):
    async def require_bearer_token(
        credentials: HTTPAuthorizationCredentials | None,
    ) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing bearer token",
            )

        if not hmac.compare_digest(credentials.credentials, settings.bearer_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid bearer token",
            )

    return require_bearer_token
