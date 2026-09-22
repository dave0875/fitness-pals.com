"""Phase 7 contracts for explainable athlete intelligence."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from app.models import Activity, AthleteGoal, Conversation, SleepSession
from app.routes import chat as chat_routes
from app.services.athlete_intelligence import (
    MIN_ASSOCIATION_PAIRS,
    build_athlete_intelligence,
    build_scenario_context,
    save_coaching_preferences,
)


class FakeQuery:
    """Small SQLAlchemy-like facade for deterministic service tests."""

    def __init__(self, items):
        self.items = list(items)

    def filter(self, *criteria):
        del criteria
        return self

    def order_by(self, *criteria):
        del criteria
        return self

    def limit(self, value):
        self.items = self.items[:value]
        return self

    def all(self):
        return list(self.items)


class FakeSession:
    """Return only rows of the requested model and support in-memory writes."""

    def __init__(self, items=None):
        self.items = list(items or [])
        self.commits = 0

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])

    def add(self, item):
        self.items.append(item)

    def commit(self):
        self.commits += 1


def make_activity(user_id, when, miles, duration_minutes=60):
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=when,
        duration_seconds=duration_minutes * 60,
        distance_m=miles * 1609.344,
        sport="run",
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json={"name": "Canonical run", "intensity": "easy"},
    )


def make_sleep(user_id, day, hours):
    return SleepSession(
        id=uuid.uuid4(),
        user_id=user_id,
        provider="garmin",
        daily_sleep_id=int(day.strftime("%Y%m%d")),
        calendar_date=day,
        summary_json={"sleepTimeSeconds": int(hours * 3600)},
    )


def make_goal(user_id, now):
    return AthleteGoal(
        id=uuid.uuid4(),
        user_id=user_id,
        goal_type="marathon",
        phase="build",
        target_date=now.date() + timedelta(days=40),
        intent_json={
            "target_performance": "finish goal",
            "custom_goal": None,
        },
        created_at=now - timedelta(days=30),
        updated_at=now - timedelta(days=1),
    )


def test_intelligence_is_athlete_scoped_and_briefing_compares_self():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    rows = [
        make_goal(athlete_id, now),
        make_activity(athlete_id, now - timedelta(days=1), 8),
        make_activity(athlete_id, now - timedelta(days=3), 6),
        make_activity(athlete_id, now - timedelta(days=8), 5),
        make_activity(other_id, now - timedelta(days=1), 100),
        make_sleep(athlete_id, (now - timedelta(days=1)).date(), 7.5),
        make_sleep(other_id, (now - timedelta(days=1)).date(), 12),
    ]

    result = build_athlete_intelligence(FakeSession(rows), athlete_id, now=now)

    assert result["scope"] == "athlete_only"
    assert result["briefing"]["state"] == "available"
    assert "increased" in result["briefing"]["headline"].lower()
    assert result["athlete_to_self"]["current"]["miles"] == 14.0
    assert result["athlete_to_self"]["previous"]["miles"] == 5.0
    assert result["trajectory"]["days_to_target"] == 40
    assert result["trajectory"]["interpretation"].endswith(
        "not a readiness score or prediction."
    )
    assert "100" not in str(result["athlete_to_self"])


def test_intelligence_keeps_missing_and_stale_signals_explicit():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    old_run = make_activity(athlete_id, now - timedelta(days=10), 5)
    result = build_athlete_intelligence(
        FakeSession([make_goal(athlete_id, now), old_run]),
        athlete_id,
        now=now,
    )

    assert result["freshness"]["state"] == "partial"
    assert result["freshness"]["signals"]["activities"]["state"] == "stale"
    assert result["freshness"]["signals"]["sleep"]["state"] == "unknown"
    assert result["associations"][0]["state"] == "insufficient"
    assert result["associations"][0]["correlation"] is None


def test_n_of_1_association_requires_sample_and_never_claims_causation():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    rows = [make_goal(athlete_id, now)]
    for offset in range(MIN_ASSOCIATION_PAIRS):
        when = now - timedelta(days=offset + 1)
        rows.append(make_activity(athlete_id, when, 4 + offset, 35 + offset * 8))
        rows.append(make_sleep(athlete_id, when.date(), 6.0 + offset * 0.25))

    result = build_athlete_intelligence(FakeSession(rows), athlete_id, now=now)
    association = result["associations"][0]

    assert association["state"] == "available"
    assert association["sample_size"] == MIN_ASSOCIATION_PAIRS
    assert association["direction"] in {"positive", "negative", "flat"}
    assert association["strength"] in {"weak", "moderate", "strong"}
    assert association["correlation"] is not None
    assert "does not establish" in association["caveat"].lower()
    assert "caused" in association["caveat"].lower()


def test_preferences_are_deliberate_preserve_goal_intent_and_can_be_cleared():
    now = datetime(2026, 9, 22, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    goal = make_goal(athlete_id, now)
    db = FakeSession([goal])

    saved = save_coaching_preferences(
        db,
        athlete_id,
        ["Prefer time-based easy runs", "  Keep explanations concise  "],
    )
    assert saved == ["Prefer time-based easy runs", "Keep explanations concise"]
    assert goal.intent_json["target_performance"] == "finish goal"
    assert goal.intent_json["coaching_preferences"] == saved

    result = build_athlete_intelligence(db, athlete_id, now=now)
    assert result["preferences"] == saved

    cleared = save_coaching_preferences(db, athlete_id, [])
    assert cleared == []
    assert "coaching_preferences" not in goal.intent_json
    assert goal.intent_json["target_performance"] == "finish goal"


def test_scenarios_are_explicit_projections_not_observed_facts():
    scenario = build_scenario_context(
        "What if I add 8 miles this week and increase volume by 10%?"
    )
    assert scenario is not None
    assert scenario["state"] == "projection"
    assert scenario["label"] == "Hypothetical scenario"
    assert scenario["requested_change"]["mentioned_miles"] == 8.0
    assert scenario["requested_change"]["mentioned_percent"] == 10.0
    assert "not" in scenario["caveat"].lower()
    assert "observed" in scenario["caveat"].lower()
    assert build_scenario_context("What did I run yesterday?") is None


COMPETITIVE_QUESTIONS = [
    "What changed in my training recently?",
    "How has my running volume changed?",
    "Is my long run progressing compared with my prior week?",
    "Has my consistency changed?",
    "How does this running week compare with my own prior baseline?",
    "What can you say if my sleep data is stale?",
    "What can you say when intensity is unknown?",
    "How do my current inputs line up with my target date?",
    "Show me the evidence behind that conclusion.",
    "What does my latest activity say about my progress?",
    "What does this selected Progress window show?",
    "Why?",
    "What if I add 8 miles this week?",
    "What if I move tomorrow's workout to Friday?",
    "Suppose I reduce this week's volume by 15%. What changes?",
    "What if that scenario happened? Separate projection from observed fact.",
    "Use my saved preference for time-based easy runs.",
    "What preferences have I deliberately saved?",
    "Is there an N-of-1 association between sleep and running time?",
    "What if there are only three paired sleep and run observations?",
    "What evidence matters most for my marathon goal?",
    "If I ran 5 extra miles, what would be hypothetical rather than measured?",
]


def test_competitive_question_suite_routes_through_bounded_intelligence(monkeypatch):
    athlete_id = uuid.uuid4()
    user = SimpleNamespace(id=athlete_id)
    intelligence = {
        "scope": "athlete_only",
        "briefing": {
            "state": "available",
            "headline": "Seven-day running volume changed.",
            "href": "/progress?window=30d",
        },
        "associations": [
            {
                "state": "insufficient",
                "title": "Sleep duration and same-day running time",
                "sample_size": 3,
                "caveat": "More paired observations are required.",
            }
        ],
        "preferences": ["Prefer time-based easy runs"],
        "views": [{"type": "weekly_running_volume", "points": []}],
    }

    monkeypatch.setattr(
        chat_routes,
        "summary",
        lambda user, db: {
            "state": "fresh",
            "generated_at": "2026-09-22T12:00:00+00:00",
            "data_through": "2026-09-22T10:00:00+00:00",
            "mileage": {"30d": 100000},
        },
    )
    monkeypatch.setattr(
        chat_routes,
        "build_today_plan",
        lambda db, user_id: {"state": "goal_required", "goal": None, "plan": None},
    )
    monkeypatch.setattr(
        chat_routes,
        "build_athlete_intelligence",
        lambda db, user_id: intelligence,
    )

    def answer(question, metrics):
        assert metrics["athlete_intelligence"]["scope"] == "athlete_only"
        assert metrics["coaching_preferences"] == intelligence["preferences"]
        expected_scenario = build_scenario_context(question)
        if expected_scenario is None:
            assert metrics["scenario"] is None
        else:
            assert metrics["scenario"]["state"] == "projection"
            assert "observed" in metrics["scenario"]["caveat"]
        return "Grounded answer with explicit evidence and uncertainty."

    monkeypatch.setattr(chat_routes, "run_coach_prompt", answer)

    for question in COMPETITIVE_QUESTIONS:
        db = FakeSession()
        response = chat_routes.chat(
            chat_routes.ChatRequest(message=question),
            user=user,
            db=db,
        )
        assert response["turn"]["status"] == "success"
        assert response["response"].startswith("Grounded answer")
        assert response["turn"]["evidence"]
        assert db.commits == 1

    assert len(COMPETITIVE_QUESTIONS) >= 20
