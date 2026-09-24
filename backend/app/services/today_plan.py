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
from app.services.athlete_goal_graph import build_goal_graph, sync_primary_event_from_goal
from app.services.athlete_intent import (
    GOAL_LABELS,
    PHASE_LABELS,
    build_future_intent,
    goal_brief,
)


METERS_PER_MILE = 1609.344
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
    return goal_brief(goal)


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


def _activity_title(activity: Activity) -> str:
    metadata = activity.metadata_json if isinstance(activity.metadata_json, dict) else {}
    title = metadata.get("name") or metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return (activity.sport or "Activity").replace("_", " ").title()


def _activity_payload(activity: Activity) -> dict[str, Any]:
    distance = valid_distance_m(activity.distance_m, activity.sport)
    return {
        "id": str(activity.id),
        "title": _activity_title(activity),
        "date": _utc(activity.start_time).date().isoformat(),
        "distance_miles": round(distance / METERS_PER_MILE, 1) if distance is not None else None,
        "duration_minutes": (
            round(activity.duration_seconds / 60)
            if activity.duration_seconds is not None and activity.duration_seconds > 0
            else None
        ),
        "href": f"/activities/{activity.id}",
    }


def _volume_summary(runs: list[Activity], start: date, end: date) -> dict[str, Any]:
    selected = [
        activity
        for activity in runs
        if start <= _utc(activity.start_time).date() <= end
    ]
    distance_m = sum(
        distance
        for activity in selected
        if (distance := valid_distance_m(activity.distance_m, activity.sport)) is not None
    )
    return {
        "runs": len(selected),
        "miles": round(distance_m / METERS_PER_MILE, 1),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _goal_trajectory(
    db,
    user_id: UUID,
    goal: AthleteGoal | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    runs = _recent_runs(db, user_id)
    today = now.date()
    last_7 = _volume_summary(runs, today - timedelta(days=6), today)
    prior_7 = _volume_summary(runs, today - timedelta(days=13), today - timedelta(days=7))
    last_28 = _volume_summary(runs, today - timedelta(days=27), today)
    days_to_target = None
    if goal is not None and goal.target_date is not None:
        days_to_target = (goal.target_date - today).days
    return {
        "goal": _serialize_goal(goal) if goal is not None else None,
        "days_to_target": days_to_target,
        "last_7_days": last_7,
        "previous_7_days": prior_7,
        "last_28_days": last_28,
        "interpretation": (
            "These are trajectory inputs, not a readiness score or prediction."
        ),
    }


def _rolling_week(
    db,
    user_id: UUID,
    plan: NextSessionPlan | None,
    *,
    now: datetime,
) -> dict[str, Any]:
    today = now.date()
    start = today - timedelta(days=2)
    end = start + timedelta(days=6)
    activities_by_date: dict[date, list[Activity]] = {}
    for activity in _recent_runs(db, user_id):
        activity_date = _utc(activity.start_time).date()
        if start <= activity_date <= end:
            activities_by_date.setdefault(activity_date, []).append(activity)

    days = []
    for offset in range(7):
        day = start + timedelta(days=offset)
        activities = [
            _activity_payload(activity)
            for activity in sorted(
                activities_by_date.get(day, []),
                key=lambda item: _utc(item.start_time),
            )
        ]
        plan_payload = None
        if plan is not None and plan.scheduled_for == day:
            plan_payload = {
                "id": str(plan.id),
                "status": plan.status,
                "session_purpose": plan.session_purpose,
            }
        days.append(
            {
                "date": day.isoformat(),
                "is_today": day == today,
                "activities": activities,
                "plan": plan_payload,
                "state": (
                    "completed"
                    if activities
                    else "planned"
                    if plan_payload is not None
                    else "open"
                ),
            }
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": days,
        "outside_window_plan": (
            {
                "date": plan.scheduled_for.isoformat(),
                "session_purpose": plan.session_purpose,
                "status": plan.status,
            }
            if plan is not None and not (start <= plan.scheduled_for <= end)
            else None
        ),
    }


def _within_range(value: float | int | None, range_value: Any) -> bool:
    if value is None or not isinstance(range_value, dict):
        return False
    try:
        low = float(range_value["min"])
        high = float(range_value["max"])
    except (KeyError, TypeError, ValueError):
        return False
    tolerance = 0.25
    return low * (1 - tolerance) <= float(value) <= high * (1 + tolerance)


def _matching_activity(
    db,
    user_id: UUID,
    plan: NextSessionPlan | None,
) -> dict[str, Any] | None:
    if plan is None or plan.status not in {"adjusted", "accepted"}:
        return None
    recommendation = dict(plan.recommendation_json or {})
    matches = []
    for activity in _recent_runs(db, user_id):
        activity_time = _utc(activity.start_time)
        if activity_time.date() != plan.scheduled_for:
            continue
        if plan.created_at is not None and activity_time < _utc(plan.created_at):
            continue
        duration_minutes = (
            activity.duration_seconds / 60
            if activity.duration_seconds is not None and activity.duration_seconds > 0
            else None
        )
        distance = valid_distance_m(activity.distance_m, activity.sport)
        distance_miles = distance / METERS_PER_MILE if distance is not None else None
        if _within_range(duration_minutes, recommendation.get("duration_minutes")) or _within_range(
            distance_miles, recommendation.get("distance_miles")
        ):
            matches.append(activity)
    if len(matches) != 1:
        return None
    payload = _activity_payload(matches[0])
    payload["basis"] = "Same scheduled day and within the saved time or distance range."
    return payload


def build_today_context(
    db,
    user_id: UUID,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return non-mutating decision context for the focused Today surface."""
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    plan = _latest_plan(db, user_id)
    home = build_athlete_home(
        db,
        user_id,
        goal=goal.goal_type if goal is not None else "consistency",
        now=current_time,
    )
    return {
        "generated_at": current_time.isoformat(),
        "freshness": home.get("freshness"),
        "future_intent": build_future_intent(db, user_id, now=current_time),
        "goal_graph": build_goal_graph(db, user_id, now=current_time),
        "week": _rolling_week(db, user_id, plan, now=current_time),
        "trajectory": _goal_trajectory(db, user_id, goal, now=current_time),
        "match": _matching_activity(db, user_id, plan),
    }


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
    intent_source: str = "today",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Persist an explicit goal and start a fresh recommendation."""
    if goal_type not in GOAL_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported goal type")
    if phase not in PHASE_LABELS:
        raise HTTPException(status_code=422, detail="Unsupported training phase")
    current_time = _now(now)
    goal = _goal_for(db, user_id)
    existing_intent = (
        dict(goal.intent_json or {})
        if goal is not None and isinstance(goal.intent_json, dict)
        else {}
    )
    if intent_json is not None:
        existing_intent.update(intent_json)
    existing_intent.update(
        {
            "intent_source": intent_source,
            "intent_kind": "explicit",
            "confirmed_at": current_time.isoformat(),
        }
    )
    if goal is None:
        goal = AthleteGoal(
            id=uuid.uuid4(),
            user_id=user_id,
            goal_type=goal_type,
            phase=phase,
            target_date=target_date,
            intent_json=existing_intent,
            created_at=current_time,
            updated_at=current_time,
        )
        db.add(goal)
    else:
        goal.goal_type = goal_type
        goal.phase = phase
        goal.target_date = target_date
        goal.intent_json = existing_intent
        goal.updated_at = current_time

    sync_primary_event_from_goal(db, user_id, goal, now=current_time)

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
        "recommended": {"accept", "adjust", "move", "skip"},
        "adjusted": {"accept", "adjust", "move", "skip", "complete"},
        "accepted": {"adjust", "move", "skip", "complete"},
    }
    if action not in allowed.get(plan.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot {action} a {plan.status} plan",
        )

    if action == "adjust":
        scheduled_for = plan.scheduled_for
        if payload.get("scheduled_for") is not None:
            try:
                scheduled_for = date.fromisoformat(str(payload["scheduled_for"]))
            except (TypeError, ValueError) as exc:
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
    elif action == "move":
        try:
            scheduled_for = date.fromisoformat(str(payload["scheduled_for"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="A valid scheduled_for date is required") from exc
        plan.adjustment_json = {
            **(plan.adjustment_json if isinstance(plan.adjustment_json, dict) else {}),
            "moved_from": plan.scheduled_for.isoformat(),
            "scheduled_for": scheduled_for.isoformat(),
        }
        plan.scheduled_for = scheduled_for
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
        matched_activity_id = str(payload.get("matched_activity_id") or "").strip()
        completion_source = "manual"
        if matched_activity_id:
            match = _matching_activity(db, user_id, plan)
            if match is None or match["id"] != matched_activity_id:
                raise HTTPException(
                    status_code=422,
                    detail="Matched activity is no longer a safe completion candidate",
                )
            completion_source = "canonical_match"
        plan.status = "completed"
        plan.feedback_json = {
            "perceived_effort": perceived_effort,
            "note": str(payload.get("note") or "").strip(),
            "completion_source": completion_source,
            "matched_activity_id": matched_activity_id or None,
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
