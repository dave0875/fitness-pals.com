"""Durable Coach workspace grounded in canonical athlete context."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.llm.client import CoachUnavailableError, run_coach_prompt
from app.models import Activity, Conversation
from app.routes.metrics import summary
from app.services.activity_quality import valid_distance_m
from app.services.training_evidence import evidence_map, evidence_payload
from app.services.athlete_intelligence import build_athlete_intelligence, build_scenario_context
from app.services.today_plan import build_today_plan
from app.types import CurrentUserLike


HISTORY_LIMIT = 6
THREAD_SCAN_LIMIT = 200


class CoachContext(BaseModel):
    """Allow-listed context an athlete can carry into Coach."""

    source_route: str | None = Field(default=None, max_length=500)
    activity_id: UUID | None = None
    window: str | None = Field(default=None, max_length=32)
    sport: str | None = Field(default=None, max_length=32)
    goal: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=160)


class ChatRequest(BaseModel):
    """Incoming message, durable thread identity, and optional context."""

    message: str | None = Field(default=None, max_length=2000)
    thread_id: UUID | None = None
    context: CoachContext | None = None
    clear_context: bool = False
    retry_turn_id: UUID | None = None


router = APIRouter(prefix="/api", tags=["chat"])


def _metadata(row: Conversation) -> dict[str, Any]:
    value = row.metadata_json
    return value if isinstance(value, dict) else {}


def _safe_source_route(value: str | None) -> str | None:
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or "%5c" in value.lower() or value.startswith("/coach"):
        return None
    return value


def _activity_title(activity: Activity) -> str:
    metadata = activity.metadata_json if isinstance(activity.metadata_json, dict) else {}
    title = metadata.get("name") or metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()
    return (activity.sport or "Activity").replace("_", " ").title()


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _conversation_rows(db: Session, user_id: UUID) -> list[Conversation]:
    rows = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.desc())
        .limit(THREAD_SCAN_LIMIT)
        .all()
    )
    return sorted(rows, key=lambda row: row.created_at or datetime.min)


def _thread_rows(
    db: Session, user_id: UUID, thread_id: UUID | str
) -> list[Conversation]:
    key = str(thread_id)
    return [
        row
        for row in _conversation_rows(db, user_id)
        if _metadata(row).get("thread_id") == key
    ]


def _owned_activity(db: Session, user_id: UUID, activity_id: UUID) -> Activity:
    activity = (
        db.query(Activity)
        .filter(Activity.user_id == user_id, Activity.id == activity_id)
        .first()
    )
    if activity is None:
        raise HTTPException(status_code=404, detail="Activity context not found")
    return activity


def _normalize_context(
    db: Session, user_id: UUID, context: CoachContext | None
) -> dict[str, Any] | None:
    if context is None:
        return None

    payload: dict[str, Any] = {}
    source_route = _safe_source_route(context.source_route)
    if source_route:
        payload["source_route"] = source_route
    for name in ("window", "sport", "goal", "label"):
        value = getattr(context, name)
        if isinstance(value, str) and value.strip():
            payload[name] = value.strip()

    if context.activity_id is not None:
        activity = _owned_activity(db, user_id, context.activity_id)
        training_rows = evidence_map(db, [activity])
        training = evidence_payload(activity, training_rows.get(activity.id))
        payload["activity"] = {
            "id": str(activity.id),
            "title": _activity_title(activity),
            "sport": activity.sport or "unknown",
            "modality": training["modality"],
            "start_time": _iso(activity.start_time),
            "distance_m": valid_distance_m(activity.distance_m, activity.sport),
            "duration_seconds": activity.duration_seconds,
            "training_evidence": training,
            "href": f"/activities/{activity.id}",
        }
        payload["label"] = payload.get("label") or payload["activity"]["title"]
    return payload or None


def _latest_context(rows: list[Conversation]) -> dict[str, Any] | None:
    for row in reversed(rows):
        metadata = _metadata(row)
        if "context" not in metadata:
            continue
        context = metadata.get("context")
        return context if isinstance(context, dict) else None
    return None


def _history(
    rows: list[Conversation], exclude_id: Any | None = None
) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for row in rows:
        if exclude_id is not None and row.id == exclude_id:
            continue
        metadata = _metadata(row)
        if metadata.get("status", "success") != "success" or not row.answer:
            continue
        turns.append({"question": row.question, "answer": row.answer})
    return turns[-HISTORY_LIMIT:]


def _evidence(
    metrics: dict[str, Any], context: dict[str, Any] | None
) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    activity = (context or {}).get("activity")
    if isinstance(activity, dict):
        evidence.append(
            {
                "kind": "measured",
                "label": "Measured fact",
                "title": activity.get("title") or "Attached activity",
                "summary": "Canonical activity facts attached to this conversation.",
                "href": activity.get("href"),
            }
        )

    data_through = metrics.get("data_through")
    if data_through:
        evidence.append(
            {
                "kind": "measured",
                "label": "Measured fact",
                "title": "Training history freshness",
                "summary": f"Canonical activity data through {data_through}.",
                "href": "/training",
            }
        )

    training = metrics.get("training")
    if isinstance(training, dict) and training.get("activity_count"):
        modalities: list[str] = [
            modality
            for item in training.get("by_modality", [])
            if isinstance(item, dict)
            and isinstance((modality := item.get("modality")), str)
            and modality
        ]
        evidence.append(
            {
                "kind": "derived",
                "label": "Canonical training summary",
                "title": "Whole-training picture",
                "summary": (
                    f"{training.get('activity_count')} workouts across "
                    f"{', '.join(modalities) if modalities else 'known modalities'} "
                    f"in the last {training.get('window_days', 30)} days."
                ),
                "href": "/training",
            }
        )

    future = metrics.get("future_intent")
    future_payload = future.get("intent") if isinstance(future, dict) else None
    if isinstance(future_payload, dict):
        goal_payload = future_payload.get("goal")
        target_payload = future_payload.get("target")
        goal_payload = goal_payload if isinstance(goal_payload, dict) else {}
        target_payload = target_payload if isinstance(target_payload, dict) else {}
        target_bits = [
            value
            for value in (
                target_payload.get("date"),
                target_payload.get("distance"),
                target_payload.get("performance"),
            )
            if isinstance(value, str) and value
        ]
        evidence.append(
            {
                "kind": "explicit",
                "label": "Athlete intent",
                "title": goal_payload.get("label") or "Current goal",
                "summary": (
                    "Explicit current future intent"
                    + (f": {', '.join(target_bits)}." if target_bits else ".")
                ),
                "href": "/settings#goals",
            }
        )

    mileage = metrics.get("mileage")
    distance_30d = mileage.get("30d") if isinstance(mileage, dict) else None
    if isinstance(distance_30d, (int, float)):
        evidence.append(
            {
                "kind": "derived",
                "label": "Derived metric",
                "title": "30-day running volume",
                "summary": (
                    f"{distance_30d / 1609.344:.1f} miles from valid canonical runs."
                ),
                "href": "/progress?window=30d",
            }
        )

    intelligence = metrics.get("athlete_intelligence")
    briefing = intelligence.get("briefing") if isinstance(intelligence, dict) else None
    if isinstance(briefing, dict) and briefing.get("state") == "available":
        evidence.append(
            {
                "kind": "derived",
                "label": "Derived metric",
                "title": "What changed",
                "summary": briefing.get("headline"),
                "href": briefing.get("href") or "/progress",
            }
        )

    associations = intelligence.get("associations") if isinstance(intelligence, dict) else None
    if isinstance(associations, list):
        for association in associations[:1]:
            if isinstance(association, dict) and association.get("state") == "available":
                evidence.append(
                    {
                        "kind": "derived",
                        "label": "Derived metric",
                        "title": association.get("title") or "Athlete-to-self association",
                        "summary": (
                            f"{association.get('direction')} {association.get('strength')} association "
                            f"across {association.get('sample_size')} paired observations. "
                            "Association does not establish causation."
                        ),
                        "href": association.get("href") or "/progress",
                    }
                )

    scenario = metrics.get("scenario")
    if isinstance(scenario, dict) and scenario.get("state") == "projection":
        evidence.append(
            {
                "kind": "estimate",
                "label": "Estimate / model output",
                "title": "Hypothetical scenario",
                "summary": scenario.get("caveat"),
                "href": "/coach",
            }
        )

    today_plan = metrics.get("today_plan")
    plan = today_plan.get("plan") if isinstance(today_plan, dict) else None
    if isinstance(plan, dict):
        evidence.append(
            {
                "kind": "estimate",
                "label": "Estimate / model output",
                "title": plan.get("session_purpose") or "Current training decision",
                "summary": (
                    "The current saved plan is a coaching model output, not a measured fact."
                ),
                "href": "/today#todays-run",
            }
        )
    return evidence


def _actions(today_plan: dict[str, Any]) -> list[dict[str, Any]]:
    plan = today_plan.get("plan")
    if not isinstance(plan, dict) or not plan.get("id"):
        return [
            {
                "id": "review-today",
                "kind": "link",
                "label": "Review Today",
                "href": "/today#todays-run",
            }
        ]

    status = plan.get("status")
    endpoint = f"/api/today-plan/{plan['id']}"
    actions: list[dict[str, Any]] = []
    if status in {"recommended", "adjusted"}:
        actions.append(
            {
                "id": "accept-plan",
                "kind": "mutation",
                "label": "Accept this session",
                "href": endpoint,
                "method": "PATCH",
                "payload": {"action": "accept", "payload": {}},
            }
        )
    if status in {"recommended", "adjusted", "accepted"}:
        actions.extend(
            [
                {
                    "id": "skip-plan",
                    "kind": "mutation",
                    "label": "Skip this session",
                    "href": endpoint,
                    "method": "PATCH",
                    "payload": {
                        "action": "skip",
                        "payload": {"note": "Skipped from Coach"},
                    },
                    "confirm": "Skip the current saved session?",
                },
                {
                    "id": "adjust-plan",
                    "kind": "link",
                    "label": "Adjust in Today",
                    "href": "/today#todays-run",
                },
            ]
        )
    if not actions:
        actions.append(
            {
                "id": "next-decision",
                "kind": "link",
                "label": "Review next decision",
                "href": "/today#todays-run",
            }
        )
    return actions


def _turn_payload(row: Conversation) -> dict[str, Any]:
    metadata = _metadata(row)
    return {
        "id": str(row.id),
        "question": row.question,
        "answer": row.answer or None,
        "status": metadata.get("status", "success"),
        "created_at": _iso(row.created_at),
        "evidence": metadata.get("evidence") or [],
        "retryable": metadata.get("status") == "failed",
    }


def _thread_payload(
    db: Session,
    user_id: UUID,
    thread_id: UUID | str,
    rows: list[Conversation] | None = None,
) -> dict[str, Any]:
    rows = rows if rows is not None else _thread_rows(db, user_id, thread_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Coach thread not found")

    latest_metadata = _metadata(rows[-1])
    metrics = latest_metadata.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    today_plan = build_today_plan(db, user_id)
    return {
        "id": str(thread_id),
        "title": rows[0].question[:80],
        "context": _latest_context(rows),
        "freshness": {
            "state": metrics.get("state"),
            "data_through": metrics.get("data_through"),
            "generated_at": metrics.get("generated_at"),
        },
        "goal": today_plan.get("goal"),
        "plan": today_plan.get("plan"),
        "actions": _actions(today_plan),
        "turns": [_turn_payload(row) for row in rows],
    }


@router.get("/chat/threads")
def list_threads(
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List durable Coach threads owned by the current athlete."""
    groups: dict[str, list[Conversation]] = {}
    for row in _conversation_rows(db, user.id):
        thread_id = _metadata(row).get("thread_id")
        if isinstance(thread_id, str):
            groups.setdefault(thread_id, []).append(row)

    threads = []
    for thread_id, rows in groups.items():
        latest = rows[-1]
        context = _latest_context(rows) or {}
        threads.append(
            {
                "id": thread_id,
                "title": rows[0].question[:80],
                "turn_count": len(rows),
                "updated_at": _iso(latest.created_at),
                "context_label": context.get("label"),
            }
        )
    threads.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    return {"threads": threads}


