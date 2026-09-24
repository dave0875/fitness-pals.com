"""Canonical athlete-owned Goal Graph over the persisted AthleteGoal root."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
import uuid
from uuid import UUID

from fastapi import HTTPException

from app.models import AthleteGoal, AthleteGoalEvent, AthleteGoalObjective, NextSessionPlan
from app.services.athlete_intent import GOAL_LABELS, goal_brief


EVENT_ROLES = {"primary", "supporting"}
LIFECYCLE_STATES = {"planned", "completed", "cancelled", "archived"}
OPEN_PLAN_STATES = {"recommended", "adjusted", "accepted"}
MAX_EVENTS = 25
MAX_OBJECTIVES = 50


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now(value: datetime | None) -> datetime:
    result = _utc(value or datetime.now(timezone.utc))
    assert result is not None
    return result


def _owned(db, model, user_id: UUID) -> list[Any]:
    query = db.query(model)
    if hasattr(query, "filter"):
        query = query.filter(model.user_id == user_id)
    return [item for item in query.all() if getattr(item, "user_id", None) == user_id]


def _goal_for(db, user_id: UUID) -> AthleteGoal | None:
    goals = _owned(db, AthleteGoal, user_id)
    goals.sort(
        key=lambda item: _utc(getattr(item, "updated_at", None))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return goals[0] if goals else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] if cleaned else None


def _relation(value: date | None, now: datetime) -> tuple[int | None, str | None]:
    if value is None:
        return None, None
    days = (value - now.date()).days
    return days, "future" if days > 0 else "today" if days == 0 else "past"


def _event_sort_key(event: AthleteGoalEvent) -> tuple[Any, ...]:
    return (
        getattr(event, "event_date", None) is None,
        getattr(event, "event_date", None) or date.max,
        getattr(event, "priority", 50),
        str(getattr(event, "id", "")),
    )


def _objective_sort_key(objective: AthleteGoalObjective) -> tuple[Any, ...]:
    return (
        getattr(objective, "target_date", None) is None,
        getattr(objective, "target_date", None) or date.max,
        getattr(objective, "priority", 50),
        str(getattr(objective, "id", "")),
    )


def _event_payload(event: AthleteGoalEvent, now: datetime) -> dict[str, Any]:
    days, relation = _relation(event.event_date, now)
    created_at = _utc(getattr(event, "created_at", None))
    updated_at = _utc(getattr(event, "updated_at", None))
    provenance = dict(event.provenance_json or {})
    provenance.setdefault("kind", "explicit")
    provenance.setdefault("source", "goal_graph")
    provenance["canonical_model"] = "athlete_goal_event"
    provenance["record_id"] = str(event.id)
    explicit_fields = ["event.role", "event.type", "event.priority", "event.lifecycle_state"]
    for value, name in (
        (event.label, "event.label"),
        (event.event_date, "event.date"),
        (event.distance_label, "target.distance"),
        (event.target_performance, "target.performance"),
        (event.target_time_seconds, "target.time_seconds"),
    ):
        if value is not None:
            explicit_fields.append(name)
    provenance["explicit_fields"] = explicit_fields
    return {
        "id": str(event.id),
        "role": event.role,
        "type": event.event_type,
        "label": event.label,
        "date": event.event_date.isoformat() if event.event_date else None,
        "distance": event.distance_label,
        "target_performance": event.target_performance,
        "target_time_seconds": _positive_int(event.target_time_seconds),
        "priority": event.priority,
        "lifecycle": {
            "state": event.lifecycle_state,
            "created_at": created_at.isoformat() if created_at is not None else None,
            "updated_at": updated_at.isoformat() if updated_at is not None else None,
        },
        "provenance": provenance,
        "derived": {
            "days_to_event": days,
            "date_relation": relation,
            "provenance": {"kind": "derived", "basis": ["event.date", "generated_at"]},
            "caveat": (
                "Calendar relationship only. It does not predict finish time, "
                "readiness, or race outcome."
            ),
        },
    }


def _objective_payload(objective: AthleteGoalObjective, now: datetime) -> dict[str, Any]:
    days, relation = _relation(objective.target_date, now)
    provenance = dict(objective.provenance_json or {})
    provenance.setdefault("kind", "explicit")
    provenance.setdefault("source", "goal_graph")
    provenance["canonical_model"] = "athlete_goal_objective"
    provenance["record_id"] = str(objective.id)
    return {
        "id": str(objective.id),
        "event_id": str(objective.event_id) if objective.event_id else None,
        "label": objective.label,
        "date": objective.target_date.isoformat() if objective.target_date else None,
        "priority": objective.priority,
        "lifecycle": {"state": objective.lifecycle_state},
        "details": dict(objective.details_json or {}),
        "provenance": provenance,
        "derived": {
            "days_to_objective": days,
            "date_relation": relation,
            "provenance": {"kind": "derived", "basis": ["objective.date", "generated_at"]},
        },
    }


def build_goal_graph(
    db,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return one bounded canonical Goal Graph for the authenticated athlete."""
    current_time = _now(now)
    try:
        goal = _goal_for(db, user_id)
        if goal is None:
            return {
                "source": "canonical_postgres",
                "state": "unknown",
                "generated_at": current_time.isoformat(),
                "goal": None,
                "primary_event": None,
                "supporting_events": [],
                "calendar": [],
                "events": [],
                "objectives": [],
                "truncated": {"events": False, "objectives": False},
                "error": None,
            }
        events = [
            item for item in _owned(db, AthleteGoalEvent, user_id)
            if getattr(item, "goal_id", None) == goal.id
        ]
        objectives = [
            item for item in _owned(db, AthleteGoalObjective, user_id)
            if getattr(item, "goal_id", None) == goal.id
        ]
    except Exception:  # pylint: disable=broad-except
        return {
            "source": "canonical_postgres",
            "state": "error",
            "generated_at": current_time.isoformat(),
            "goal": None,
            "primary_event": None,
            "supporting_events": [],
            "calendar": [],
            "events": [],
            "objectives": [],
            "truncated": {"events": False, "objectives": False},
            "error": {
                "code": "canonical_goal_graph_read_failed",
                "message": "Canonical athlete Goal Graph is temporarily unavailable.",
            },
        }

    ordered_events = sorted(events, key=_event_sort_key)
    active_events = [item for item in ordered_events if item.lifecycle_state == "planned"]
    primary_rows = [item for item in active_events if item.role == "primary"]
    primary = min(primary_rows, key=_event_sort_key) if primary_rows else None
    supporting = [item for item in active_events if primary is None or item.id != primary.id]
    ordered_objectives = sorted(objectives, key=_objective_sort_key)
    return {
        "source": "canonical_postgres",
        "state": "known",
        "generated_at": current_time.isoformat(),
        "goal": goal_brief(goal),
        "primary_event": _event_payload(primary, current_time) if primary else None,
        "supporting_events": [_event_payload(item, current_time) for item in supporting[:MAX_EVENTS]],
        "calendar": [_event_payload(item, current_time) for item in active_events[:MAX_EVENTS]],
        "events": [_event_payload(item, current_time) for item in ordered_events[:MAX_EVENTS]],
        "objectives": [
            _objective_payload(item, current_time)
            for item in ordered_objectives[:MAX_OBJECTIVES]
        ],
        "truncated": {
            "events": len(ordered_events) > MAX_EVENTS,
            "objectives": len(ordered_objectives) > MAX_OBJECTIVES,
        },
        "error": None,
    }


