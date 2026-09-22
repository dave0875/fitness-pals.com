"""Goal-aware, persisted next-session coaching loop."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import median
from typing import Any
import uuid
from uuid import UUID

from fastapi import HTTPException

from app.models import Activity, AthleteGoal, NextSessionPlan
from app.services.activity_quality import is_run, valid_distance_m
from app.services.athlete_home import build_athlete_home


METERS_PER_MILE = 1609.344
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
TERMINAL_STATUSES = {"completed", "skipped"}
OPEN_STATUSES = {"recommended", "adjusted", "accepted"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _now(value: datetime | None) -> datetime:
    return _utc(value or datetime.now(timezone.utc))


def _owned(db, model, user_id: UUID) -> list[Any]:
    query = db.query(model).filter(model.user_id == user_id)
    return [
        item
        for item in query.all()
        if getattr(item, "user_id", None) == user_id
    ]


def _goal_for(db, user_id: UUID) -> AthleteGoal | None:
    goals = _owned(db, AthleteGoal, user_id)
    goals.sort(
        key=lambda item: getattr(item, "updated_at", None)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return goals[0] if goals else None


def _latest_plan(db, user_id: UUID) -> NextSessionPlan | None:
    plans = _owned(db, NextSessionPlan, user_id)
    plans.sort(
        key=lambda item: getattr(item, "created_at", None)
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    return plans[0] if plans else None


def _serialize_goal(goal: AthleteGoal) -> dict[str, Any]:
    return {
        "type": goal.goal_type,
        "label": GOAL_LABELS[goal.goal_type],
        "phase": goal.phase,
        "phase_label": PHASE_LABELS[goal.phase],
        "target_date": goal.target_date.isoformat() if goal.target_date else None,
    }


def _serialize_plan(plan: NextSessionPlan) -> dict[str, Any]:
    recommendation = dict(plan.recommendation_json or {})
    rationale = dict(plan.rationale_json or {})
    return {
        "id": str(plan.id),
        "status": plan.status,
        "session_purpose": plan.session_purpose,
        "scheduled_for": plan.scheduled_for.isoformat(),
        "duration_minutes": recommendation.get("duration_minutes"),
        "distance_miles": recommendation.get("distance_miles"),
        "effort_range": recommendation.get("effort_range"),
        "evidence": rationale.get("evidence", []),
        "rationale": rationale.get("rationale", []),
        "uncertainty": rationale.get("uncertainty", []),
        "feedback": plan.feedback_json,
    }


def _response(goal: AthleteGoal, plan: NextSessionPlan) -> dict[str, Any]:
    return {
        "state": plan.status,
        "goal": _serialize_goal(goal),
        "plan": _serialize_plan(plan),
        "goal_options": list(GOAL_LABELS),
        "phase_options": list(PHASE_LABELS),
        "next_decision_available": plan.status in TERMINAL_STATUSES,
    }


def _format_day(value: datetime) -> str:
    return value.strftime("%b %d").replace(" 0", " ")


def _round_minutes(value: float) -> int:
    return max(5, int(round(value / 5.0) * 5))


def _round_half_mile(value: float) -> float:
    return round(value * 2.0) / 2.0


def _recent_runs(db, user_id: UUID) -> list[Activity]:
    activities = [
        item
        for item in _owned(db, Activity, user_id)
        if getattr(item, "status", None) != "conflict" and is_run(item.sport)
    ]
    return sorted(activities, key=lambda item: _utc(item.start_time), reverse=True)


def _ranges(runs: list[Activity], phase: str) -> tuple[dict | None, dict | None]:
    durations = [
        activity.duration_seconds / 60
        for activity in runs[:4]
        if activity.duration_seconds is not None
        and 0 < activity.duration_seconds <= 6 * 60 * 60
    ]
    distances = [
        distance / METERS_PER_MILE
        for activity in runs[:4]
        if (distance := valid_distance_m(activity.distance_m, activity.sport)) is not None
    ]
    factors = {
        "build": (0.70, 0.90),
        "maintenance": (0.65, 0.85),
        "recovery": (0.50, 0.70),
    }
    low_factor, high_factor = factors[phase]

    duration_range = None
    if durations:
        baseline = float(median(durations))
        duration_low = max(15, min(50, _round_minutes(baseline * low_factor)))
        duration_high = max(
            duration_low + 5,
            min(60, _round_minutes(baseline * high_factor)),
        )
        duration_range = {"min": duration_low, "max": duration_high}

    distance_range = None
    if distances:
        baseline = float(median(distances))
        distance_low = max(1.0, _round_half_mile(baseline * low_factor))
        distance_high = max(
            distance_low + 0.5,
            _round_half_mile(baseline * high_factor),
        )
        distance_range = {"min": distance_low, "max": distance_high}

    return duration_range, distance_range


def _evidence(runs: list[Activity]) -> list[dict[str, Any]]:
    items = []
    for activity in runs[:2]:
        distance = valid_distance_m(activity.distance_m, activity.sport)
        distance_miles = round(distance / METERS_PER_MILE, 1) if distance is not None else None
        duration_minutes = (
            round(activity.duration_seconds / 60)
            if activity.duration_seconds is not None and activity.duration_seconds > 0
            else None
        )
        facts = []
        if distance_miles is not None:
            facts.append(f"{distance_miles:.1f} mi")
        if duration_minutes is not None:
            facts.append(f"{duration_minutes} min")
        fact_text = " in ".join(facts) if facts else "distance and duration unknown"
        items.append(
            {
                "activity_id": str(activity.id),
                "date": _utc(activity.start_time).date().isoformat(),
                "distance_miles": distance_miles,
                "duration_minutes": duration_minutes,
                "summary": f"{_format_day(_utc(activity.start_time))}: {fact_text}.",
            }
        )
    return items


def _uncertainty(home: dict[str, Any]) -> list[str]:
    messages = []
    for label, key in (("Workout history", "activities"), ("Sleep", "sleep"), ("Intensity", "intensity")):
        signal = home["freshness"]["signals"][key]
        state = signal["state"]
        if state == "fresh":
            continue
        data_through = signal.get("data_through")
        suffix = ""
        if data_through:
            suffix = f" (data through {date.fromisoformat(data_through[:10]).strftime('%b %d').replace(' 0', ' ')})"
        messages.append(
            f"{label} is {state}{suffix}, so it was not used as proof of readiness."
        )
    messages.append(
        "This coaching suggestion uses training history only; it is not a medical or readiness assessment."
    )
    return messages


def _create_plan(
    db,
    user_id: UUID,
    goal: AthleteGoal,
    *,
    now: datetime,
) -> NextSessionPlan | None:
    runs = _recent_runs(db, user_id)
    if not runs:
        return None
    duration_range, distance_range = _ranges(runs, goal.phase)
    if duration_range is None and distance_range is None:
        return None

    home = build_athlete_home(db, user_id, goal=goal.goal_type, now=now)
    purpose = {
        "build": "Easy aerobic support",
        "maintenance": "Consistency run",
        "recovery": "Recovery movement",
    }[goal.phase]
    latest_day = _utc(runs[0].start_time).date()
    scheduled_for = max(now.date(), latest_day + timedelta(days=1))
    evidence = _evidence(runs)
    goal_date = (
        f" for {goal.target_date.strftime('%b %d, %Y').replace(' 0', ' ')}"
        if goal.target_date
        else ""
    )
    rationale = [
        f"This supports your {GOAL_LABELS[goal.goal_type]} goal{goal_date} in the {PHASE_LABELS[goal.phase].lower()} phase.",
        "The range is scaled from your latest recorded valid run durations and distances; choose time or distance, not both.",
    ]
    previous = _latest_plan(db, user_id)
    if previous and previous.status == "completed" and previous.feedback_json:
        perceived_effort = previous.feedback_json.get("perceived_effort")
        feedback_messages = {
            "easier": "You reported that the previous session felt easier than expected; the next range remains conservative until a canonical completion is available.",
            "as_expected": "You reported that the previous session felt as expected; no extra adjustment was applied.",
            "harder": "You reported that the previous session felt harder than expected; keep this session at the easy end of the range.",
        }
        if perceived_effort in feedback_messages:
            rationale.append(feedback_messages[perceived_effort])
    plan = NextSessionPlan(
        id=uuid.uuid4(),
        user_id=user_id,
        goal_id=goal.id,
        status="recommended",
        session_purpose=purpose,
        scheduled_for=scheduled_for,
        recommendation_json={
            "duration_minutes": duration_range,
            "distance_miles": distance_range,
            "effort_range": "Easy to conversational; keep breathing controlled and choose effort by feel.",
        },
        rationale_json={
            "evidence": evidence,
            "rationale": rationale,
            "uncertainty": _uncertainty(home),
        },
        created_at=now,
        updated_at=now,
    )
    db.add(plan)
    db.commit()
    return plan


def build_today_plan(
    db,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return the signed-in athlete's current coaching decision."""
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    if goal is None:
        return {
            "state": "goal_required",
            "goal": None,
            "plan": None,
            "goal_options": list(GOAL_LABELS),
            "phase_options": list(PHASE_LABELS),
            "next_decision_available": False,
        }
    plan = _latest_plan(db, user_id)
    if plan is None:
        plan = _create_plan(db, user_id, goal, now=current_time)
    if plan is None:
        return {
            "state": "history_required",
            "goal": _serialize_goal(goal),
            "plan": None,
            "goal_options": list(GOAL_LABELS),
            "phase_options": list(PHASE_LABELS),
            "next_decision_available": False,
        }
    return _response(goal, plan)


