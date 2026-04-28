"""
Dashboard retrieval API routes for new logical collections.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp import web
from bson import ObjectId

import db

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/api/dashboard/overview", overview)
    app.router.add_get("/api/dashboard/meal-sessions", meal_sessions)
    app.router.add_get("/api/dashboard/child-status-events", child_status_events)
    app.router.add_get("/api/dashboard/food-diary-entries", food_diary_entries)
    app.router.add_get("/api/dashboard/allergen-logs", allergen_logs)
    app.router.add_get("/api/dashboard/children", children)
    app.router.add_get("/api/dashboard/devices", devices)
    app.router.add_get("/api/dashboard/master-allergens", master_allergens)


def _parse_object_id(value: str | None) -> ObjectId | None:
    if not value:
        return None
    return ObjectId(value) if ObjectId.is_valid(value) else None


def _parse_iso_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _parse_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _mongo_json(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat() + "Z"
    if isinstance(value, dict):
        return {k: _mongo_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mongo_json(v) for v in value]
    return value


def _build_common_filters(request: web.Request, *, time_field: str) -> dict[str, Any]:
    query: dict[str, Any] = {}
    child_id = _parse_object_id(request.query.get("child_id"))
    device_id = _parse_object_id(request.query.get("device_id"))
    session_id = _parse_object_id(request.query.get("session_id"))
    since = _parse_iso_dt(request.query.get("since"))
    until = _parse_iso_dt(request.query.get("until"))

    if child_id:
        query["child_id"] = child_id
    if device_id:
        query["device_id"] = device_id
    if session_id:
        query["session_id"] = session_id
    if since or until:
        query[time_field] = {}
        if since:
            query[time_field]["$gte"] = since
        if until:
            query[time_field]["$lte"] = until
    return query


async def overview(request: web.Request) -> web.Response:
    q = _build_common_filters(request, time_field="started_at")
    meal_count = await db.meal_sessions().count_documents(q)
    active_count = await db.meal_sessions().count_documents({**q, "status": "active"})

    status_q = _build_common_filters(request, time_field="event_timestamp")
    cough_count = await db.child_status_events().count_documents({**status_q, "event_type": "cough"})
    sneeze_count = await db.child_status_events().count_documents({**status_q, "event_type": "sneeze"})

    allergen_q = _build_common_filters(request, time_field="checked_at")
    allergen_alerts = await db.allergen_logs().count_documents({**allergen_q, "alert_triggered": True})

    payload = {
        "meal_sessions_total": meal_count,
        "meal_sessions_active": active_count,
        "cough_events": cough_count,
        "sneeze_events": sneeze_count,
        "allergen_alerts": allergen_alerts,
    }
    return web.json_response(_mongo_json(payload))


async def meal_sessions(request: web.Request) -> web.Response:
    query = _build_common_filters(request, time_field="started_at")
    status = request.query.get("status")
    if status:
        query["status"] = status

    limit = max(1, min(_parse_int(request.query.get("limit"), 50), 200))
    offset = max(0, _parse_int(request.query.get("offset"), 0))

    items = await db.meal_sessions().find(query).sort("started_at", -1).skip(offset).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def child_status_events(request: web.Request) -> web.Response:
    query = _build_common_filters(request, time_field="event_timestamp")
    event_type = request.query.get("event_type")
    if event_type:
        query["event_type"] = event_type

    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    offset = max(0, _parse_int(request.query.get("offset"), 0))

    items = await db.child_status_events().find(query).sort("event_timestamp", -1).skip(offset).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def food_diary_entries(request: web.Request) -> web.Response:
    query = _build_common_filters(request, time_field="detected_at")
    food_name = request.query.get("food_name")
    if food_name:
        query["food_name"] = {"$regex": food_name, "$options": "i"}

    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    offset = max(0, _parse_int(request.query.get("offset"), 0))

    items = await db.food_diary_entries().find(query).sort("detected_at", -1).skip(offset).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def allergen_logs(request: web.Request) -> web.Response:
    query = _build_common_filters(request, time_field="checked_at")
    status = request.query.get("status")
    if status:
        query["status"] = status

    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    offset = max(0, _parse_int(request.query.get("offset"), 0))
    items = await db.allergen_logs().find(query).sort("checked_at", -1).skip(offset).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def children(request: web.Request) -> web.Response:
    query: dict[str, Any] = {}
    active = request.query.get("active")
    if active in ("true", "false"):
        query["active"] = active == "true"
    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    items = await db.children().find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def devices(request: web.Request) -> web.Response:
    query: dict[str, Any] = {}
    active = request.query.get("active")
    if active in ("true", "false"):
        query["active"] = active == "true"
    location = request.query.get("location_label")
    if location:
        query["location_label"] = {"$regex": location, "$options": "i"}
    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    items = await db.devices().find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def master_allergens(request: web.Request) -> web.Response:
    query: dict[str, Any] = {}
    active = request.query.get("active")
    if active in ("true", "false"):
        query["active"] = active == "true"
    limit = max(1, min(_parse_int(request.query.get("limit"), 200), 1000))
    items = await db.master_allergens().find(query).sort("name", 1).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))
