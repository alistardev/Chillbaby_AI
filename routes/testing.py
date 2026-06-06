"""
Tester feedback API (open beta / pilot).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiohttp import web

import db
from app_state import get_runtime_session
from services.admin_auth import require_admin

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application) -> None:
    app.router.add_post("/api/testing-results", submit_testing_result)
    app.router.add_get("/api/testing-results", list_testing_results)


async def submit_testing_result(request: web.Request) -> web.Response:
    runtime = get_runtime_session(request)
    globalvars = runtime.globalvars

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid_json"}, status=400)

    doc = {
        "tester_id": globalvars.get("testerId"),
        "session_id": globalvars.get("insertedId"),
        "meal_session_id": globalvars.get("mealSessionId"),
        "name": globalvars.get("parent_name") or body.get("name", ""),
        "email": (globalvars.get("parent_email") or body.get("email") or "").lower(),
        "company": globalvars.get("parent_company") or body.get("company", ""),
        "food_accuracy_rating": body.get("food_accuracy_rating"),
        "emotion_accuracy_rating": body.get("emotion_accuracy_rating"),
        "audio_accuracy_rating": body.get("audio_accuracy_rating"),
        "overall_rating": body.get("overall_rating"),
        "notes": (body.get("notes") or "").strip(),
        "browser": (body.get("browser") or "").strip(),
        "device": (body.get("device") or "").strip(),
        "created_at": datetime.now(timezone.utc),
    }

    await db.testing_results().insert_one(doc)
    logger.info(
        "Testing feedback saved: email=%s overall=%s",
        doc.get("email"),
        doc.get("overall_rating"),
    )
    return web.json_response({"ok": True})


def _parse_iso_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


async def list_testing_results(request: web.Request) -> web.Response:
    require_admin(request)
    query: dict = {}
    email = request.query.get("email", "").strip().lower()
    if email:
        query["email"] = email
    tester_id_raw = request.query.get("tester_id", "").strip()
    session_id_raw = request.query.get("session_id", "").strip()
    if tester_id_raw:
        from bson import ObjectId

        if ObjectId.is_valid(tester_id_raw):
            query["tester_id"] = ObjectId(tester_id_raw)
    if session_id_raw:
        from bson import ObjectId

        if ObjectId.is_valid(session_id_raw):
            query["session_id"] = ObjectId(session_id_raw)

    since = _parse_iso_dt(request.query.get("since"))
    until = _parse_iso_dt(request.query.get("until"))
    if since or until:
        query["created_at"] = {}
        if since:
            query["created_at"]["$gte"] = since
        if until:
            query["created_at"]["$lte"] = until

    limit = min(max(int(request.query.get("limit", "50")), 1), 200)
    items = (
        await db.testing_results()
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(length=limit)
    )
    for item in items:
        item["_id"] = str(item["_id"])
        if item.get("tester_id"):
            item["tester_id"] = str(item["tester_id"])
        if item.get("session_id"):
            item["session_id"] = str(item["session_id"])
        if item.get("meal_session_id"):
            item["meal_session_id"] = str(item["meal_session_id"])
        if item.get("created_at"):
            item["created_at"] = item["created_at"].isoformat()
    return web.json_response({"items": items, "count": len(items)})
