"""
Smoke verification for additive write flow into new logical collections.

Usage:
    python scripts/verify_new_write_flow.py
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models import EventType, utcnow
from services.domain_writes import (
    close_meal_session,
    create_or_update_meal_session_start,
    ensure_child_and_device_context,
    write_child_status_event,
    write_food_diary_and_allergen_log,
)
import db


def _assert_fields(doc: dict, fields: list[str], name: str) -> None:
    missing = [f for f in fields if f not in doc]
    if missing:
        raise AssertionError(f"{name} missing fields: {missing}")


async def main() -> None:
    now = utcnow()
    globalvars = {
        "intolerances": ["qa-allergen"],
        "location_label": "QA Lab",
    }
    payload = {
        "username": "qa-parent",
        "child_name": "qa-child",
        "age_months": 30,
        "sex": "female",
        "device_name": "QA Device",
        "device_type": "T40",
        "location_label": "QA Lab",
        "body_temperature_celsius": 37.1,
        "intolerance": ["qa-allergen"],
    }

    # 1) Resolve context + start session.
    await ensure_child_and_device_context(globalvars=globalvars, payload=payload)
    globalvars["mealSessionStartedAt"] = now - timedelta(minutes=10)
    meal_session_id = await create_or_update_meal_session_start(
        globalvars=globalvars,
        started_at=globalvars["mealSessionStartedAt"],
    )
    if not meal_session_id:
        raise RuntimeError("Failed to create meal session in additive flow.")

    # 2) Emit representative status events.
    await write_child_status_event(
        globalvars=globalvars,
        event_type=EventType.EMOTION,
        confidence=0.84,
        metadata={"dominant_emotion": "happy"},
    )
    await write_child_status_event(
        globalvars=globalvars,
        event_type=EventType.COUGH,
        confidence=0.77,
        metadata={"source": "panns"},
    )

    # 3) Emit food diary + allergen check.
    await write_food_diary_and_allergen_log(
        globalvars=globalvars,
        food_name="qa-allergen porridge",
        confidence=0.88,
        detected_foods={"qa-allergen porridge": 0.88, "oats": 0.81},
        child_allergy_names=["qa-allergen"],
        nutrition={"calories_kcal": 120.0, "protein_g": 3.2},
    )
    await close_meal_session(globalvars, ended_at=utcnow())

    # 4) Validate persisted shapes.
    ms = await db.meal_sessions().find_one({"_id": meal_session_id})
    cse = await db.child_status_events().find_one({"session_id": meal_session_id})
    fde = await db.food_diary_entries().find_one({"session_id": meal_session_id})
    al = await db.allergen_logs().find_one({"session_id": meal_session_id})

    if not all([ms, cse, fde, al]):
        raise AssertionError("One or more target collection docs were not inserted.")

    _assert_fields(ms, ["started_at", "status", "child_id", "device_id"], "meal_sessions")
    _assert_fields(cse, ["event_type", "event_timestamp", "session_id"], "child_status_events")
    _assert_fields(
        fde,
        ["food_name", "detected_at", "session_id", "estimated_quantity_served_percent"],
        "food_diary_entries",
    )
    _assert_fields(al, ["status", "checked_at", "alert_triggered", "session_id"], "allergen_logs")

    print("OK: additive write flow verified.")
    print(
        {
            "meal_session_id": str(meal_session_id),
            "child_status_event_type": cse.get("event_type"),
            "food_diary_food_name": fde.get("food_name"),
            "allergen_status": al.get("status"),
        }
    )

    # Cleanup only this smoke run.
    await db.allergen_logs().delete_many({"session_id": meal_session_id})
    await db.food_diary_entries().delete_many({"session_id": meal_session_id})
    await db.child_status_events().delete_many({"session_id": meal_session_id})
    await db.meal_sessions().delete_many({"_id": meal_session_id})
    if globalvars.get("childId"):
        await db.children().delete_many({"_id": globalvars["childId"], "name": "qa-child"})
    if globalvars.get("deviceId"):
        await db.devices().delete_many({"_id": globalvars["deviceId"], "device_name": "QA Device"})
    await db.master_allergens().delete_many({"name": "qa-allergen"})


if __name__ == "__main__":
    asyncio.run(main())
