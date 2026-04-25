"""
Async MongoDB client using motor.
Exposes collection references used across the application.

Collections
-----------
sessions       – one document per user monitoring session
emotion_events – timestamped emotion snapshots
food_events    – timestamped food-detection results
alert_events   – child_missing / cough alerts  (Phases 2 & 3)
"""

import logging
from motor.motor_asyncio import AsyncIOMotorClient
from config import DB_URL, DB_NAME

logger = logging.getLogger(__name__)

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
