"""
Shared application state — one isolated runtime bucket per browser session (cookie).

Each tester gets their own globalvars, WebSocket map, and WebRTC video track so
concurrent logins do not overwrite each other's processing state.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

from aiohttp import web

APP_STATE_KEY = "cammy_session"
COOKIE_NAME = "cammy_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
SESSION_IDLE_TTL_S = max(
    3600,
    int(os.getenv("CAMMY_SESSION_IDLE_TTL_S", str(60 * 60 * 24))),
)  # default 24h without activity


def default_globalvars() -> dict[str, Any]:
    return {
        "processing": False,
        "intolerances": [],
        "mainFood": "",
        "filepath": "",
        "filename": "",
        "insertedId": "",
        "video_url": "",
        "alert_msg": "",
        "processed": False,
    }


@dataclass
class RuntimeSession:
    """Per-browser (cookie) runtime: connections + session globalvars + WebRTC video."""

    connections: dict[str, Any] = field(default_factory=dict)
    globalvars: dict[str, Any] = field(default_factory=default_globalvars)
    local_video: Any = None
    last_activity: float = field(default_factory=time.monotonic)


@dataclass
class AppState:
    sessions: dict[str, RuntimeSession] = field(default_factory=dict)
    admin_tokens: set[str] = field(default_factory=set)


def get_state(request) -> AppState:
    return request.app[APP_STATE_KEY]


def cookie_secure() -> bool:
    """Set CAMMY_COOKIE_SECURE=0 for local HTTP without trusted TLS."""
    return os.getenv("CAMMY_COOKIE_SECURE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def get_session_token(request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def get_runtime_session(request) -> RuntimeSession:
    """Return the cookie-scoped runtime or redirect to login."""
    token = get_session_token(request)
    if not token:
        raise web.HTTPFound("/")
    state = get_state(request)
    runtime = state.sessions.get(token)
    if runtime is None:
        raise web.HTTPFound("/")
    runtime.last_activity = time.monotonic()
    return runtime


def get_runtime_session_optional(request) -> RuntimeSession | None:
    token = get_session_token(request)
    if not token:
        return None
    runtime = get_state(request).sessions.get(token)
    if runtime is not None:
        runtime.last_activity = time.monotonic()
    return runtime


def set_session_cookie(response: web.Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=cookie_secure(),
        samesite="Lax",
        max_age=COOKIE_MAX_AGE,
    )


def create_runtime_session(state: AppState) -> tuple[str, RuntimeSession]:
    import secrets

    token = secrets.token_urlsafe(32)
    runtime = RuntimeSession()
    state.sessions[token] = runtime
    return token, runtime


def revoke_tester_session(request) -> None:
    token = get_session_token(request)
    if not token:
        return
    state = get_state(request)
    runtime = state.sessions.pop(token, None)
    if runtime is not None:
        from services.food import clear_food_client_state, reset_food_runtime_state

        reset_food_runtime_state(token)
        clear_food_client_state(runtime.connections.keys())


def purge_idle_sessions(state: AppState) -> int:
    """Drop in-memory tester sessions idle longer than SESSION_IDLE_TTL_S."""
    now = time.monotonic()
    stale: list[str] = []
    for token, runtime in state.sessions.items():
        if now - runtime.last_activity > SESSION_IDLE_TTL_S:
            stale.append(token)
    for token in stale:
        runtime = state.sessions.pop(token, None)
        if runtime is not None:
            from services.food import clear_food_client_state, reset_food_runtime_state

            reset_food_runtime_state(token)
            clear_food_client_state(runtime.connections.keys())
    return len(stale)


def clear_session_cookie(response: web.Response) -> None:
    response.del_cookie(COOKIE_NAME, path="/")


def has_tester_session(request) -> bool:
    runtime = get_runtime_session_optional(request)
    if runtime is None:
        return False
    return bool(runtime.globalvars.get("insertedId"))
