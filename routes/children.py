"""
Child profile CRUD (Phase 8.1).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from aiohttp import web
from bson import ObjectId

import db
from models import utcnow
from services.children_access import (
    attach_tester_fields,
    child_mutation_filter,
    children_list_filter,
    require_children_api,
)

logger = logging.getLogger(__name__)


def setup_routes(app: web.Application) -> None:
    app.router.add_get("/api/children", list_children)
    app.router.add_get("/api/children/{id}", get_child)
    app.router.add_post("/api/children", create_child)
    app.router.add_patch("/api/children/{id}", update_child)
    app.router.add_delete("/api/children/{id}", delete_child)


def _parse_object_id(value: str | None) -> ObjectId | None:
    if not value:
        return None
    return ObjectId(value) if ObjectId.is_valid(value) else None


def _parse_int(value: Any, default: int | None = None) -> int | None:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
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


async def _resolve_allergen_map(ids: list[Any]) -> dict[str, dict[str, Any]]:
    oids = [oid for oid in (_parse_object_id(str(i)) for i in ids) if oid]
    if not oids:
        return {}
    cursor = db.master_allergens().find({"_id": {"$in": oids}}, {"name": 1, "aliases": 1})
    docs = await cursor.to_list(length=len(oids))
    return {str(d["_id"]): d for d in docs}


async def _enrich_child(doc: dict[str, Any]) -> dict[str, Any]:
    ids = doc.get("allergy_ids") or []
    by_id = await _resolve_allergen_map(ids)
    allergies = []
    for raw_id in ids:
        key = str(raw_id)
        allergen = by_id.get(key)
        if allergen:
            allergies.append({"id": key, "name": allergen.get("name", "")})
        else:
            allergies.append({"id": key, "name": ""})
    out = dict(doc)
    out["allergies"] = allergies
    out["allergy_names"] = [a["name"] for a in allergies if a.get("name")]
    return out


def _parse_allergy_ids(body: dict[str, Any]) -> list[ObjectId]:
    raw = body.get("allergy_ids")
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise web.HTTPBadRequest(text="'allergy_ids' must be an array")
    oids: list[ObjectId] = []
    for item in raw:
        oid = _parse_object_id(str(item))
        if oid:
            oids.append(oid)
    return oids


async def list_children(request: web.Request) -> web.Response:
    require_children_api(request)
    base: dict[str, Any] = {}
    active = request.query.get("active")
    if active in ("true", "false"):
        base["active"] = active == "true"
    else:
        base["active"] = True

    query = children_list_filter(request, base)
    limit = max(1, min(_parse_int(request.query.get("limit"), 100) or 100, 500))
    items = await db.children().find(query).sort("name", 1).limit(limit).to_list(length=limit)
    enriched = [await _enrich_child(item) for item in items]
    return web.json_response(_mongo_json({"items": enriched, "count": len(enriched)}))


async def get_child(request: web.Request) -> web.Response:
    require_children_api(request)
    oid = _parse_object_id(request.match_info.get("id", ""))
    if oid is None:
        raise web.HTTPBadRequest(text="Invalid child id")
    doc = await db.children().find_one(child_mutation_filter(request, oid))
    if not doc:
        raise web.HTTPNotFound(text="Child not found")
    return web.json_response(_mongo_json(await _enrich_child(doc)))


async def create_child(request: web.Request) -> web.Response:
    require_children_api(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    name = str(body.get("name", "")).strip()
    if not name:
        raise web.HTTPBadRequest(text="'name' is required")

    age_months = _parse_int(body.get("age_months"))
    sex = str(body.get("sex", "")).strip() or None
    allergy_ids = _parse_allergy_ids(body)

    now = utcnow()
    doc = {
        "name": name,
        "age_months": age_months,
        "sex": sex,
        "allergy_ids": allergy_ids,
        "active": True,
        "created_at": now,
        "updated_at": now,
    }
    doc = attach_tester_fields({k: v for k, v in doc.items() if v is not None}, request)
    result = await db.children().insert_one(doc)
    saved = await db.children().find_one({"_id": result.inserted_id})
    logger.info("Child created: id=%s name=%s", result.inserted_id, name)
    return web.json_response(_mongo_json(await _enrich_child(saved)), status=201)


async def update_child(request: web.Request) -> web.Response:
    require_children_api(request)
    oid = _parse_object_id(request.match_info.get("id", ""))
    if oid is None:
        raise web.HTTPBadRequest(text="Invalid child id")

    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="Invalid JSON body")

    update: dict[str, Any] = {"updated_at": utcnow()}
    if "name" in body:
        name = str(body["name"]).strip()
        if not name:
            raise web.HTTPBadRequest(text="'name' cannot be empty")
        update["name"] = name
    if "age_months" in body:
        update["age_months"] = _parse_int(body["age_months"])
    if "sex" in body:
        sex = str(body["sex"]).strip()
        update["sex"] = sex or None
    if "allergy_ids" in body:
        update["allergy_ids"] = _parse_allergy_ids(body)
    if "active" in body:
        update["active"] = bool(body["active"])

    filt = child_mutation_filter(request, oid)
    result = await db.children().update_one(filt, {"$set": update})
    if result.matched_count == 0:
        raise web.HTTPNotFound(text="Child not found")

    saved = await db.children().find_one(filt)
    logger.info("Child updated: id=%s fields=%s", oid, list(update.keys()))
    return web.json_response(_mongo_json(await _enrich_child(saved)))


async def delete_child(request: web.Request) -> web.Response:
    require_children_api(request)
    oid = _parse_object_id(request.match_info.get("id", ""))
    if oid is None:
        raise web.HTTPBadRequest(text="Invalid child id")

    filt = child_mutation_filter(request, oid)
    result = await db.children().update_one(
        filt,
        {"$set": {"active": False, "updated_at": utcnow()}},
    )
    if result.matched_count == 0:
        raise web.HTTPNotFound(text="Child not found")

    logger.info("Child soft-deleted: id=%s", oid)
    return web.json_response({"deleted": True})
