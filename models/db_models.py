"""
Application-level data models for normalized MongoDB document shapes.

These models define document intent before enforcing strict Mongo validators.
They are used for additive writes to new logical collections while preserving
legacy collection writes used by existing Phases 1-4 behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any


def utcnow() -> datetime:
    return datetime.utcnow()


class EventType(str, Enum):
    COUGH = "cough"
    SNEEZE = "sneeze"
    EMOTION = "emotion"
    CHILD_PRESENT = "child_present"
    CHILD_ABSENT = "child_absent"
    TEMPERATURE = "temperature"


class AllergenStatus(str, Enum):
    DETECTED = "detected"
    NOT_DETECTED = "not_detected"
    UNKNOWN = "unknown"


@dataclass
class ChildSnapshot:
    name: str | None = None
    age_months: int | None = None
    sex: str | None = None


@dataclass
class Child:
    _id: Any | None = None
    name: str = ""
    age_months: int | None = None
    sex: str | None = None
    allergy_ids: list[Any] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    active: bool = True


@dataclass
class Device:
    _id: Any | None = None
    device_name: str = ""
    device_type: str | None = None
    location_label: str | None = None
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    active: bool = True


@dataclass
class MasterAllergen:
    _id: Any | None = None
    name: str = ""
    category: str = "major"
    aliases: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utcnow)
    active: bool = True


@dataclass
class MealSession:
    _id: Any | None = None
    child_id: Any | None = None
    device_id: Any | None = None
    location_label_snapshot: str | None = None
    child_snapshot: ChildSnapshot | None = None
    body_temperature_celsius: float | None = None
    started_at: datetime = field(default_factory=utcnow)
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    status: str = "active"
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)


@dataclass
class ChildStatusEvent:
    _id: Any | None = None
    session_id: Any | None = None
    child_id: Any | None = None
    device_id: Any | None = None
    location_label_snapshot: str | None = None
    child_snapshot: ChildSnapshot | None = None
    event_type: EventType = EventType.EMOTION
    event_timestamp: datetime = field(default_factory=utcnow)
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    body_temperature_celsius: float | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class FoodDiaryEntry:
    _id: Any | None = None
    session_id: Any | None = None
    child_id: Any | None = None
    device_id: Any | None = None
    location_label_snapshot: str | None = None
    child_snapshot: ChildSnapshot | None = None
    food_name: str = ""
    detected_at: datetime = field(default_factory=utcnow)
    detection_sources: list[str] = field(default_factory=list)
    confidence: float | None = None
    nutrition: dict[str, Any] = field(default_factory=dict)
    estimated_quantity_served_percent: float | None = None
    estimated_quantity_eaten_percent: float | None = None
    estimated_quantity_remaining_percent: float | None = None
    allergens_served: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=utcnow)


@dataclass
class AllergenLog:
    _id: Any | None = None
    session_id: Any | None = None
    child_id: Any | None = None
    device_id: Any | None = None
    food_diary_entry_id: Any | None = None
    food_name: str = ""
    checked_at: datetime = field(default_factory=utcnow)
    child_allergy_ids: list[Any] = field(default_factory=list)
    matched_allergen_ids: list[Any] = field(default_factory=list)
    matched_allergen_names: list[str] = field(default_factory=list)
    alert_triggered: bool = False
    status: AllergenStatus = AllergenStatus.UNKNOWN
    created_at: datetime = field(default_factory=utcnow)


def to_mongo_doc(model: Any, *, drop_none: bool = True) -> dict[str, Any]:
    """Convert dataclass model to Mongo-friendly dictionary."""

    def _normalize(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if is_dataclass(value):
            return _normalize(asdict(value))
        if isinstance(value, dict):
            out: dict[str, Any] = {}
            for k, v in value.items():
                nv = _normalize(v)
                if drop_none and nv is None:
                    continue
                out[k] = nv
            return out
        if isinstance(value, list):
            return [_normalize(v) for v in value]
        return value

    raw = asdict(model) if is_dataclass(model) else dict(model)
    return _normalize(raw)
