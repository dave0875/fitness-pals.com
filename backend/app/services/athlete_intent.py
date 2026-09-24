"""Canonical athlete-owned future intent over the existing AthleteGoal row."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.models import AthleteGoal


GOAL_LABELS = {
    "marathon": "Marathon",
    "half": "Half marathon",
    "race": "Race preparation",
    "consistency": "Consistency",
    "aerobic_fitness": "Aerobic fitness",
    "recovery": "Recovery",
    "healthy_activity": "Healthy activity",
    "other": "Another goal",
    "not_sure": "I’m not sure",
}
PHASE_LABELS = {
    "build": "Training / build",
    "maintenance": "Maintenance",
    "recovery": "Post-race / recovery",
}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned[:limit] if cleaned else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _goal_for(db, user_id: UUID) -> AthleteGoal | None:
    """Resolve one athlete's current explicit goal with a defensive ownership check."""
    query = db.query(AthleteGoal)
    if hasattr(query, "filter"):
        query = query.filter(AthleteGoal.user_id == user_id)
    rows = [
        row
        for row in query.all()
        if getattr(row, "user_id", None) == user_id
    ]
    rows.sort(
        key=lambda row: _utc(getattr(row, "updated_at", None))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return rows[0] if rows else None


def goal_brief(goal: AthleteGoal) -> dict[str, Any]:
    """Return the backwards-compatible goal shape used by Today."""
    return {
        "type": goal.goal_type,
        "label": GOAL_LABELS.get(
            goal.goal_type, goal.goal_type.replace("_", " ").title()
        ),
        "phase": goal.phase,
        "phase_label": PHASE_LABELS.get(
            goal.phase, goal.phase.replace("_", " ").title()
        ),
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
    }


def _explicit_fields(goal: AthleteGoal, details: dict[str, Any]) -> list[str]:
    fields = ["goal.type", "goal.phase"]
    if goal.target_date is not None:
        fields.append("target.date")
    for key, name in (
        ("target_distance", "target.distance"),
        ("target_performance", "target.performance"),
        ("target_time_seconds", "target.time_seconds"),
        ("custom_goal", "goal.custom"),
    ):
        if details.get(key) not in (None, ""):
            fields.append(name)
    return fields


def _intent(goal: AthleteGoal, now: datetime) -> dict[str, Any]:
    details = dict(goal.intent_json or {})
    target_time_seconds = _positive_int(details.get("target_time_seconds"))
    target_date = goal.target_date

    days_to_target = None
    target_date_relation = None
    if target_date is not None:
        days_to_target = (target_date - now.date()).days
        target_date_relation = (
            "future" if days_to_target > 0 else "today" if days_to_target == 0 else "past"
        )

    source = _text(details.get("intent_source"), 40) or "athlete_goal"
    provenance = {
        "kind": "explicit",
        "source": source,
        "canonical_model": "athlete_goal",
        "record_id": str(goal.id) if getattr(goal, "id", None) else None,
        "explicit_fields": _explicit_fields(goal, details),
    }

    return {
        "goal": {
            "type": goal.goal_type,
            "label": GOAL_LABELS.get(
                goal.goal_type, goal.goal_type.replace("_", " ").title()
            ),
            "phase": goal.phase,
            "phase_label": PHASE_LABELS.get(
                goal.phase, goal.phase.replace("_", " ").title()
            ),
            "custom": _text(details.get("custom_goal"), 240),
        },
        "target": {
            "date": target_date.isoformat() if target_date else None,
            "distance": _text(details.get("target_distance"), 80),
            "performance": _text(details.get("target_performance"), 120),
            "time_seconds": target_time_seconds,
        },
        "lifecycle": {
            "state": "current",
            "created_at": (
                _utc(getattr(goal, "created_at", None)).isoformat()
                if _utc(getattr(goal, "created_at", None))
                else None
            ),
            "updated_at": (
                _utc(getattr(goal, "updated_at", None)).isoformat()
                if _utc(getattr(goal, "updated_at", None))
                else None
            ),
            "ended_at": None,
        },
        "provenance": provenance,
        "derived": {
            "days_to_target": days_to_target,
            "target_date_relation": target_date_relation,
            "provenance": {
                "kind": "derived",
                "basis": ["target.date", "generated_at"],
            },
            "caveat": (
                "Calendar relationship only. It does not predict finish time, "
                "readiness, or race outcome."
            ),
        },
    }


def build_future_intent(
    db,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return bounded current future intent without inferring unstated targets."""
    current_time = _utc(now or datetime.now(timezone.utc))
    assert current_time is not None
    try:
        goal = _goal_for(db, user_id)
    except Exception:  # pylint: disable=broad-except
        return {
            "source": "canonical_postgres",
            "state": "error",
            "generated_at": current_time.isoformat(),
            "intent": None,
            "error": {
                "code": "canonical_future_intent_read_failed",
                "message": "Canonical athlete intent is temporarily unavailable.",
            },
        }

    return {
        "source": "canonical_postgres",
        "state": "known" if goal is not None else "unknown",
        "generated_at": current_time.isoformat(),
        "intent": _intent(goal, current_time) if goal is not None else None,
        "error": None,
    }
