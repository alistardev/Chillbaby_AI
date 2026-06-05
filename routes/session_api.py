"""
Session-scoped APIs for logged-in testers (not admin dashboard).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp import web
import db
from app_state import get_runtime_session
from routes.dashboard import _mongo_json, _parse_int
from services.ml_ready import get_ml_ready, ready_payload

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/api/session/ready", session_ready)
    app.router.add_get("/api/session/allergen-logs", session_allergen_logs)


async def session_ready(request: web.Request) -> web.Response:
    """Whether server ML models finished startup warmup (call before Start camera)."""
    get_runtime_session(request)
    payload = ready_payload(get_ml_ready(request.app))
    return web.json_response(payload)


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def session_allergen_logs(request: web.Request) -> web.Response:
    """Allergen audit for the current tester session only."""
    runtime = get_runtime_session(request)
    globalvars = runtime.globalvars

    query: dict[str, Any] = {}
    meal_session_id = globalvars.get("mealSessionId")
    legacy_session_id = globalvars.get("insertedId")
    if meal_session_id:
        query["session_id"] = meal_session_id
    elif legacy_session_id:
        query["session_id"] = legacy_session_id
    else:
        return web.json_response({"items": [], "count": 0})

    tester_id = globalvars.get("testerId")
    if tester_id:
        query["tester_id"] = tester_id

    since = _parse_iso_dt(request.query.get("since"))
    if since:
        query["checked_at"] = {"$gte": since}

    limit = max(1, min(_parse_int(request.query.get("limit"), 80), 200))
    items = (
        await db.allergen_logs()
        .find(query)
        .sort("checked_at", -1)
        .limit(limit)
        .to_list(length=limit)
    )
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))
