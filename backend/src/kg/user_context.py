from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import jwt
from fastapi import HTTPException

from .settings import KGSettings
from .types import UserRecord


def resolve_current_user(
    token: str,
    *,
    settings: KGSettings,
    load_users: Callable[[], dict[str, dict[str, Any]]],
    parse_datetime: Callable[[Any], datetime | None],
) -> UserRecord:
    token = token.strip()
    token_iat: datetime | None = None

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Token cannot be empty",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        decoded = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = decoded.get("sub")
        if not user_id:
            raise ValueError("No sub in token")
        token_iat = parse_datetime(decoded.get("iat")) or datetime.now(tz=UTC)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if not user_id:
        raise HTTPException(
            status_code=401,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    users = load_users()
    revoked_before = users.get("_revoked_before", {})
    if isinstance(revoked_before, dict):
        revoked_at = parse_datetime(revoked_before.get(user_id))
        if revoked_at and (token_iat is None or token_iat <= revoked_at):
            raise HTTPException(
                status_code=401,
                detail="Account was deleted. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )

    record = users.get(user_id, {})
    if isinstance(record, dict):
        linked_to = record.get("_linked_to")
        if linked_to and isinstance(revoked_before, dict):
            revoked_at = parse_datetime(revoked_before.get(linked_to))
            if revoked_at and (token_iat is None or token_iat <= revoked_at):
                raise HTTPException(
                    status_code=401,
                    detail="Account was deleted. Please sign in again.",
                    headers={"WWW-Authenticate": "Bearer"},
                )

    user_dir = settings.data_dir / "users" / user_id
    user_dir.mkdir(parents=True, exist_ok=True)

    return {
        "id": user_id,
        "dir": user_dir,
        "record": record,
        "config": record.get("config", {}) if isinstance(record, dict) else {},
    }
