"""Phase 5 contracts for the deterministic Athlete Orbit decision engine."""

from app.services.athlete_decision import compose_athlete_decision


NOW = "2026-09-24T12:00:00+00:00"


def goal_graph(phase="build", days=38):
    return {
        "state": "known",
        "goal": {"type": "marathon", "phase": phase},
        "primary_event": {
            "id": "event-1",
            "type": "marathon",
            "label": "Primary marathon",
            "date": "2026-11-01",
            "priority": 1,
            "derived": {"days_to_event": days},
        },
        "supporting_events": [],
        "objectives": [],
    }


def recovery(state="fresh"):
    return {
        "state": state,
        "data_through": "2026-09-24",
        "latest": {
            "signals": {
                "sleep_duration": {
                    "value": 7.4 if state != "unknown" else None,
                    "status": "known" if state == "fresh" else state,
                },
                "overnight_hrv": {
                    "value": 41 if state != "unknown" else None,
                    "status": "known" if state == "fresh" else state,
                },
            }
        },
    }


def training(state="fresh", *, running=3, strength=1):
    count = running + strength
    return {
        "state": state,
        "data_through": "2026-09-24T10:00:00+00:00",
        "window_days": 30,
        "activity_count": count,
        "duration_seconds": count * 3600 if count else None,
        "known_duration_count": count,
        "by_modality": [
            {
                "modality": "running",
                "activity_count": running,
                "duration_seconds": running * 3600 if running else None,
                "known_duration_count": running,
            },
            {
                "modality": "strength",
                "activity_count": strength,
                "duration_seconds": strength * 3600 if strength else None,
                "known_duration_count": strength,
            },
        ],
        "cross_training_sessions": strength,
        "strength_sessions": strength,
    }


def decide(graph=None, recover=None, train=None):
    return compose_athlete_decision(
        goal_graph=graph if graph is not None else goal_graph(),
        recovery=recover if recover is not None else recovery(),
        training=train if train is not None else training(),
        generated_at=NOW,
    )


def test_fresh_canonical_context_is_actionable_without_readiness_score():
    result = decide()
    assert result["state"] == "actionable"
    assert result["action"]["code"] == "goal_aligned_session"
    assert result["freshness"] == {
        "state": "fresh",
        "recovery": "fresh",
        "training": "fresh",
    }
    assert "medical readiness" in result["provenance"]["caveat"]
    assert "score" not in result["action"]


def test_missing_goal_blocks_instead_of_inventing_intent():
    result = decide(graph={"state": "unknown", "goal": None})
    assert result["state"] == "blocked"
    assert result["action"]["code"] == "set_goal"
    assert result["evidence"]["goal"]["goal_type"] is None


def test_missing_training_history_blocks_instead_of_treating_zero_as_load():
    result = decide(train=training("unknown", running=0, strength=0))
    assert result["state"] == "blocked"
    assert result["action"]["code"] == "add_training_history"
    assert result["evidence"]["training"]["duration_seconds"] is None


def test_stale_training_requires_refresh_before_material_change():
    result = decide(train=training("stale"))
    assert result["state"] == "caution"
    assert result["action"]["code"] == "refresh_training"
    assert result["action"]["training_bias"] == "hold"


def test_stale_recovery_makes_goal_session_conservative_and_explicitly_uncertain():
    result = decide(recover=recovery("stale"))
    assert result["state"] == "caution"
    assert result["action"]["code"] == "conservative_goal_session"
    assert result["action"]["training_bias"] == "conservative"
    assert {item["code"] for item in result["uncertainty"]} == {"recovery_stale"}


def test_unknown_recovery_never_becomes_readiness_proof():
    result = decide(recover=recovery("unknown"))
    assert result["state"] == "caution"
    assert result["action"]["code"] == "conservative_goal_session"
    assert result["evidence"]["recovery"]["known_signals"] == []
    assert result["evidence"]["recovery"]["unavailable_signals"] == [
        "overnight_hrv",
        "sleep_duration",
    ]


def test_explicit_recovery_phase_wins_over_near_event_pressure():
    result = decide(graph=goal_graph(phase="recovery", days=3))
    assert result["state"] == "actionable"
    assert result["action"]["code"] == "recovery_focused_session"
    assert result["action"]["training_bias"] == "recovery"
    assert result["conflicts"][0]["code"] == "recovery_phase_vs_event_pressure"


def test_past_planned_primary_event_becomes_visible_conflict():
    result = decide(graph=goal_graph(days=-2))
    assert result["state"] == "caution"
    assert result["action"]["code"] == "review_goal_calendar"
    assert result["conflicts"][0]["code"] == "past_primary_event"


def test_cross_training_is_retained_as_first_class_decision_evidence():
    result = decide(train=training(running=1, strength=4))
    modalities = {
        item["modality"]: item["activity_count"]
        for item in result["evidence"]["training"]["by_modality"]
    }
    assert modalities == {"running": 1, "strength": 4}
    whole_training = next(
        item for item in result["rationale"] if item["code"] == "whole_training_context"
    )
    assert "4 non-running" in whole_training["summary"]
    assert "1 running" in whole_training["summary"]