def _find_event(db, user_id: UUID, goal_id: UUID, event_id: UUID) -> AthleteGoalEvent:
    event = next(
        (
            item for item in _owned(db, AthleteGoalEvent, user_id)
            if item.goal_id == goal_id and item.id == event_id
        ),
        None,
    )
    if event is None:
        raise HTTPException(status_code=404, detail="Goal event not found")
    return event


def _invalidate_open_plan(db, user_id: UUID, now: datetime) -> None:
    for plan in _owned(db, NextSessionPlan, user_id):
        if plan.status in OPEN_PLAN_STATES:
            plan.status = "skipped"
            plan.feedback_json = {"reason": "goal_graph_primary_updated"}
            plan.decided_at = now
            plan.updated_at = now


def _clear_root_event_target(goal: AthleteGoal, now: datetime) -> None:
    goal.target_date = None
    details = dict(goal.intent_json or {})
    for key in ("target_distance", "target_performance", "target_time_seconds"):
        details.pop(key, None)
    details.update(
        {
            "intent_source": "goal_graph",
            "intent_kind": "explicit",
            "confirmed_at": now.isoformat(),
        }
    )
    goal.intent_json = details
    goal.updated_at = now


def _sync_root_from_primary(goal: AthleteGoal, event: AthleteGoalEvent, now: datetime) -> None:
    details = dict(goal.intent_json or {})
    goal.goal_type = event.event_type
    goal.target_date = event.event_date
    for key, value in (
        ("target_distance", event.distance_label),
        ("target_performance", event.target_performance),
        ("target_time_seconds", _positive_int(event.target_time_seconds)),
    ):
        if value is None:
            details.pop(key, None)
        else:
            details[key] = value
    details.update(
        {
            "intent_source": "goal_graph",
            "intent_kind": "explicit",
            "confirmed_at": now.isoformat(),
        }
    )
    goal.intent_json = details
    goal.updated_at = now


