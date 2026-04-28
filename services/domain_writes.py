"""
Additive domain writes to new logical collections.

This module intentionally keeps legacy writes intact and mirrors normalized
documents into new collections to reduce migration risk for Phases 1-4.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from bson import ObjectId
import db
from models import (
    AllergenLog,
    AllergenStatus,
    ChildSnapshot,
    ChildStatusEvent,
    EventType,
    FoodDiaryEntry,
    MealSession,
    to_mongo_doc,
    utcnow,
)

logger = logging.getLogger(__name__)


def additive_writes_enabled() -> bool:
    value = os.getenv("CAMMY_ENABLE_NEW_COLLECTION_WRITES", "1").strip().lower()
    return value not in ("0", "false", "no")


def _snapshot_from_globalvars(globalvars: dict[str, Any]) -> ChildSnapshot:
    # Current Phase 1-4 flow still captures parent-centric fields. We keep this
    # optional snapshot relaxed until child profile UI (Phase 8) is implemented.
    name = globalvars.get("child_name") or globalvars.get("parent_name")
    return ChildSnapshot(
        name=name,
        age_months=globalvars.get("child_age_months"),
        sex=globalvars.get("child_sex"),
    )


def _to_object_id(value: Any) -> ObjectId | None:
    if isinstance(value, ObjectId):
        return value
    if isinstance(value, str) and ObjectId.is_valid(value):
        return ObjectId(value)
    return None


def _to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def _resolve_master_allergen_docs() -> list[dict[str, Any]]:
    cursor = db.master_allergens().find(
        {"active": True},
        {"name": 1, "aliases": 1},
    )
    return await cursor.to_list(length=500)


def _food_matches_allergen(food_text: str, allergen_doc: dict[str, Any]) -> bool:
    hay = (food_text or "").lower()
    keys = [str(allergen_doc.get("name", "")).strip().lower()]
    keys.extend([str(a).strip().lower() for a in allergen_doc.get("aliases", []) if a])
    keys = [k for k in keys if k]
    return any(k in hay for k in keys)


def _compute_quantity_estimates(first_conf: float | None, last_conf: float | None) -> tuple[float | None, float | None, float | None]:
    # Confidence is a weak proxy for quantity; keep this conservative and bounded.
    served = 100.0
    if first_conf is None or last_conf is None or first_conf <= 0:
        return served, None, None
    eaten = max(0.0, min(100.0, (1.0 - (last_conf / first_conf)) * 100.0))
    remaining = max(0.0, min(100.0, 100.0 - eaten))
    return served, round(eaten, 2), round(remaining, 2)


async def ensure_child_and_device_context(
    *,
    globalvars: dict[str, Any],
    payload: dict[str, Any],
) -> None:
    """
    Resolve/initialize child and device references from request payload.

    This is intentionally permissive and backward-compatible for current flows.
    """
    child_id = _to_object_id(payload.get("child_id") or globalvars.get("childId"))
    device_id = _to_object_id(payload.get("device_id") or globalvars.get("deviceId"))

    child_name = (payload.get("child_name") or payload.get("username") or globalvars.get("parent_name") or "").strip()
    child_age_months = payload.get("age_months") or payload.get("child_age_months") or globalvars.get("child_age_months")
    child_sex = (payload.get("sex") or payload.get("child_sex") or globalvars.get("child_sex") or "").strip() or None

    location_label = (payload.get("location_label") or payload.get("device_location") or globalvars.get("location_label") or "").strip() or None
    device_name = (payload.get("device_name") or "Cammy Device").strip()
    device_type = (payload.get("device_type") or "T40").strip()

    body_temp = _to_float(payload.get("body_temperature_celsius"))
    if body_temp is not None:
        globalvars["body_temperature_celsius"] = body_temp
    elif "body_temperature_celsius" not in globalvars:
        globalvars["body_temperature_celsius"] = None

    master_allergens = await _resolve_master_allergen_docs()
    by_name = {d.get("name", "").strip().lower(): d for d in master_allergens if d.get("name")}
    by_alias: dict[str, dict[str, Any]] = {}
    for doc in master_allergens:
        for alias in doc.get("aliases", []):
            k = str(alias).strip().lower()
            if k:
                by_alias[k] = doc

    declared_allergy_names: list[str] = [
        str(x).strip() for x in (payload.get("intolerance") or globalvars.get("intolerances") or []) if str(x).strip()
    ]

    resolved_allergy_ids: list[ObjectId] = []
    if payload.get("allergy_ids"):
        for aid in payload.get("allergy_ids", []):
            oid = _to_object_id(aid)
            if oid:
                resolved_allergy_ids.append(oid)
    else:
        for name in dict.fromkeys(declared_allergy_names):
            key = name.lower()
            found = by_name.get(key) or by_alias.get(key)
            if found and isinstance(found.get("_id"), ObjectId):
                resolved_allergy_ids.append(found["_id"])
            elif name:
                # Keep Phase 6 flexible: allow custom allergens while preserving
                # normalized linkage by creating a master allergen entry on demand.
                custom = {
                    "name": name,
                    "category": "custom",
                    "aliases": [],
                    "created_at": utcnow(),
                    "active": True,
                }
                result = await db.master_allergens().insert_one(custom)
                resolved_allergy_ids.append(result.inserted_id)

    # Create fallback child if no identifier was supplied.
    if child_id is None and child_name:
        child_doc = {
            "name": child_name,
            "age_months": int(child_age_months) if child_age_months not in (None, "") else None,
            "sex": child_sex,
            "allergy_ids": resolved_allergy_ids,
            "active": True,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        result = await db.children().insert_one({k: v for k, v in child_doc.items() if v is not None})
        child_id = result.inserted_id
    elif child_id is not None:
        update_doc = {
            "updated_at": utcnow(),
            "active": True,
        }
        if child_name:
            update_doc["name"] = child_name
        if child_age_months not in (None, ""):
            update_doc["age_months"] = int(child_age_months)
        if child_sex:
            update_doc["sex"] = child_sex
        if resolved_allergy_ids:
            update_doc["allergy_ids"] = resolved_allergy_ids
        await db.children().update_one({"_id": child_id}, {"$set": update_doc}, upsert=True)

    if device_id is None:
        device_doc = {
            "device_name": device_name,
            "device_type": device_type,
            "location_label": location_label,
            "active": True,
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        result = await db.devices().insert_one({k: v for k, v in device_doc.items() if v is not None})
        device_id = result.inserted_id
    else:
        await db.devices().update_one(
            {"_id": device_id},
            {
                "$set": {
                    "device_name": device_name,
                    "device_type": device_type,
                    "location_label": location_label,
                    "active": True,
                    "updated_at": utcnow(),
                }
            },
            upsert=True,
        )

    globalvars["childId"] = child_id
    globalvars["deviceId"] = device_id
    globalvars["child_name"] = child_name or globalvars.get("child_name")
    globalvars["child_age_months"] = int(child_age_months) if child_age_months not in (None, "") else globalvars.get("child_age_months")
    globalvars["child_sex"] = child_sex or globalvars.get("child_sex")
    globalvars["location_label"] = location_label
    globalvars["intolerances"] = declared_allergy_names
    globalvars["child_allergy_ids"] = resolved_allergy_ids


async def create_or_update_meal_session_start(
    *,
    globalvars: dict[str, Any],
    started_at: datetime | None = None,
    status: str = "active",
) -> Any | None:
    if not additive_writes_enabled():
        return None

    started_at = started_at or utcnow()
    existing = globalvars.get("mealSessionId")
    now = utcnow()
    if existing:
        await db.meal_sessions().update_one(
            {"_id": existing},
            {"$set": {"status": status, "updated_at": now}},
        )
        return existing

    model = MealSession(
        child_id=globalvars.get("childId"),
        device_id=globalvars.get("deviceId"),
        location_label_snapshot=globalvars.get("location_label"),
        child_snapshot=_snapshot_from_globalvars(globalvars),
        body_temperature_celsius=globalvars.get("body_temperature_celsius"),
        started_at=started_at,
        status=status,
        created_at=now,
        updated_at=now,
    )
    result = await db.meal_sessions().insert_one(to_mongo_doc(model))
    globalvars["mealSessionId"] = result.inserted_id
    return result.inserted_id


async def close_meal_session(globalvars: dict[str, Any], ended_at: datetime | None = None) -> None:
    if not additive_writes_enabled():
        return

    meal_session_id = globalvars.get("mealSessionId")
    if not meal_session_id:
        return

    ended_at = ended_at or utcnow()
    started_at = globalvars.get("mealSessionStartedAt")
    duration_seconds = None
    if isinstance(started_at, datetime):
        duration_seconds = max(int((ended_at - started_at).total_seconds()), 0)

    await db.meal_sessions().update_one(
        {"_id": meal_session_id},
        {
            "$set": {
                "ended_at": ended_at,
                "duration_seconds": duration_seconds,
                "status": "completed",
                "updated_at": utcnow(),
            }
        },
    )


async def write_child_status_event(
    *,
    globalvars: dict[str, Any],
    event_type: EventType,
    confidence: float | None = None,
    metadata: dict[str, Any] | None = None,
    event_timestamp: datetime | None = None,
) -> None:
    if not additive_writes_enabled():
        return

    model = ChildStatusEvent(
        session_id=globalvars.get("mealSessionId") or globalvars.get("insertedId"),
        child_id=globalvars.get("childId"),
        device_id=globalvars.get("deviceId"),
        location_label_snapshot=globalvars.get("location_label"),
        child_snapshot=_snapshot_from_globalvars(globalvars),
        event_type=event_type,
        event_timestamp=event_timestamp or utcnow(),
        confidence=confidence,
        metadata=metadata or {},
        body_temperature_celsius=globalvars.get("body_temperature_celsius"),
        created_at=utcnow(),
    )
    await db.child_status_events().insert_one(to_mongo_doc(model))


async def write_food_diary_and_allergen_log(
    *,
    globalvars: dict[str, Any],
    food_name: str,
    confidence: float | None,
    detected_foods: dict[str, float],
    child_allergy_names: list[str],
    nutrition: dict[str, Any] | None = None,
    detection_sources: list[str] | None = None,
) -> None:
    if not additive_writes_enabled():
        return

    now = utcnow()
    session_id = globalvars.get("mealSessionId") or globalvars.get("insertedId")
    if not session_id:
        return

    food_name = (food_name or "").strip()
    if not food_name:
        return

    previous = await db.food_diary_entries().find_one(
        {"session_id": session_id, "food_name": food_name},
        sort=[("detected_at", -1)],
    )

    first_conf = _to_float(previous.get("metadata", {}).get("first_detection_confidence")) if previous else None
    last_conf = _to_float(confidence)
    if first_conf is None:
        first_conf = last_conf

    served_pct, eaten_pct, remaining_pct = _compute_quantity_estimates(first_conf, last_conf)

    entry = FoodDiaryEntry(
        session_id=session_id,
        child_id=globalvars.get("childId"),
        device_id=globalvars.get("deviceId"),
        location_label_snapshot=globalvars.get("location_label"),
        child_snapshot=_snapshot_from_globalvars(globalvars),
        food_name=food_name,
        detected_at=now,
        detection_sources=detection_sources or ["local"],
        confidence=last_conf,
        nutrition=nutrition or {},
        estimated_quantity_served_percent=served_pct,
        estimated_quantity_eaten_percent=eaten_pct,
        estimated_quantity_remaining_percent=remaining_pct,
        allergens_served=[],
        metadata={
            "first_detection_confidence": first_conf,
            "last_detection_confidence": last_conf,
            "quantity_estimation_method": "confidence_proxy_v1",
            "detected_foods": detected_foods,
        },
        created_at=now,
    )

    master_docs = await _resolve_master_allergen_docs()
    declared_ids: list[ObjectId] = [
        oid for oid in (globalvars.get("child_allergy_ids") or []) if isinstance(oid, ObjectId)
    ]
    if not declared_ids:
        by_name = {d.get("name", "").strip().lower(): d for d in master_docs if d.get("name")}
        by_alias: dict[str, dict[str, Any]] = {}
        for doc in master_docs:
            for alias in doc.get("aliases", []):
                k = str(alias).strip().lower()
                if k:
                    by_alias[k] = doc
        for name in child_allergy_names:
            key = str(name).strip().lower()
            found = by_name.get(key) or by_alias.get(key)
            if found and isinstance(found.get("_id"), ObjectId):
                declared_ids.append(found["_id"])

    declared_set = set(declared_ids)
    source_food_text = " ".join([food_name] + list(detected_foods.keys()))
    matched_docs = [
        d for d in master_docs
        if (not declared_set or d.get("_id") in declared_set) and _food_matches_allergen(source_food_text, d)
    ]
    matched_names = [str(d.get("name")) for d in matched_docs if d.get("name")]
    matched_ids = [d.get("_id") for d in matched_docs if isinstance(d.get("_id"), ObjectId)]
    if not matched_names and child_allergy_names:
        # Fallback when master allergen catalog is incomplete.
        hay = source_food_text.lower()
        matched_names = [name for name in child_allergy_names if str(name).lower() in hay]
    entry.allergens_served = matched_names

    status = AllergenStatus.DETECTED if matched_names else AllergenStatus.NOT_DETECTED

    # One diary document per (session, food_name), updated as detections continue.
    update_doc = to_mongo_doc(entry)
    update_doc.pop("created_at", None)
    upsert_result = await db.food_diary_entries().update_one(
        {"session_id": session_id, "food_name": food_name},
        {
            "$set": update_doc,
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    if upsert_result.upserted_id is not None:
        food_entry_id = upsert_result.upserted_id
    elif previous and previous.get("_id"):
        food_entry_id = previous["_id"]
    else:
        refreshed = await db.food_diary_entries().find_one({"session_id": session_id, "food_name": food_name})
        food_entry_id = refreshed.get("_id") if refreshed else None

    allergen_log = AllergenLog(
        session_id=session_id,
        child_id=entry.child_id,
        device_id=entry.device_id,
        food_diary_entry_id=food_entry_id,
        food_name=food_name,
        checked_at=now,
        child_allergy_ids=declared_ids,
        matched_allergen_ids=matched_ids,
        matched_allergen_names=matched_names,
        alert_triggered=bool(matched_names),
        status=status,
        created_at=now,
    )
    await db.allergen_logs().insert_one(to_mongo_doc(allergen_log))
