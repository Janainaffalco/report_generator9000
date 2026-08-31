from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import Request, Response


COOKIE_NAME = "rg9000_session"
TTL_SECONDS = 7 * 24 * 60 * 60
_PUBLIC_API = frozenset({"/api/health", "/api/login", "/api/logout"})
_LOGIN_FAILED_DETAIL = "Senha incorreta."
UNAUTHENTICATED_DETAIL = "É preciso entrar para continuar."


def resolve_password(app_password: str | None) -> str:
    if app_password is not None:
        return app_password.strip()
    return os.environ.get("REPORT_APP_PASSWORD", "").strip()


def passwords_match(given: str, secret: str) -> bool:
    if not secret:
        return False
    given_digest = hashlib.sha256(given.encode("utf-8")).digest()
    secret_digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return hmac.compare_digest(given_digest, secret_digest)


def is_public_path(path: str) -> bool:
    if path in _PUBLIC_API or path == "/robots.txt":
        return True
    return not path.startswith("/api/")


def issue_token(secret: str) -> str:
    expiry = str(int(time.time()) + TTL_SECONDS)
    return f"{expiry}.{_sign(expiry, secret)}"


def token_is_valid(token: str | None, secret: str) -> bool:
    if not secret or not token or "." not in token:
        return False
    expiry, _, signature = token.partition(".")
    if not hmac.compare_digest(_sign(expiry, secret), signature):
        return False
    try:
        return int(expiry) >= int(time.time())
    except ValueError:
        return False


def request_is_authenticated(request: Request, secret: str) -> bool:
    return token_is_valid(request.cookies.get(COOKIE_NAME), secret)


def set_session_cookie(response: Response, secret: str) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=issue_token(secret),
        max_age=TTL_SECONDS,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def login_failed_detail() -> str:
    return _LOGIN_FAILED_DETAIL


def _sign(payload: str, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
