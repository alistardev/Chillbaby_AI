"""
Shared application state container.

This centralizes mutable runtime state that was previously held in module-level
globals, and provides a single accessor for route handlers/services.
"""

from dataclasses import dataclass, field
from typing import Any


APP_STATE_KEY = "app_state"


@dataclass
class AppState:
    connections: dict[str, Any] = field(default_factory=dict)
    globalvars: dict[str, Any] = field(
        default_factory=lambda: {
            "processing": False,
            "intolerances": [],
            "mainFood": "",
            "filepath": "",
            "filename": "",
            "insertedId": "",
            "video_url": "",
            "alert_msg": "",
            "processed": False,
        }
    )


def get_state(request) -> AppState:
    return request.app[APP_STATE_KEY]
