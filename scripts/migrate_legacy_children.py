"""
Backfill tester_id / email on child profiles created before per-tester scoping.

Usage:
  python scripts/migrate_legacy_children.py          # dry-run (default)
  python scripts/migrate_legacy_children.py --apply  # write updates

Links children to testers using meal_sessions, then legacy sessions, then testers by email.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: F401
import db
from bson import ObjectId

logger = logging.getLogger(__name__)


async def _link_from_meal_sessions(child_id: ObjectId) -> dict | None:
    doc = await db.meal_sessions().find_one(
        {"child_id": child_id},
        sort=[("started_at", -1)],
        projection={"tester_id": 1, "email": 1, "tester_name": 1},
    )
    if not doc:
        return None
    out: dict = {}
    if doc.get("tester_id"):
        out["tester_id"] = doc["tester_id"]
    if doc.get("email"):
        out["email"] = str(doc["email"]).strip().lower()
    if doc.get("tester_name"):
        out["tester_name"] = str(doc["tester_name"]).strip()
    return out or None


async def _link_from_legacy_session(child_id: ObjectId) -> dict | None:
    doc = await db.sessions().find_one(
        {"child_id": child_id},
        sort=[("started_at", -1)],
        projection={"tester_id": 1, "email": 1, "name": 1},
    )
    if not doc:
        return None
    out: dict = {}
    if doc.get("tester_id"):
        out["tester_id"] = doc["tester_id"]
    email = str(doc.get("email") or "").strip().lower()
    if email:
        out["email"] = email
    name = str(doc.get("name") or "").strip()
    if name:
        out["tester_name"] = name
    if out.get("email") and not out.get("tester_id"):
        tester = await db.testers().find_one({"email": out["email"]}, projection={"_id": 1, "name": 1})
        if tester:
            out["tester_id"] = tester["_id"]
            if not out.get("tester_name") and tester.get("name"):
                out["tester_name"] = str(tester["name"]).strip()
    return out or None


async def migrate(*, apply: bool) -> None:
    await db.get_client().admin.command("ping")
    cursor = db.children().find(
        {
            "$or": [
                {"tester_id": {"$exists": False}},
                {"tester_id": None},
                {"email": {"$exists": False}},
                {"email": None},
                {"email": ""},
            ]
        }
    )
    children = await cursor.to_list(length=5000)
    updated = 0
    skipped = 0

    for child in children:
        child_id = child["_id"]
        patch = await _link_from_meal_sessions(child_id)
        if not patch:
            patch = await _link_from_legacy_session(child_id)
        if not patch:
            logger.warning("No owner link found for child %s (%s)", child_id, child.get("name"))
            skipped += 1
            continue

        logger.info(
            "%s child %s (%s) -> tester_id=%s email=%s",
            "UPDATE" if apply else "WOULD UPDATE",
            child_id,
            child.get("name"),
            patch.get("tester_id"),
            patch.get("email"),
        )
        if apply:
            await db.children().update_one({"_id": child_id}, {"$set": patch})
        updated += 1

    print(f"Legacy children scanned: {len(children)}")
    print(f"{'Updated' if apply else 'Would update'}: {updated}")
    print(f"Skipped (no link): {skipped}")
    if not apply and updated:
        print("Re-run with --apply to write changes.")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Backfill tester ownership on legacy child profiles.")
    parser.add_argument("--apply", action="store_true", help="Write updates (default is dry-run).")
    args = parser.parse_args()
    asyncio.run(migrate(apply=args.apply))


if __name__ == "__main__":
    main()
