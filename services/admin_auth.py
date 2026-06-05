"""
Admin authentication for the caregiver dashboard and sensitive APIs.

Credentials come from CAMMY_ADMIN_USERNAME / CAMMY_ADMIN_PASSWORD in the environment.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from urllib.parse import quote

from aiohttp import web

import config
from app_state import cookie_secure, get_state

logger = logging.getLogger(__name__)

ADMIN_COOKIE_NAME = "cammy_admin"
ADMIN_COOKIE_MAX_AGE = 60 * 60 * 12  # 12 hours


def admin_configured() -> bool:
    return bool(config.CAMMY_ADMIN_USERNAME and config.CAMMY_ADMIN_PASSWORD)


def verify_admin_credentials(username: str, password: str) -> bool:
    if not admin_configured():
        return False
    user_ok = hmac.compare_digest(
        (username or "").strip(),
        config.CAMMY_ADMIN_USERNAME,
    )
    pass_ok = hmac.compare_digest(password or "", config.CAMMY_ADMIN_PASSWORD)
    return user_ok and pass_ok


def get_admin_token(request: web.Request) -> str | None:
    return request.cookies.get(ADMIN_COOKIE_NAME)


def is_admin_authenticated(request: web.Request) -> bool:
    if not admin_configured():
        return False
    token = get_admin_token(request)
    if not token:
        return False
    return token in get_state(request).admin_tokens


def create_admin_session(request: web.Request) -> str:
    token = secrets.token_urlsafe(32)
    get_state(request).admin_tokens.add(token)
    return token


def revoke_admin_session(request: web.Request) -> None:
    token = get_admin_token(request)
    if token:
        get_state(request).admin_tokens.discard(token)


def set_admin_cookie(response: web.Response, token: str) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="Lax",
        max_age=ADMIN_COOKIE_MAX_AGE,
    )


def clear_admin_cookie(response: web.Response) -> None:
    response.del_cookie(ADMIN_COOKIE_NAME)


def safe_next_path(raw: str | None) -> str:
    if not raw or not raw.startswith("/") or raw.startswith("//"):
        return "/admin/dashboard"
    return raw


def require_tester_session(request: web.Request) -> None:
    """Redirect to login if no valid tester (cammy_session) cookie."""
    from app_state import has_tester_session

    if has_tester_session(request):
        return
    if request.path.startswith("/api/"):
        raise web.HTTPUnauthorized(
            text='{"error":"login_required"}',
            content_type="application/json",
        )
    raise web.HTTPFound("/")


def require_dashboard_read(request: web.Request) -> None:
    """Admin or logged-in tester may read dashboard data."""
    from app_state import has_tester_session

    if is_admin_authenticated(request) or has_tester_session(request):
        return
    if request.path.startswith("/api/"):
        raise web.HTTPUnauthorized(
            text='{"error":"login_required"}',
            content_type="application/json",
        )
    raise web.HTTPFound("/")


def require_admin(request: web.Request) -> None:
    """Raise if the request is not from an authenticated admin."""
    if is_admin_authenticated(request):
        return
    if request.path.startswith("/api/"):
        raise web.HTTPUnauthorized(
            text='{"error":"admin_required"}',
            content_type="application/json",
        )
    next_path = quote(request.rel_url.path_qs, safe="/%?=&")
    raise web.HTTPFound(f"/admin/login?next={next_path}")


def consent_accepted(value: str | None) -> bool:
    return (value or "").strip().lower() in ("on", "true", "1", "yes")
