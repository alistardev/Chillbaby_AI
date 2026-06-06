"""
Dashboard retrieval API routes for new logical collections.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from datetime import datetime
from typing import Any

from aiohttp import web
from bson import ObjectId

import db
from app_state import get_runtime_session_optional
from services.admin_auth import is_admin_authenticated, require_admin, require_dashboard_read

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
    app.router.add_get("/api/dashboard/testers", testers_list)
    app.router.add_get("/api/dashboard/export/{kind}.csv", export_dashboard_csv)
    app.router.add_delete("/api/dashboard/records/{kind}/{id}", delete_dashboard_record)
    app.router.add_post("/api/dashboard/records/bulk-delete", bulk_delete_dashboard_records)
    app.router.add_post("/api/allergens", create_allergen)
    app.router.add_patch("/api/allergens/{id}", update_allergen)
    app.router.add_delete("/api/allergens/{id}", delete_allergen)


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


def _deletable_collection(kind: str):
    """Admin dashboard collections that support row removal."""
    return {
        "testers": db.testers,
        "testing-results": db.testing_results,
        "meal-sessions": db.meal_sessions,
        "food-diary-entries": db.food_diary_entries,
        "allergen-logs": db.allergen_logs,
        "child-status-events": db.child_status_events,
    }.get(kind)


def _export_config(kind: str) -> dict[str, Any] | None:
    return {
        "testers": {
            "collection": db.testers,
            "time_field": "created_at",
            "sort": "created_at",
            "columns": ["_id", "name", "email", "company", "consent_version", "invite_status", "created_at"],
        },
        "testing-results": {
            "collection": db.testing_results,
            "time_field": "created_at",
            "sort": "created_at",
            "columns": [
                "_id",
                "tester_id",
                "tester_name",
                "email",
                "session_id",
                "meal_session_id",
                "overall_rating",
                "food_accuracy_rating",
                "emotion_accuracy_rating",
                "audio_accuracy_rating",
                "notes",
                "browser",
                "device",
                "created_at",
            ],
        },
        "meal-sessions": {
            "collection": db.meal_sessions,
            "time_field": "started_at",
            "sort": "started_at",
            "columns": ["_id", "tester_id", "tester_name", "email", "session_id", "child_id", "status", "started_at", "ended_at"],
        },
        "food-diary-entries": {
            "collection": db.food_diary_entries,
            "time_field": "detected_at",
            "sort": "detected_at",
            "columns": ["_id", "tester_id", "tester_name", "email", "session_id", "child_id", "food_name", "confidence", "detected_at"],
        },
        "allergen-logs": {
            "collection": db.allergen_logs,
            "time_field": "checked_at",
            "sort": "checked_at",
            "columns": ["_id", "tester_id", "tester_name", "email", "session_id", "child_id", "food_name", "matched_allergens", "alert_triggered", "status", "checked_at"],
        },
        "child-status-events": {
            "collection": db.child_status_events,
            "time_field": "event_timestamp",
            "sort": "event_timestamp",
            "columns": ["_id", "tester_id", "tester_name", "email", "session_id", "child_id", "event_type", "confidence", "event_timestamp"],
        },
    }.get(kind)


def _csv_value(value: Any) -> str:
    value = _mongo_json(value)
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def _build_common_filters(request: web.Request, *, time_field: str) -> dict[str, Any]:
    query: dict[str, Any] = {}
    child_id = _parse_object_id(request.query.get("child_id"))
    device_id = _parse_object_id(request.query.get("device_id"))
    session_id = _parse_object_id(request.query.get("session_id"))
    tester_id = _parse_object_id(request.query.get("tester_id"))
    email = request.query.get("email", "").strip().lower()
    since = _parse_iso_dt(request.query.get("since"))
    until = _parse_iso_dt(request.query.get("until"))

    if child_id:
        query["child_id"] = child_id
    if device_id:
        query["device_id"] = device_id
    if session_id:
        query["session_id"] = session_id
    if tester_id:
        query["tester_id"] = tester_id
    if email:
        query["email"] = email
    if since or until:
        query[time_field] = {}
        if since:
            query[time_field]["$gte"] = since
        if until:
            query[time_field]["$lte"] = until
    return query


def _scoped_filters(request: web.Request, *, time_field: str) -> dict[str, Any]:
    """Admins see all data; testers are limited to their own email/tester_id."""
    if is_admin_authenticated(request):
        return _build_common_filters(request, time_field=time_field)

    require_dashboard_read(request)
    runtime = get_runtime_session_optional(request)
    query: dict[str, Any] = {}
    since = _parse_iso_dt(request.query.get("since"))
    until = _parse_iso_dt(request.query.get("until"))
    if since or until:
        query[time_field] = {}
        if since:
            query[time_field]["$gte"] = since
        if until:
            query[time_field]["$lte"] = until

    if runtime:
        tester_id = runtime.globalvars.get("testerId")
        email = (runtime.globalvars.get("parent_email") or "").strip().lower()
        if tester_id:
            query["tester_id"] = tester_id
        elif email:
            query["email"] = email
    return query


async def _enrich_tester_names(items: list[dict[str, Any]]) -> None:
    """Attach tester_name from testers collection when missing on dashboard rows."""
    if not items:
        return

    ids: list[ObjectId] = []
    emails: list[str] = []
    for item in items:
        if item.get("tester_name"):
            continue
        tid = item.get("tester_id")
        if isinstance(tid, ObjectId):
            ids.append(tid)
        elif tid and ObjectId.is_valid(str(tid)):
            ids.append(ObjectId(str(tid)))
        em = (item.get("email") or "").strip().lower()
        if em:
            emails.append(em)

    by_id: dict[ObjectId, dict[str, Any]] = {}
    by_email: dict[str, dict[str, Any]] = {}
    if ids:
        unique_ids = list(dict.fromkeys(ids))
        docs = await db.testers().find({"_id": {"$in": unique_ids}}).to_list(length=len(unique_ids))
        for doc in docs:
            by_id[doc["_id"]] = doc
    if emails:
        unique_emails = list(dict.fromkeys(emails))
        docs = await db.testers().find({"email": {"$in": unique_emails}}).to_list(length=len(unique_emails))
        for doc in docs:
            by_email[str(doc.get("email", "")).strip().lower()] = doc

    for item in items:
        if item.get("tester_name"):
            continue
        tester = None
        tid = item.get("tester_id")
        oid = (
            tid
            if isinstance(tid, ObjectId)
            else (ObjectId(str(tid)) if tid and ObjectId.is_valid(str(tid)) else None)
        )
        if oid is not None:
            tester = by_id.get(oid)
        if tester is None:
            em = (item.get("email") or "").strip().lower()
            if em:
                tester = by_email.get(em)
        if tester:
            item["tester_name"] = tester.get("name") or ""
            if not item.get("email") and tester.get("email"):
                item["email"] = str(tester["email"]).strip().lower()


async def overview(request: web.Request) -> web.Response:
    require_dashboard_read(request)
    q = _scoped_filters(request, time_field="started_at")
    meal_count = await db.meal_sessions().count_documents(q)
    active_count = await db.meal_sessions().count_documents({**q, "status": "active"})

    status_q = _scoped_filters(request, time_field="event_timestamp")
    cough_count = await db.child_status_events().count_documents({**status_q, "event_type": "cough"})
    sneeze_count = await db.child_status_events().count_documents({**status_q, "event_type": "sneeze"})

    allergen_q = _scoped_filters(request, time_field="checked_at")
    allergen_alerts = await db.allergen_logs().count_documents({**allergen_q, "alert_triggered": True})

    payload = {
        "meal_sessions_total": meal_count,
        "meal_sessions_active": active_count,
        "cough_events": cough_count,
        "sneeze_events": sneeze_count,
        "allergen_alerts": allergen_alerts,
    }
    if is_admin_authenticated(request):
        payload["testers_total"] = await db.testers().count_documents({})
        payload["feedback_total"] = await db.testing_results().count_documents({})
    return web.json_response(_mongo_json(payload))


async def meal_sessions(request: web.Request) -> web.Response:
    require_dashboard_read(request)
    query = _scoped_filters(request, time_field="started_at")
    status = request.query.get("status")
    if status:
        query["status"] = status

    limit = max(1, min(_parse_int(request.query.get("limit"), 50), 200))
    offset = max(0, _parse_int(request.query.get("offset"), 0))

    items = await db.meal_sessions().find(query).sort("started_at", -1).skip(offset).limit(limit).to_list(length=limit)
    if is_admin_authenticated(request):
        await _enrich_tester_names(items)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def child_status_events(request: web.Request) -> web.Response:
    require_dashboard_read(request)
    query = _scoped_filters(request, time_field="event_timestamp")
    event_type = request.query.get("event_type")
    if event_type:
        query["event_type"] = event_type

    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    offset = max(0, _parse_int(request.query.get("offset"), 0))

    items = await db.child_status_events().find(query).sort("event_timestamp", -1).skip(offset).limit(limit).to_list(length=limit)
    if is_admin_authenticated(request):
        await _enrich_tester_names(items)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def food_diary_entries(request: web.Request) -> web.Response:
    require_dashboard_read(request)
    query = _scoped_filters(request, time_field="detected_at")
    food_name = request.query.get("food_name")
    if food_name:
        query["food_name"] = {"$regex": food_name, "$options": "i"}

    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    offset = max(0, _parse_int(request.query.get("offset"), 0))

    items = await db.food_diary_entries().find(query).sort("detected_at", -1).skip(offset).limit(limit).to_list(length=limit)
    if is_admin_authenticated(request):
        await _enrich_tester_names(items)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def allergen_logs(request: web.Request) -> web.Response:
    require_dashboard_read(request)
    query = _scoped_filters(request, time_field="checked_at")
    status = request.query.get("status")
    if status:
        query["status"] = status

    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    offset = max(0, _parse_int(request.query.get("offset"), 0))
    items = await db.allergen_logs().find(query).sort("checked_at", -1).skip(offset).limit(limit).to_list(length=limit)
    if is_admin_authenticated(request):
        await _enrich_tester_names(items)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def children(request: web.Request) -> web.Response:
    require_admin(request)  # admin-only: all child profiles
    query: dict[str, Any] = {}
    active = request.query.get("active")
    if active in ("true", "false"):
        query["active"] = active == "true"
    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    items = await db.children().find(query).sort("created_at", -1).limit(limit).to_list(length=limit)
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def devices(request: web.Request) -> web.Response:
    require_admin(request)  # admin-only
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


# ── Phase 6: Master Allergen CRUD ────────────────────────────────────────────

async def create_allergen(request: web.Request) -> web.Response:
    """POST /api/allergens — create a custom allergen in master_allergens."""
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    name = str(body.get("name", "")).strip()
    if not name:
        raise web.HTTPBadRequest(text="'name' is required")

    existing = await db.master_allergens().find_one(
        {"name": {"$regex": f"^{name}$", "$options": "i"}}
    )
    if existing:
        return web.json_response(
            {"error": f"Allergen '{name}' already exists", "id": str(existing["_id"])},
            status=409,
        )

    aliases = [str(a).strip() for a in body.get("aliases", []) if str(a).strip()]
    doc = {
        "name": name,
        "category": str(body.get("category", "custom")).strip() or "custom",
        "aliases": aliases,
        "created_at": datetime.utcnow(),
        "active": True,
    }
    result = await db.master_allergens().insert_one(doc)
    logger.info("Custom allergen created: name=%s id=%s", name, result.inserted_id)
    return web.json_response(
        _mongo_json({"id": result.inserted_id, "name": name}), status=201
    )


async def update_allergen(request: web.Request) -> web.Response:
    """PATCH /api/allergens/{id} — update name, aliases, or active flag."""
    require_admin(request)
    raw_id = request.match_info.get("id", "")
    oid = _parse_object_id(raw_id)
    if oid is None:
        raise web.HTTPBadRequest(text="Invalid allergen id")

    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    update: dict[str, Any] = {"updated_at": datetime.utcnow()}
    if "name" in body:
        name = str(body["name"]).strip()
        if not name:
            raise web.HTTPBadRequest(text="'name' cannot be empty")
        existing = await db.master_allergens().find_one(
            {"name": {"$regex": f"^{name}$", "$options": "i"}, "_id": {"$ne": oid}}
        )
        if existing:
            return web.json_response(
                {"error": f"Allergen '{name}' already exists"},
                status=409,
            )
        update["name"] = name
    if "aliases" in body:
        update["aliases"] = [str(a).strip() for a in body["aliases"] if str(a).strip()]
    if "active" in body:
        update["active"] = bool(body["active"])
    if "category" in body:
        update["category"] = str(body["category"]).strip() or "custom"

    result = await db.master_allergens().update_one({"_id": oid}, {"$set": update})
    if result.matched_count == 0:
        raise web.HTTPNotFound(text=f"Allergen {raw_id} not found")

    logger.info("Allergen updated: id=%s fields=%s", raw_id, list(update.keys()))
    return web.json_response({"updated": True})


async def testers_list(request: web.Request) -> web.Response:
    require_admin(request)
    limit = max(1, min(_parse_int(request.query.get("limit"), 100), 500))
    email = request.query.get("email", "").strip().lower()
    tester_id = _parse_object_id(request.query.get("tester_id"))
    since = _parse_iso_dt(request.query.get("since"))
    until = _parse_iso_dt(request.query.get("until"))
    query: dict[str, Any] = {}
    if email:
        query["email"] = email
    if tester_id:
        query["_id"] = tester_id
    if since or until:
        query["created_at"] = {}
        if since:
            query["created_at"]["$gte"] = since
        if until:
            query["created_at"]["$lte"] = until

    items = (
        await db.testers()
        .find(query)
        .sort("created_at", -1)
        .limit(limit)
        .to_list(length=limit)
    )
    return web.json_response(_mongo_json({"items": items, "count": len(items)}))


async def export_dashboard_csv(request: web.Request) -> web.Response:
    require_admin(request)
    kind = request.match_info.get("kind", "")
    config = _export_config(kind)
    if config is None:
        raise web.HTTPBadRequest(text="Unsupported export type")

    limit = max(1, min(_parse_int(request.query.get("limit"), 5000), 20000))
    if kind == "testers":
        query: dict[str, Any] = {}
        email = request.query.get("email", "").strip().lower()
        tester_id = _parse_object_id(request.query.get("tester_id"))
        since = _parse_iso_dt(request.query.get("since"))
        until = _parse_iso_dt(request.query.get("until"))
        if email:
            query["email"] = email
        if tester_id:
            query["_id"] = tester_id
        if since or until:
            query["created_at"] = {}
            if since:
                query["created_at"]["$gte"] = since
            if until:
                query["created_at"]["$lte"] = until
    else:
        query = _build_common_filters(request, time_field=config["time_field"])

    items = (
        await config["collection"]()
        .find(query)
        .sort(config["sort"], -1)
        .limit(limit)
        .to_list(length=limit)
    )
    if kind != "testers":
        await _enrich_tester_names(items)

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=config["columns"], extrasaction="ignore")
    writer.writeheader()
    for item in items:
        row = {column: _csv_value(item.get(column)) for column in config["columns"]}
        writer.writerow(row)

    filename = f"cammy-{kind}.csv"
    return web.Response(
        text=output.getvalue(),
        content_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


async def delete_dashboard_record(request: web.Request) -> web.Response:
    require_admin(request)
    kind = request.match_info.get("kind", "")
    oid = _parse_object_id(request.match_info.get("id", ""))
    collection_factory = _deletable_collection(kind)
    if collection_factory is None:
        raise web.HTTPBadRequest(text="Unsupported dashboard record type")
    if oid is None:
        raise web.HTTPBadRequest(text="Invalid record id")

    result = await collection_factory().delete_one({"_id": oid})
    if result.deleted_count == 0:
        raise web.HTTPNotFound(text="Record not found")

    logger.info("Admin deleted dashboard record: kind=%s id=%s", kind, oid)
    return web.json_response({"deleted": True, "kind": kind, "id": str(oid)})


async def bulk_delete_dashboard_records(request: web.Request) -> web.Response:
    require_admin(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    items = body.get("items", [])
    if not isinstance(items, list):
        raise web.HTTPBadRequest(text="'items' must be an array")
    if len(items) > 200:
        raise web.HTTPBadRequest(text="At most 200 records can be removed at once")

    deleted = 0
    missing = 0
    invalid: list[dict[str, str]] = []
    for item in items:
        if not isinstance(item, dict):
            invalid.append({"kind": "", "id": "", "error": "invalid_item"})
            continue
        kind = str(item.get("kind", "")).strip()
        raw_id = str(item.get("id", "")).strip()
        collection_factory = _deletable_collection(kind)
        oid = _parse_object_id(raw_id)
        if collection_factory is None or oid is None:
            invalid.append({"kind": kind, "id": raw_id, "error": "invalid_kind_or_id"})
            continue
        result = await collection_factory().delete_one({"_id": oid})
        if result.deleted_count:
            deleted += 1
        else:
            missing += 1

    logger.info(
        "Admin bulk deleted dashboard records: deleted=%d missing=%d invalid=%d",
        deleted,
        missing,
        len(invalid),
    )
    return web.json_response(
        {"deleted": deleted, "missing": missing, "invalid": invalid}
    )


async def delete_allergen(request: web.Request) -> web.Response:
    """DELETE /api/allergens/{id} — soft-delete (sets active=false)."""
    require_admin(request)
    raw_id = request.match_info.get("id", "")
    oid = _parse_object_id(raw_id)
    if oid is None:
        raise web.HTTPBadRequest(text="Invalid allergen id")

    result = await db.master_allergens().update_one(
        {"_id": oid},
        {"$set": {"active": False, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count == 0:
        raise web.HTTPNotFound(text=f"Allergen {raw_id} not found")

    logger.info("Allergen soft-deleted: id=%s", raw_id)
    return web.json_response({"deleted": True})
