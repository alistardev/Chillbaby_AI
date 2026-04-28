"""
Async MongoDB client using motor.
Exposes collection references used across the application.

Collections
-----------
Legacy collections
------------------
sessions       – one document per user monitoring session
emotion_events – timestamped emotion snapshots
food_events    – timestamped food-detection results
alert_events   – child_missing / cough alerts (Phases 2 & 3)
intake_forms   – submitted start-form identity/preferences

Target logical entities (roadmap/client brief)
-----------------------------------------------
children
devices
meal_sessions
child_status_events
food_diary_entries
allergen_logs
master_allergens
"""

import logging
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient
from config import DB_URL, DB_NAME
from models import MasterAllergen, to_mongo_doc

logger = logging.getLogger(__name__)

DEFAULT_MASTER_ALLERGENS = (
    "Milk",
    "Egg",
    "Peanut",
    "Tree nut",
    "Soy",
    "Wheat",
    "Fish",
    "Shellfish",
    "Sesame",
)

# ── Client (single shared instance) ─────────────────────────────────────────
_client: AsyncIOMotorClient | None = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(DB_URL)
        logger.info("MongoDB client created (url=%s, db=%s)", DB_URL, DB_NAME)
    return _client


def get_db():
    return get_client()[DB_NAME]


# ── Collection helpers ───────────────────────────────────────────────────────
def sessions():
    return get_db()["sessions"]


def emotion_events():
    return get_db()["emotion_events"]


def food_events():
    return get_db()["food_events"]


def alert_events():
    return get_db()["alert_events"]


def intake_forms():
    return get_db()["intake_forms"]


# ── Roadmap/client-brief collections ─────────────────────────────────────────
def children():
    return get_db()["children"]


def devices():
    return get_db()["devices"]


def meal_sessions():
    return get_db()["meal_sessions"]


def child_status_events():
    return get_db()["child_status_events"]


def food_diary_entries():
    return get_db()["food_diary_entries"]


def allergen_logs():
    return get_db()["allergen_logs"]


def master_allergens():
    return get_db()["master_allergens"]


async def seed_master_allergens() -> int:
    """
    Ensure default global allergens exist.

    Returns
    -------
    int
        Number of allergens inserted (0 if already present).
    """
    now = datetime.utcnow()
    inserted = 0
    for name in DEFAULT_MASTER_ALLERGENS:
        existing = await master_allergens().find_one(
            {"name": {"$regex": f"^{name}$", "$options": "i"}}
        )
        if existing:
            continue
        doc = to_mongo_doc(
            MasterAllergen(
                name=name,
                category="major",
                aliases=[],
                created_at=now,
                active=True,
            )
        )
        await master_allergens().insert_one(doc)
        inserted += 1
    if inserted:
        logger.info("Seeded master_allergens: %d entries", inserted)
    return inserted


async def ensure_target_indexes() -> None:
    """Create low-risk indexes for new logical collections."""
    await intake_forms().create_index([("session_id", 1)])
    await intake_forms().create_index([("email", 1), ("created_at", -1)])

    await children().create_index([("active", 1)])
    await devices().create_index([("active", 1)])
    await devices().create_index([("location_label", 1)])

    await meal_sessions().create_index([("child_id", 1), ("started_at", -1)])
    await meal_sessions().create_index([("device_id", 1), ("started_at", -1)])
    await meal_sessions().create_index([("started_at", -1)])

    await child_status_events().create_index([("session_id", 1), ("event_timestamp", -1)])
    await child_status_events().create_index([("event_type", 1), ("event_timestamp", -1)])
    await child_status_events().create_index([("child_id", 1), ("event_timestamp", -1)])

    await food_diary_entries().create_index([("session_id", 1), ("detected_at", -1)])
    await food_diary_entries().create_index([("child_id", 1), ("detected_at", -1)])

    await allergen_logs().create_index([("session_id", 1), ("checked_at", -1)])
    await allergen_logs().create_index([("child_id", 1), ("checked_at", -1)])
    await allergen_logs().create_index([("status", 1), ("checked_at", -1)])

    logger.info("Target indexes ensured for new logical collections.")


async def ensure_collections_exist() -> None:
    """
    Proactively create expected collections so they are visible in MongoDB UI
    even before first writes occur.
    """
    expected = [
        # legacy
        "sessions",
        "emotion_events",
        "food_events",
        "alert_events",
        "intake_forms",
        # target
        "children",
        "devices",
        "meal_sessions",
        "child_status_events",
        "food_diary_entries",
        "allergen_logs",
        "master_allergens",
    ]
    existing = set(await get_db().list_collection_names())
    created = 0
    for name in expected:
        if name in existing:
            continue
        await get_db().create_collection(name)
        created += 1
    if created:
        logger.info("Created %d missing collections.", created)