@router.get("/chat/threads/{thread_id}")
def get_thread(
    thread_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return one athlete-owned thread and its current structured actions."""
    return _thread_payload(db, user.id, thread_id)


@router.patch("/chat/threads/{thread_id}/context")
def clear_thread_context(
    thread_id: UUID,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Remove visible attached context without deleting the conversation."""
    rows = _thread_rows(db, user.id, thread_id)
    if not rows:
        raise HTTPException(status_code=404, detail="Coach thread not found")
    latest = rows[-1]
    latest.metadata_json = {**_metadata(latest), "context": None}
    db.commit()
    return _thread_payload(db, user.id, thread_id, rows)


@router.post("/chat")
def chat(
    body: ChatRequest,
    user: CurrentUserLike = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Persist a Coach turn with bounded history, evidence, and retry semantics."""
    thread_id = body.thread_id or uuid4()
    rows = _thread_rows(db, user.id, thread_id) if body.thread_id else []
    if body.thread_id and not rows:
        raise HTTPException(status_code=404, detail="Coach thread not found")

    retry_row: Conversation | None = None
    if body.retry_turn_id is not None:
        if body.thread_id is None:
            raise HTTPException(
                status_code=422, detail="A thread is required to retry a turn"
            )
        retry_row = next(
            (row for row in rows if row.id == body.retry_turn_id),
            None,
        )
        if retry_row is None or _metadata(retry_row).get("status") != "failed":
            raise HTTPException(status_code=409, detail="That turn is not retryable")
        question = retry_row.question
        context = _metadata(retry_row).get("context")
        context = context if isinstance(context, dict) else None
    else:
        question = (body.message or "").strip()
        if not question:
            raise HTTPException(status_code=422, detail="Ask Coach a question")
        if body.clear_context:
            context = None
        elif body.context is not None:
            context = _normalize_context(db, user.id, body.context)
        else:
            context = _latest_context(rows)

    metrics = summary(user=user, db=db)
    intelligence = build_athlete_intelligence(db, user.id)
    metrics["today_plan"] = build_today_plan(db, user.id)
    metrics["athlete_intelligence"] = intelligence
    metrics["coaching_preferences"] = intelligence.get("preferences", [])
    metrics["scenario"] = build_scenario_context(question)
    metrics["coach_context"] = context
    metrics["conversation_history"] = _history(
        rows, exclude_id=retry_row.id if retry_row is not None else None
    )
    evidence = _evidence(metrics, context)

    try:
        reply = run_coach_prompt(question, metrics)
        status = "success"
        failure = None
    except CoachUnavailableError:
        reply = ""
        status = "failed"
        failure = "model_unavailable"

    metadata = {
        "thread_id": str(thread_id),
        "status": status,
        "context": context,
        "metrics": metrics,
        "evidence": evidence,
        "failure": failure,
    }
    if retry_row is not None:
        retry_row.answer = reply
        retry_row.metadata_json = metadata
        row = retry_row
    else:
        row = Conversation(
            id=uuid4(),
            user_id=user.id,
            question=question,
            answer=reply,
            metadata_json=metadata,
            created_at=datetime.now(timezone.utc),
        )
        db.add(row)
        rows.append(row)
    db.commit()

    thread = _thread_payload(db, user.id, thread_id, rows)
    return {
        "response": reply or None,
        "thread": thread,
        "turn": _turn_payload(row),
    }
