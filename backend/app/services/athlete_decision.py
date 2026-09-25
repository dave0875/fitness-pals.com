"""Deterministic unified athlete decision composed from canonical evidence."""

from __future__ import annotations

from typing import Any


DECISION_VERSION = "athlete_orbit_v1"
RECOVERY_STATES = {"fresh", "stale", "unknown", "error"}
TRAINING_STATES = {"fresh", "stale", "unknown", "error"}


def _mapping(value: object | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _domain_state(value: object | None, allowed: set[str]) -> str:
    state = str(value or "unknown")
    return state if state in allowed else "unknown"


def _freshness(recovery_state: str, training_state: str) -> str:
    states = {recovery_state, training_state}
    if "error" in states:
        return "degraded"
    if states == {"fresh"}:
        return "fresh"
    if states == {"unknown"}:
        return "unknown"
    return "partial"


def _modality_counts(training: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in training.get("by_modality") or []:
        if not isinstance(item, dict):
            continue
        modality = item.get("modality")
        count = item.get("activity_count")
        if isinstance(modality, str) and isinstance(count, int):
            counts[modality] = count
    return counts


def _recovery_evidence(recovery: dict[str, Any]) -> dict[str, Any]:
    latest = _mapping(recovery.get("latest"))
    signals = _mapping(latest.get("signals"))
    known: list[str] = []
    stale: list[str] = []
    unavailable: list[str] = []
    for name, raw in signals.items():
        signal = _mapping(raw)
        status = signal.get("status")
        if signal.get("value") is None:
            unavailable.append(str(name))
        else:
            known.append(str(name))
            if status == "stale":
                stale.append(str(name))
    return {
        "state": _domain_state(recovery.get("state"), RECOVERY_STATES),
        "data_through": recovery.get("data_through"),
        "known_signals": sorted(known),
        "stale_signals": sorted(stale),
        "unavailable_signals": sorted(unavailable),
    }


def _training_evidence(training: dict[str, Any]) -> dict[str, Any]:
    return {
        "state": _domain_state(training.get("state"), TRAINING_STATES),
        "data_through": training.get("data_through"),
        "window_days": training.get("window_days"),
        "activity_count": training.get("activity_count"),
        "duration_seconds": training.get("duration_seconds"),
        "known_duration_count": training.get("known_duration_count"),
        "by_modality": [
            {
                "modality": item.get("modality"),
                "activity_count": item.get("activity_count"),
                "duration_seconds": item.get("duration_seconds"),
                "known_duration_count": item.get("known_duration_count"),
            }
            for item in training.get("by_modality") or []
            if isinstance(item, dict)
        ],
        "cross_training_sessions": training.get("cross_training_sessions"),
        "strength_sessions": training.get("strength_sessions"),
    }


def _goal_evidence(goal_graph: dict[str, Any]) -> dict[str, Any]:
    goal = _mapping(goal_graph.get("goal"))
    primary = _mapping(goal_graph.get("primary_event"))
    derived = _mapping(primary.get("derived"))
    return {
        "state": str(goal_graph.get("state") or "unknown"),
        "goal_type": goal.get("type"),
        "phase": goal.get("phase"),
        "primary_event": (
            {
                "id": primary.get("id"),
                "type": primary.get("type"),
                "label": primary.get("label"),
                "date": primary.get("date"),
                "days_to_event": derived.get("days_to_event"),
                "priority": primary.get("priority"),
            }
            if primary
            else None
        ),
        "supporting_event_count": len(goal_graph.get("supporting_events") or []),
        "objective_count": len(goal_graph.get("objectives") or []),
    }


def compose_athlete_decision(
    *,
    goal_graph: dict[str, Any],
    recovery: dict[str, Any],
    training: dict[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    """Answer what to do next without inventing readiness or missing evidence."""
    goal = _goal_evidence(goal_graph)
    recovery_evidence = _recovery_evidence(recovery)
    training_evidence = _training_evidence(training)
    recovery_state = recovery_evidence["state"]
    training_state = training_evidence["state"]
    phase = goal.get("phase")
    primary = _mapping(goal.get("primary_event"))
    days_to_event = primary.get("days_to_event")
    activity_count = training_evidence.get("activity_count")
    activity_count = activity_count if isinstance(activity_count, int) else 0
    modality_counts = _modality_counts(training)

    rationale: list[dict[str, str]] = []
    uncertainty: list[dict[str, str]] = []
    conflicts: list[dict[str, str]] = []

    if training_state == "error":
        state = "blocked"
        action = {
            "code": "review_training_data",
            "label": "Review your training data connection",
            "href": "/settings",
            "priority": "data",
            "training_bias": None,
        }
        rationale.append(
            {
                "code": "training_read_error",
                "summary": "Canonical training evidence could not be read, so the engine will not manufacture a session decision.",
            }
        )
    elif training_state == "stale":
        state = "caution"
        action = {
            "code": "refresh_training",
            "label": "Refresh training history before a material plan change",
            "href": "/settings",
            "priority": "data",
            "training_bias": "hold",
        }
        rationale.append(
            {
                "code": "training_stale",
                "summary": "Recent training evidence is stale, so old load cannot justify increasing or materially changing the next session.",
            }
        )
    elif goal.get("state") != "known" or not goal.get("goal_type"):
        state = "blocked"
        action = {
            "code": "set_goal",
            "label": "Define your current goal",
            "href": "/settings#goals",
            "priority": "goal",
            "training_bias": None,
        }
        rationale.append(
            {
                "code": "goal_missing",
                "summary": "No current athlete-owned goal is available to anchor the next decision.",
            }
        )
    elif activity_count == 0 or training_state == "unknown":
        state = "blocked"
        action = {
            "code": "add_training_history",
            "label": "Add training history before changing the plan",
            "href": "/training",
            "priority": "data",
            "training_bias": None,
        }
        rationale.append(
            {
                "code": "training_history_missing",
                "summary": "No recent canonical training history is available to ground a next-session decision.",
            }
        )
    elif isinstance(days_to_event, int) and days_to_event < 0:
        state = "caution"
        action = {
            "code": "review_goal_calendar",
            "label": "Review the primary event before planning forward",
            "href": "/settings#goals",
            "priority": "goal",
            "training_bias": None,
        }
        conflicts.append(
            {
                "code": "past_primary_event",
                "resolution": "The Goal Graph stays authoritative, but a planned primary event in the past must be corrected before it drives new training.",
            }
        )
    elif phase == "recovery":
        state = "actionable"
        action = {
            "code": "recovery_focused_session",
            "label": "Keep the next session recovery-focused",
            "href": "/today#todays-run",
            "priority": "recovery",
            "training_bias": "recovery",
        }
        rationale.append(
            {
                "code": "explicit_recovery_phase",
                "summary": "The athlete explicitly set a recovery phase, so recovery-focused intent outranks calendar pressure.",
            }
        )
        if isinstance(days_to_event, int) and 0 <= days_to_event <= 7:
            conflicts.append(
                {
                    "code": "recovery_phase_vs_event_pressure",
                    "resolution": "The explicit recovery phase wins; a nearby event does not silently convert the decision into harder training.",
                }
            )
    elif recovery_state == "stale":
        state = "caution"
        action = {
            "code": "conservative_goal_session",
            "label": "Keep the next goal-aligned session conservative",
            "href": "/today#todays-run",
            "priority": "recovery",
            "training_bias": "conservative",
        }
        uncertainty.append(
            {
                "code": "recovery_stale",
                "summary": "Recovery evidence is stale and is not used as proof of current readiness.",
            }
        )
    elif recovery_state in {"unknown", "error"}:
        state = "caution"
        action = {
            "code": "conservative_goal_session",
            "label": "Use a conservative goal-aligned next session",
            "href": "/today#todays-run",
            "priority": "recovery",
            "training_bias": "conservative",
        }
        uncertainty.append(
            {
                "code": "recovery_unknown",
                "summary": "Current recovery evidence is unavailable, so the decision stays conservative instead of assuming readiness.",
            }
        )
    else:
        state = "actionable"
        action = {
            "code": "goal_aligned_session",
            "label": "Review the goal-aligned next session",
            "href": "/today#todays-run",
            "priority": "goal",
            "training_bias": "goal_aligned",
        }
        rationale.append(
            {
                "code": "current_canonical_context",
                "summary": "Goal, recent whole-training history, and recovery freshness are current enough to support the normal goal-aligned workflow.",
            }
        )

    if goal.get("goal_type"):
        rationale.append(
            {
                "code": "goal_anchor",
                "summary": (
                    f"The canonical Goal Graph anchors this decision to the athlete's "
                    f"{goal.get('goal_type')} goal and {phase or 'unknown'} phase."
                ),
            }
        )

    cross_training = training_evidence.get("cross_training_sessions")
    if isinstance(cross_training, int) and cross_training > 0:
        running_count = modality_counts.get("running", 0)
        rationale.append(
            {
                "code": "whole_training_context",
                "summary": (
                    f"Whole-training evidence includes {cross_training} non-running session(s) "
                    f"alongside {running_count} running session(s); cross-training is not discarded."
                ),
            }
        )

    if recovery_state == "fresh":
        rationale.append(
            {
                "code": "recovery_freshness",
                "summary": "Recovery evidence is current context, but no recovery value is converted into a medical or physiological readiness score.",
            }
        )
    elif recovery_state == "stale" and not any(
        item.get("code") == "recovery_stale" for item in uncertainty
    ):
        uncertainty.append(
            {
                "code": "recovery_stale",
                "summary": "Recovery evidence is stale and is not used as proof of current readiness.",
            }
        )

    return {
        "source": "canonical_postgres",
        "version": DECISION_VERSION,
        "state": state,
        "generated_at": generated_at,
        "action": action,
        "freshness": {
            "state": _freshness(recovery_state, training_state),
            "recovery": recovery_state,
            "training": training_state,
        },
        "rationale": rationale,
        "uncertainty": uncertainty,
        "conflicts": conflicts,
        "evidence": {
            "goal": goal,
            "recovery": recovery_evidence,
            "training": training_evidence,
        },
        "provenance": {
            "kind": "derived",
            "basis": [
                "athlete_goal_graph",
                "athlete_state_recovery",
                "whole_training_summary",
            ],
            "caveat": (
                "Decision support only. It does not establish medical readiness, diagnose a condition, "
                "or predict a race outcome."
            ),
        },
        "error": None,
    }
