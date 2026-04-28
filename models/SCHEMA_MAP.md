# Cammy App Schema Layer

This folder defines **application-level schemas** (dataclass models) for new
logical entities before strict Mongo validators are enabled.

## Why this exists

- make document shape explicit
- normalize writes before Mongo enforcement
- preserve existing Phases 1-4 runtime behavior
- support additive migration from legacy collections

## New logical entities

- `Child`
- `Device`
- `MealSession`
- `ChildStatusEvent`
- `FoodDiaryEntry`
- `AllergenLog`
- `MasterAllergen`

Defined in `models/db_models.py`.

## Legacy to target mapping

Legacy collections are still written:

- `sessions`
- `emotion_events`
- `food_events`
- `alert_events`

Additive writes now mirror to new collections:

- `sessions` -> `meal_sessions`
- `emotion_events` -> `child_status_events` (`event_type=emotion`)
- `alert_events` child presence/audio alerts -> `child_status_events`
- `food_events` -> `food_diary_entries`
- intolerance/allergen check -> `allergen_logs` (`detected` or `not_detected`)

## Safety strategy

- No destructive replacement of legacy collections.
- New writes are guarded and best-effort.
- Set `CAMMY_ENABLE_NEW_COLLECTION_WRITES=0` to disable additive writes.

## Indexes

`db.ensure_target_indexes()` creates low-risk indexes for new collections at startup.
