"""Contract tests for the canonical Athlete State recovery model."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

from app.models import Activity, SleepSession
from app.routes.athlete_state import athlete_state
from app.services.activity_summary import build_canonical_summary
from app.services.athlete_home import build_athlete_home
from app.services.athlete_state import build_athlete_state


class FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *_conditions):
        return self

    def all(self):
        return list(self.items)


class FakeSession:
    def __init__(self, items):
        self.items = list(items)

    def query(self, model):
        return FakeQuery([item for item in self.items if isinstance(item, model)])


def sleep(user_id, day, payload, provider="garmin"):
    return SleepSession(
        id=uuid.uuid4(),
        user_id=user_id,
        provider=provider,
        daily_sleep_id=int(day.strftime("%Y%m%d")),
        calendar_date=day,
        summary_json=payload,
    )


def activity(user_id, now):
    return Activity(
        id=uuid.uuid4(),
        user_id=user_id,
        start_time=now - timedelta(days=1),
        duration_seconds=3600,
        distance_m=10000,
        sport="run",
        status="merged",
        fingerprint_hash=str(uuid.uuid4()),
        metadata_json={},
    )


def test_athlete_state_normalizes_hrv_sleep_score_duration_and_provenance():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    row = sleep(
        athlete_id,
        date(2026, 9, 24),
        {
            "sleepTimeSeconds": 27000,
            "sleepScores": {"overall": 82},
            "avgOvernightHrv": 41,
            "restingHeartRate": 48,
        },
    )

    state = build_athlete_state(FakeSession([row]), athlete_id, now=now)

    signals = state["latest"]["signals"]
    assert signals["sleep_duration"]["value"] == 7.5
    assert signals["sleep_duration"]["unit"] == "hours"
    assert signals["sleep_score"]["value"] == 82
    assert signals["overnight_hrv"]["value"] == 41
    assert signals["overnight_hrv"]["unit"] == "ms"
    assert signals["resting_heart_rate"]["value"] == 48
    assert signals["overnight_hrv"]["provenance"]["provider"] == "garmin"
    assert signals["overnight_hrv"]["provenance"]["record_id"] == str(row.id)


def test_athlete_state_accepts_provider_payload_variants_without_leaking_keys():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    row = sleep(
        athlete_id,
        date(2026, 9, 24),
        {
            "sleep_time_seconds": 25200,
            "overallSleepScore": 77,
            "hrvSummary": {"lastNightAvg": 39},
        },
        provider="garmin_archive",
    )

    state = build_athlete_state(FakeSession([row]), athlete_id, now=now)
    signals = state["latest"]["signals"]

    assert signals["sleep_duration"]["value"] == 7.0
    assert signals["sleep_score"]["value"] == 77
    assert signals["overnight_hrv"]["value"] == 39
    assert "avgOvernightHrv" not in str(state)
    assert signals["overnight_hrv"]["provenance"]["provider"] == "garmin_archive"


def test_missing_values_stay_unavailable_and_never_become_zero():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    state = build_athlete_state(
        FakeSession([sleep(athlete_id, date(2026, 9, 24), {})]),
        athlete_id,
        now=now,
    )

    for signal in state["latest"]["signals"].values():
        assert signal["value"] is None
        assert signal["status"] == "unavailable"
    assert state["derived"]["hrv_7d_average"]["value"] is None
    assert state["derived"]["hrv_7d_average"]["sample_count"] == 0


def test_stale_state_preserves_values_and_marks_them_stale():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    state = build_athlete_state(
        FakeSession([
            sleep(
                athlete_id,
                date(2026, 9, 18),
                {"sleepTimeSeconds": 28800, "avgOvernightHrv": 45},
            )
        ]),
        athlete_id,
        now=now,
        days=14,
    )

    assert state["state"] == "stale"
    assert state["latest"]["signals"]["sleep_duration"]["value"] == 8.0
    assert state["latest"]["signals"]["sleep_duration"]["status"] == "stale"
    assert state["latest"]["signals"]["overnight_hrv"]["status"] == "stale"


def test_history_is_bounded_dated_and_athlete_isolated():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    rows = [
        sleep(athlete_id, date(2026, 9, 24), {"avgOvernightHrv": 40}),
        sleep(athlete_id, date(2026, 9, 23), {"avgOvernightHrv": 42}),
        sleep(other_id, date(2026, 9, 24), {"avgOvernightHrv": 99}),
    ]

    state = build_athlete_state(FakeSession(rows), athlete_id, now=now, days=2)

    assert [item["date"] for item in state["history"]] == ["2026-09-24", "2026-09-23"]
    assert [item["signals"]["overnight_hrv"]["value"] for item in state["history"]] == [40, 42]
    assert state["derived"]["hrv_7d_average"]["value"] == 41
    assert state["decision"]["evidence"]["recovery"]["known_signals"] == [
        "overnight_hrv"
    ]


def test_metrics_summary_derives_legacy_hrv_average_from_athlete_state():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    db = FakeSession([
        activity(athlete_id, now),
        sleep(athlete_id, date(2026, 9, 24), {"avgOvernightHrv": 40}),
        sleep(athlete_id, date(2026, 9, 23), {"avgOvernightHrv": 42}),
    ])

    summary = build_canonical_summary(db, athlete_id, now=now)

    assert summary["hrv_avg"] == 41
    assert summary["hrv_avg_window_days"] == 7
    assert summary["hrv_avg_sample_count"] == 2
    assert summary["metric_states"]["hrv_avg"] == "fresh"
    assert isinstance(summary["goal_graph"], dict)
    assert summary["goal_graph"] == summary["athlete_state"]["goal_graph"]
    assert summary["decision"] == summary["athlete_state"]["decision"]
    assert summary["decision"]["action"]["code"] == "set_goal"
    assert summary["athlete_state"]["latest"]["signals"]["overnight_hrv"]["value"] == 40


def test_api_contract_returns_only_authenticated_athlete_state():
    now = datetime.now(timezone.utc)
    athlete_id = uuid.uuid4()
    other_id = uuid.uuid4()
    db = FakeSession([
        sleep(athlete_id, now.date(), {"avgOvernightHrv": 44}),
        sleep(other_id, now.date(), {"avgOvernightHrv": 90}),
    ])

    result = athlete_state(days=14, user=SimpleNamespace(id=athlete_id), db=db)

    assert result["latest"]["signals"]["overnight_hrv"]["value"] == 44


def test_dashboard_and_canonical_summary_agree_on_recovery_availability():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    row = sleep(
        athlete_id,
        date(2026, 9, 24),
        {"sleepTimeSeconds": 27000, "sleepScores": {"overall": 82}, "avgOvernightHrv": 41},
    )
    db = FakeSession([activity(athlete_id, now), row])

    state = build_athlete_state(db, athlete_id, now=now)
    home = build_athlete_home(db, athlete_id, goal="marathon", now=now)
    metrics = build_canonical_summary(db, athlete_id, now=now)

    assert home["recovery"]["overnight_hrv"] == 41
    assert metrics["athlete_state"]["latest"]["signals"]["overnight_hrv"]["value"] == 41
    assert metrics["metric_states"]["hrv_avg"] == "fresh"
    assert state["latest"]["signals"]["overnight_hrv"]["status"] == "known"
    assert home["decision"] == metrics["decision"] == state["decision"]


def test_dashboard_and_canonical_summary_agree_when_recovery_is_missing():
    now = datetime(2026, 9, 24, 12, tzinfo=timezone.utc)
    athlete_id = uuid.uuid4()
    db = FakeSession([activity(athlete_id, now)])

    home = build_athlete_home(db, athlete_id, goal="marathon", now=now)
    metrics = build_canonical_summary(db, athlete_id, now=now)

    assert home["recovery"]["state"] == "unknown"
    assert home["recovery"]["overnight_hrv"] is None
    assert metrics["athlete_state"]["state"] == "unknown"
    assert metrics["hrv_avg"] is None
    assert metrics["metric_states"]["hrv_avg"] == "unknown"