def sync_primary_event_from_goal(
    db,
    user_id: UUID,
    goal: AthleteGoal,
    *,
    now: datetime | None = None,
) -> AthleteGoalEvent | None:
    """Keep legacy goal writes compatible with the canonical event graph."""
    current_time = _now(now)
    details = dict(goal.intent_json or {})
    signal = any(
        value is not None and value != ""
        for value in (
            goal.target_date,
            details.get("target_distance"),
            details.get("target_performance"),
            details.get("target_time_seconds"),
        )
    )
    events = [
        item for item in _owned(db, AthleteGoalEvent, user_id)
        if item.goal_id == goal.id and item.role == "primary" and item.lifecycle_state == "planned"
    ]
    current = min(events, key=_event_sort_key) if events else None
    if not signal:
        if current is not None:
            current.lifecycle_state = "archived"
            current.updated_at = current_time
        return None
    if current is None:
        current = AthleteGoalEvent(
            id=uuid.uuid4(),
            user_id=user_id,
            goal_id=goal.id,
            role="primary",
            event_type=goal.goal_type,
            lifecycle_state="planned",
            priority=1,
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(current)
    current.event_type = goal.goal_type
    current.event_date = goal.target_date
    current.distance_label = _text(details.get("target_distance"), 80)
    current.target_performance = _text(details.get("target_performance"), 120)
    current.target_time_seconds = _positive_int(details.get("target_time_seconds"))
    current.priority = 1
    current.lifecycle_state = "planned"
    current.provenance_json = {
        "kind": "explicit",
        "source": _text(details.get("intent_source"), 40) or "compatibility_goal",
        "basis": "athlete_goal",
    }
    current.updated_at = current_time
    return current


def save_goal_event(
    db,
    user_id: UUID,
    *,
    event_id: UUID | None,
    role: str,
    event_type: str,
    label: str | None,
    event_date: date | None,
    distance: str | None,
    target_performance: str | None,
    target_time_seconds: int | None,
    priority: int,
    lifecycle_state: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create or replace one explicit event while preserving graph history."""
    if role not in EVENT_ROLES:
        raise HTTPException(status_code=422, detail="Unsupported event role")
    if event_type not in GOAL_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported event type")
    if lifecycle_state not in LIFECYCLE_STATES:
        raise HTTPException(status_code=422, detail="Unsupported event lifecycle")
    if not 1 <= priority <= 100:
        raise HTTPException(status_code=422, detail="Priority must be between 1 and 100")
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    if goal is None:
        raise HTTPException(status_code=409, detail="Choose a goal before adding events")

    if event_id is None:
        event = AthleteGoalEvent(
            id=uuid.uuid4(),
            user_id=user_id,
            goal_id=goal.id,
            role=role,
            event_type=event_type,
            priority=priority,
            lifecycle_state=lifecycle_state,
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(event)
        was_active_primary = False
    else:
        event = _find_event(db, user_id, goal.id, event_id)
        was_active_primary = event.role == "primary" and event.lifecycle_state == "planned"

    if role == "primary" and lifecycle_state == "planned":
        for other in _owned(db, AthleteGoalEvent, user_id):
            if (
                other.goal_id == goal.id
                and other.id != event.id
                and other.role == "primary"
                and other.lifecycle_state == "planned"
            ):
                other.role = "supporting"
                other.updated_at = current_time

    event.role = role
    event.event_type = event_type
    event.label = _text(label, 160)
    event.event_date = event_date
    event.distance_label = _text(distance, 80)
    event.target_performance = _text(target_performance, 120)
    event.target_time_seconds = _positive_int(target_time_seconds)
    event.priority = priority
    event.lifecycle_state = lifecycle_state
    event.provenance_json = {"kind": "explicit", "source": "goal_graph"}
    event.updated_at = current_time

    if role == "primary" and lifecycle_state == "planned":
        _sync_root_from_primary(goal, event, current_time)
        _invalidate_open_plan(db, user_id, current_time)
    elif was_active_primary:
        remaining = [
            item for item in _owned(db, AthleteGoalEvent, user_id)
            if item.goal_id == goal.id
            and item.id != event.id
            and item.role == "primary"
            and item.lifecycle_state == "planned"
        ]
        if remaining:
            _sync_root_from_primary(goal, min(remaining, key=_event_sort_key), current_time)
        else:
            _clear_root_event_target(goal, current_time)
        _invalidate_open_plan(db, user_id, current_time)

    db.commit()
    return build_goal_graph(db, user_id, now=current_time)


def save_goal_objective(
    db,
    user_id: UUID,
    *,
    objective_id: UUID | None,
    event_id: UUID | None,
    label: str,
    target_date: date | None,
    priority: int,
    lifecycle_state: str,
    details: dict[str, Any] | None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create or replace one intermediate objective owned by this athlete."""
    if lifecycle_state not in LIFECYCLE_STATES:
        raise HTTPException(status_code=422, detail="Unsupported objective lifecycle")
    if not 1 <= priority <= 100:
        raise HTTPException(status_code=422, detail="Priority must be between 1 and 100")
    clean_label = _text(label, 200)
    if not clean_label:
        raise HTTPException(status_code=422, detail="Objective label is required")
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    if goal is None:
        raise HTTPException(status_code=409, detail="Choose a goal before adding objectives")
    if event_id is not None:
        _find_event(db, user_id, goal.id, event_id)

    if objective_id is None:
        objective = AthleteGoalObjective(
            id=uuid.uuid4(),
            user_id=user_id,
            goal_id=goal.id,
            label=clean_label,
            priority=priority,
            lifecycle_state=lifecycle_state,
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(objective)
    else:
        objective = next(
            (
                item for item in _owned(db, AthleteGoalObjective, user_id)
                if item.goal_id == goal.id and item.id == objective_id
            ),
            None,
        )
        if objective is None:
            raise HTTPException(status_code=404, detail="Goal objective not found")

    objective.event_id = event_id
    objective.label = clean_label
    objective.target_date = target_date
    objective.priority = priority
    objective.lifecycle_state = lifecycle_state
    objective.details_json = dict(details or {})
    objective.provenance_json = {"kind": "explicit", "source": "goal_graph"}
    objective.updated_at = current_time
    db.commit()
    return build_goal_graph(db, user_id, now=current_time)
