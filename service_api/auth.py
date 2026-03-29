from __future__ import annotations

import secrets

from typing import Optional

from fastapi import Header, HTTPException, status

from .config import SETTINGS


async def require_bearer_token(authorization: Optional[str] = Header(default=None)) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")

    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, SETTINGS.service_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token")
