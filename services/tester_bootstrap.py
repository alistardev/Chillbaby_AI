"""
Create caregiver (tester) runtime + MongoDB records for login flows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import config
import db
from app_state import AppState, RuntimeSession, create_runtime_session
from services.domain_writes import create_or_update_meal_session_start

logger = logging.getLogger(__name__)


def admin_staff_email() -> str:
    user = (config.CAMMY_ADMIN_USERNAME or "admin").strip().lower()
    return f"{user}@staff.chillbaby.local"


async def begin_tester_session(
    state: AppState,
    *,
    parent_name: str,
    email: str,
    company: str = "",
    source: str = "login",
) -> tuple[str, RuntimeSession]:
    """Create in-memory runtime + DB tester/session/intake records."""
    token, runtime = create_runtime_session(state)
    globalvars = runtime.globalvars
    email = email.strip().lower()
    consent_version = config.CAMMY_CONSENT_VERSION

    globalvars["parent_name"] = parent_name
    globalvars["parent_email"] = email
    globalvars["parent_company"] = company
    globalvars["intolerances"] = []
    globalvars.pop("childId", None)
    globalvars.pop("child_name", None)
    globalvars.pop("child_allergy_ids", None)

    now = datetime.now(timezone.utc)
    await db.testers().update_one(
        {"email": email},
        {
            "$set": {
                "name": parent_name,
                "email": email,
                "company": company,
                "consent_given": True,
                "consent_version": consent_version,
                "consent_at": now,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
                "active": True,
            },
        },
        upsert=True,
    )
    globalvars["consentVersion"] = consent_version
    tester = await db.testers().find_one({"email": email})
    if tester:
        globalvars["testerId"] = tester["_id"]

    new_session = {
        "tester_id": globalvars.get("testerId"),
        "name": parent_name,
        "email": email,
        "company": company,
        "intolerances": [],
        "consent_given": True,
        "consent_version": consent_version,
        "consent_at": now,
        "started_at": now,
        "video_link": None,
    }
    result = await db.sessions().insert_one(new_session)
    globalvars["insertedId"] = result.inserted_id
    globalvars["mealSessionStartedAt"] = new_session["started_at"]

    intake_doc = {
        "tester_id": globalvars.get("testerId"),
        "session_id": result.inserted_id,
        "name": parent_name,
        "email": email,
        "company": company,
        "intolerances": [],
        "consent_given": True,
        "consent_version": consent_version,
        "consent_at": now,
        "source": source,
        "created_at": now,
        "updated_at": now,
    }
    intake_result = await db.intake_forms().insert_one(intake_doc)
    globalvars["intakeFormId"] = intake_result.inserted_id

    try:
        await create_or_update_meal_session_start(
            globalvars=globalvars,
            started_at=new_session["started_at"],
        )
    except Exception:
        logger.exception("Failed additive meal_session write at %s", source)

    logger.info(
        "Tester session created: source=%s id=%s tester=%s user=%s",
        source,
        result.inserted_id,
        globalvars.get("testerId"),
        parent_name,
    )
    return token, runtime


async def begin_admin_staff_session(state: AppState) -> tuple[str, RuntimeSession]:
    """Staff monitor session for an authenticated admin."""
    name = (config.CAMMY_ADMIN_USERNAME or "Admin").strip() or "Admin"
    return await begin_tester_session(
        state,
        parent_name=name,
        email=admin_staff_email(),
        company="Staff",
        source="admin_login",
    )