def save_goal(
    db,
    user_id: UUID,
    *,
    goal_type: str,
    phase: str,
    target_date: date | None,
    intent_json: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist an explicit goal and start a fresh recommendation."""
    if goal_type not in GOAL_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported goal type")
    if phase not in PHASE_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported training phase")
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    if goal is None:
        goal = AthleteGoal(
            id=uuid.uuid4(),
            user_id=user_id,
            goal_type=goal_type,
            phase=phase,
            target_date=target_date,
            intent_json=intent_json,
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(goal)
    else:
        goal.goal_type = goal_type
        goal.phase = phase
        goal.target_date = target_date
        if intent_json is not None:
            goal.intent_json = intent_json
        goal.updated_at = current_time

    active = _latest_plan(db, user_id)
    if active and active.status in OPEN_STATUSES:
        active.status = "skipped"
        active.feedback_json = {"reason": "goal_updated"}
        active.decided_at = current_time
        active.updated_at = current_time
    db.commit()

    plan = _create_plan(db, user_id, goal, now=current_time)
    if plan is None:
        return build_today_plan(db, user_id, now=current_time)
    return _response(goal, plan)


def _parse_range(payload: Any, field: str) -> dict[str, float] | None:
    if payload is None:
        return None
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail=f"{field} must be a range")
    try:
        low = float(payload["min"])
        high = float(payload["max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"{field} must include min and max") from exc
    if low <= 0 or high < low:
        raise HTTPException(status_code=422, detail=f"Invalid {field} range")
    return {"min": int(low) if low.is_integer() else low, "max": int(high) if high.is_integer() else high}


def apply_plan_action(
    db,
    user_id: UUID,
    plan_id: UUID,
    *,
    action: str,
    payload: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Apply one validated state transition to an athlete-owned plan."""
    current_time = _now(now)
    plan = next(
        (item for item in _owned(db, NextSessionPlan, user_id) if item.id == plan_id),
        None,
    )
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    goal = next(
        (item for item in _owned(db, AthleteGoal, user_id) if item.id == plan.goal_id),
        None,
    )
    if goal is None:
        raise HTTPException(status_code=404, detail="Goal not found")

    allowed = {
        "recommended": {"accept", "adjust", "skip"},
        "adjusted": {"accept", "adjust", "skip", "complete"},
        "accepted": {"adjust", "skip", "complete"},
    }
    if action not in allowed.get(plan.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} a {plan.status} plan",
        )

    if action == "adjust":
        try:
            scheduled_for = date.fromisoformat(str(payload["scheduled_for"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="A valid scheduled_for date is required") from exc
        duration = _parse_range(payload.get("duration_minutes"), "duration_minutes")
        distance = _parse_range(payload.get("distance_miles"), "distance_miles")
        effort = str(payload.get("effort_range") or "").strip()
        if duration is None and distance is None:
            raise HTTPException(status_code=422, detail="Choose a time or distance range")
        if not effort:
            raise HTTPException(status_code=422, detail="Effort guidance is required")
        plan.scheduled_for = scheduled_for
        plan.recommendation_json = {
            "duration_minutes": duration,
            "distance_miles": distance,
            "effort_range": effort,
        }
        plan.adjustment_json = dict(payload)
        plan.status = "adjusted"
    elif action == "accept":
        plan.status = "accepted"
        plan.decided_at = current_time
    elif action == "skip":
        plan.status = "skipped"
        plan.feedback_json = {"note": str(payload.get("note") or "").strip() or None}
        plan.decided_at = current_time
    elif action == "complete":
        perceived_effort = str(payload.get("perceived_effort") or "")
        if perceived_effort not in {"easier", "as_expected", "harder"}:
            raise HTTPException(status_code=422, detail="Completion effort is required")
        plan.status = "completed"
        plan.feedback_json = {
            "perceived_effort": perceived_effort,
            "note": str(payload.get("note") or "").strip(),
        }
        plan.decided_at = plan.decided_at or current_time
        plan.completed_at = current_time
    plan.updated_at = current_time
    db.commit()
    return _response(goal, plan)


def create_next_plan(
    db,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return an open decision or create the next one after a terminal state."""
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    if goal is None:
        raise HTTPException(status_code=409, detail="Choose a goal first")
    current = _latest_plan(db, user_id)
    if current is not None and current.status not in TERMINAL_STATUSES:
        return _response(goal, current)
    plan = _create_plan(db, user_id, goal, now=current_time)
    if plan is None:
        return build_today_plan(db, user_id, now=current_time)
    return _response(goal, plan)
