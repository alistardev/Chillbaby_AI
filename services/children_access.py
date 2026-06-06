"""
Tester-scoped access for child profile CRUD APIs.
"""

from __future__ import annotations

from typing import Any

from aiohttp import web
from bson import ObjectId

from app_state import get_runtime_session_optional
from services.admin_auth import is_admin_authenticated, require_tester_session


def _tester_scope_from_globalvars(globalvars: dict[str, Any]) -> dict[str, Any]:
    tester_id = globalvars.get("testerId")
    if tester_id:
        return {"tester_id": tester_id}
    email = (globalvars.get("parent_email") or "").strip().lower()
    if email:
        return {"email": email}
    return {}


def children_visibility_filter(
    globalvars: dict[str, Any],
    *,
    admin_mode: bool = False,
) -> dict[str, Any]:
    """Mongo filter for listing/counting children visible to this session."""
    query: dict[str, Any] = {"active": True}
    if admin_mode:
        return query
    scope = _tester_scope_from_globalvars(globalvars)
    if not scope:
        query["_id"] = {"$exists": False}
    else:
        query.update(scope)
    return query


def child_mutation_scope(
    globalvars: dict[str, Any],
    *,
    admin_mode: bool = False,
) -> dict[str, Any]:
    """Ownership filter for loading/updating a single child document."""
    if admin_mode:
        return {}
    scope = _tester_scope_from_globalvars(globalvars)
    if not scope:
        return {"_id": {"$exists": False}}
    return scope


def child_owned_by_tester(
    doc: dict[str, Any] | None,
    globalvars: dict[str, Any],
    *,
    admin_mode: bool = False,
) -> bool:
    if not doc:
        return False
    if admin_mode:
        return True
    scope = _tester_scope_from_globalvars(globalvars)
    if not scope:
        return False
    if "tester_id" in scope and doc.get("tester_id") == scope["tester_id"]:
        return True
    if "email" in scope and (doc.get("email") or "").strip().lower() == scope["email"]:
        return True
    return False


def require_children_api(request: web.Request) -> None:
    """Admin or logged-in tester may use /api/children."""
    if is_admin_authenticated(request):
        return
    require_tester_session(request)


def children_list_filter(request: web.Request, base: dict[str, Any] | None = None) -> dict[str, Any]:
    """Mongo filter for listing/querying children."""
    query = dict(base or {})
    if is_admin_authenticated(request):
        return query
    require_tester_session(request)
    runtime = get_runtime_session_optional(request)
    assert runtime is not None
    scope = _tester_scope_from_globalvars(runtime.globalvars)
    if not scope:
        raise web.HTTPForbidden(text="No tester scope on session")
    query.update(scope)
    return query


def child_mutation_filter(request: web.Request, child_id: ObjectId) -> dict[str, Any]:
    """Mongo filter for get/update/delete one child."""
    filt: dict[str, Any] = {"_id": child_id}
    if is_admin_authenticated(request):
        return filt
    require_tester_session(request)
    runtime = get_runtime_session_optional(request)
    assert runtime is not None
    scope = _tester_scope_from_globalvars(runtime.globalvars)
    if not scope:
        raise web.HTTPForbidden(text="No tester scope on session")
    filt.update(scope)
    return filt


def attach_tester_fields(doc: dict[str, Any], request: web.Request) -> dict[str, Any]:
    """Stamp tester_id/email on new child records."""
    runtime = get_runtime_session_optional(request)
    if runtime is None:
        return dict(doc)
    globalvars = runtime.globalvars
    out = dict(doc)
    tester_id = globalvars.get("testerId")
    if tester_id:
        out["tester_id"] = tester_id
    email = (globalvars.get("parent_email") or "").strip().lower()
    if email:
        out["email"] = email
    name = (globalvars.get("parent_name") or "").strip()
    if name:
        out["tester_name"] = name
    return out


async def count_active_children(
    globalvars: dict[str, Any],
    *,
    admin_mode: bool = False,
) -> int:
    import db

    return await db.children().count_documents(
        children_visibility_filter(globalvars, admin_mode=admin_mode)
    )
