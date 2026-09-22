from __future__ import annotations

import secrets
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request, status


PASSWORDS = PasswordHasher()


def hash_password(password: str) -> str:
    if len(password) < 10:
        raise ValueError("password must be at least 10 characters")
    return PASSWORDS.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return PASSWORDS.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False


def issue_csrf_token(request: Request) -> str:
    token = secrets.token_urlsafe(32)
    request.session["csrf_token"] = token
    return token


def require_csrf(request: Request, form_token: str | None = None) -> None:
    expected = request.session.get("csrf_token")
    received = form_token or request.headers.get("x-csrf-token")
    if not expected or not received or not secrets.compare_digest(expected, received):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid csrf token")


def current_user(request: Request, database: Any) -> dict[str, Any] | None:
    user_id = request.session.get("user_id")
    if not isinstance(user_id, int):
        return None
    user = database.get_by_id(user_id)
    session_version = request.session.get("session_version")
    if not user or not user["enabled"] or session_version != user["session_version"]:
        request.session.clear()
        return None
    database.record_seen(user["id"])
    return user


def require_user(request: Request, database: Any) -> dict[str, Any]:
    user = current_user(request, database)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="login required")
    return user


def require_admin(request: Request, database: Any) -> dict[str, Any]:
    user = require_user(request, database)
    if user["role"] != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="administrator access required")
    return user
