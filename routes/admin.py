"""
Admin login/logout for the caregiver dashboard.
"""

from __future__ import annotations

import logging

import aiohttp_jinja2
from aiohttp import web

from app_state import get_runtime_session_optional, get_state, has_tester_session, set_session_cookie
from services.admin_auth import (
    admin_configured,
    clear_admin_cookie,
    create_admin_session,
    is_admin_authenticated,
    require_admin,
    revoke_admin_session,
    safe_next_path,
    set_admin_cookie,
    verify_admin_credentials,
)
from services.tester_bootstrap import begin_admin_staff_session

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/admin/login", admin_login_get)
    app.router.add_post("/admin/login", admin_login_post)
    app.router.add_get("/admin/start-monitor", admin_start_monitor_get)
    app.router.add_post("/admin/logout", admin_logout_post)


@aiohttp_jinja2.template("admin-login.html")
async def admin_login_get(request: web.Request) -> dict:
    if is_admin_authenticated(request):
        raise web.HTTPFound("/admin/dashboard")
    return {
        "next": safe_next_path(request.query.get("next")),
        "error": request.query.get("err", ""),
    }


async def admin_login_post(request: web.Request) -> web.Response:
    if not admin_configured():
        raise web.HTTPFound("/admin/login?err=invalid")

    data = await request.post()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    next_url = safe_next_path(data.get("next"))

    if not verify_admin_credentials(username, password):
        logger.warning("Failed admin login attempt for user=%s", username)
        raise web.HTTPFound(f"/admin/login?err=invalid&next={next_url}")

    token = create_admin_session(request)
    resp = web.HTTPFound(next_url)
    set_admin_cookie(resp, token)

    if not has_tester_session(request):
        try:
            staff_token, _runtime = await begin_admin_staff_session(get_state(request))
            set_session_cookie(resp, staff_token)
            logger.info("Admin staff monitor session created for user=%s", username)
        except Exception:
            logger.exception("Failed to create admin staff monitor session for user=%s", username)

    logger.info("Admin login successful for user=%s", username)
    return resp


async def admin_start_monitor_get(request: web.Request) -> web.Response:
    """Ensure admin has a caregiver session, then open child selection / monitor."""
    require_admin(request)
    if not has_tester_session(request):
        try:
            staff_token, _runtime = await begin_admin_staff_session(get_state(request))
            resp = web.HTTPFound("/select-child")
            set_session_cookie(resp, staff_token)
            return resp
        except Exception:
            logger.exception("Failed to create admin staff monitor session")
            raise web.HTTPFound("/admin/dashboard?err=monitor")

    runtime = get_runtime_session_optional(request)
    if runtime and runtime.globalvars.get("childId"):
        raise web.HTTPFound("/process")
    raise web.HTTPFound("/select-child")


async def admin_logout_post(request: web.Request) -> web.Response:
    revoke_admin_session(request)
    resp = web.HTTPFound("/admin/login")
    clear_admin_cookie(resp)
    return resp
