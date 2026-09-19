"""Idempotently backfill one verified Garmin export into product Postgres and Influx.

Stage the export files in a local directory first. Dry-run is the default; --apply
requires an exact app user UUID, Garmin profile ID, and expected record counts.
No Garmin credentials or Drive tokens are needed by this script.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4


SUMMARY_GLOB = "*_summarizedActivities.json"
SLEEP_GLOB = "*_sleepData.json"
RECENT_FIT_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}.*\.fit$", re.I)
SUMMARY_MEASUREMENT = "FitnessPalsActivitySummary"
SLEEP_MEASUREMENT = "FitnessPalsSleepSummary"
SAMPLE_MEASUREMENT = "FitnessPalsActivitySample"


@dataclass(frozen=True)
class ActivityRecord:
    provider_activity_id: str
    start_time: datetime
    duration_seconds: float | None
    distance_m: float | None
    sport: str
    name: str
    source_file: str
    source_hash: str
    fingerprint: str
    source_kind: str


@dataclass(frozen=True)
class SleepRecord:
    calendar_date: date
    summary: dict[str, Any]
    source_file: str


@dataclass(frozen=True)
class Snapshot:
    activities: list[ActivityRecord]
    sleep: list[SleepRecord]
    fit_files: list[Path]
    nap_only_rows: int
    oldest_activity: datetime
    newest_activity: datetime


def _fingerprint(start: datetime, duration: float | None, distance: float | None, sport: str) -> str:
    """Match the canonical dedupe fingerprint contract."""
    payload = {
        "start": start.isoformat(),
        "duration_s": None if duration is None else round(duration, -1),
        "distance_m": None if distance is None else round(distance),
        "sport": sport.lower(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def _nonnegative_number(value: Any, label: str) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Invalid {label}")
    return number


def _millis_datetime(value: Any) -> datetime:
    milliseconds = _nonnegative_number(value, "activity start time")
    if milliseconds is None:
        raise ValueError("Missing activity start time")
    result = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    if result.year < 2000 or result > datetime.now(timezone.utc) + timedelta(days=1):
        raise ValueError("Activity start time is outside the expected range")
    return result


def _summary_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("Garmin activity export must be a list")
    result = []
    for wrapper in payload:
        if not isinstance(wrapper, dict) or not isinstance(wrapper.get("summarizedActivitiesExport"), list):
            raise ValueError("Garmin activity export wrapper is malformed")
        result.extend(wrapper["summarizedActivitiesExport"])
    if not all(isinstance(item, dict) for item in result):
        raise ValueError("Garmin activity export includes a malformed activity")
    return result


def load_activity_summaries(source_dir: Path, expected_profile_id: int) -> list[ActivityRecord]:
    files = sorted(source_dir.glob(SUMMARY_GLOB))
    if not files:
        raise ValueError("No summarized-activity exports were staged")
    activities: list[ActivityRecord] = []
    ids: set[str] = set()
    for path in files:
        content = path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        for item in _summary_items(json.loads(content.decode("utf-8-sig"))):
            if item.get("userProfileId") != expected_profile_id:
                raise ValueError(f"Garmin profile mismatch in {path.name}")
            activity_id = item.get("activityId")
            if activity_id is None:
                raise ValueError(f"Missing Garmin activity ID in {path.name}")
            provider_id = str(activity_id)
            if provider_id in ids:
                raise ValueError(f"Duplicate Garmin activity ID {provider_id}")
            ids.add(provider_id)
            start = _millis_datetime(item.get("startTimeGmt") or item.get("beginTimestamp"))
            duration_ms = _nonnegative_number(item.get("duration"), "activity duration")
            distance_cm = _nonnegative_number(item.get("distance"), "activity distance")
            duration = duration_ms / 1000 if duration_ms is not None else None
            distance = distance_cm / 100 if distance_cm is not None else None
            sport = str(item.get("sportType") or item.get("activityType") or "activity").lower()
            name = str(item.get("name") or sport.replace("_", " ").title())
            activities.append(ActivityRecord(
                provider_activity_id=provider_id,
                start_time=start,
                duration_seconds=duration,
                distance_m=distance,
                sport=sport,
                name=name,
                source_file=path.name,
                source_hash=file_hash,
                fingerprint=_fingerprint(start, duration, distance, sport),
                source_kind="summary",
            ))
    return activities


def load_sleep_history(source_dir: Path, expected_profile_id: int) -> tuple[list[SleepRecord], int]:
    files = sorted(source_dir.glob(SLEEP_GLOB))
    if not files:
        raise ValueError("No sleep-history exports were staged")
    records: list[SleepRecord] = []
    dates: set[date] = set()
    nap_only = 0
    for path in files:
        if f"_{expected_profile_id}_" not in path.name:
            raise ValueError(f"Garmin profile mismatch in {path.name}")
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError(f"Malformed sleep export {path.name}")
        for row in payload:
            if not isinstance(row, dict):
                raise ValueError(f"Malformed sleep record in {path.name}")
            date_value = row.get("calendarDate")
            if not date_value:
                if set(row) <= {"napList", "retro"}:
                    nap_only += 1
                    continue
                raise ValueError(f"Undated sleep record in {path.name}")
            calendar_date = date.fromisoformat(str(date_value))
            if calendar_date in dates:
                raise ValueError(f"Duplicate sleep date {calendar_date}")
            dates.add(calendar_date)
            records.append(SleepRecord(calendar_date, _normalize_sleep(row), path.name))
    return records, nap_only


def _normalize_sleep(row: dict[str, Any]) -> dict[str, Any]:
    """Preserve the export while adding fields expected by the athlete home view."""
    summary = dict(row)
    stages = ("deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds")
    if all(_finite_field(row.get(key)) is not None for key in stages):
        summary["sleepTimeSeconds"] = sum(float(row[key]) for key in stages)
    scores = row.get("sleepScores")
    if isinstance(scores, dict) and _finite_field(scores.get("overallScore")) is not None:
        summary["sleepScore"] = scores["overallScore"]
    return summary


def load_recent_fits(source_dir: Path, after: datetime) -> tuple[list[ActivityRecord], list[Path]]:
    """Only import sessions newer than the summarized export to avoid duplicates."""
    paths = [p for p in sorted(source_dir.glob("*.fit")) if RECENT_FIT_NAME.match(p.name)]
    if not paths:
        return [], []
    from fitparse import FitFile  # installed in the backend runtime

    records: list[ActivityRecord] = []
    included: list[Path] = []
    fingerprints: set[str] = set()
    for path in paths:
        content = path.read_bytes()
        file_hash = hashlib.sha256(content).hexdigest()
        file_included = False
        for index, session in enumerate(FitFile(str(path)).get_messages("session")):
            start = session.get_value("start_time") or session.get_value("timestamp")
            if not isinstance(start, datetime):
                continue
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            start = start.astimezone(timezone.utc)
            if start <= after:
                continue
            if start > datetime.now(timezone.utc) + timedelta(days=1):
                raise ValueError(f"Future FIT session in {path.name}")
            duration = _nonnegative_number(
                session.get_value("total_timer_time") or session.get_value("total_elapsed_time"),
                "FIT duration",
            )
            distance = _nonnegative_number(session.get_value("total_distance"), "FIT distance")
            sport = str(session.get_value("sport") or "activity").lower()
            fingerprint = _fingerprint(start, duration, distance, sport)
            if fingerprint in fingerprints:
                continue
            fingerprints.add(fingerprint)
            records.append(ActivityRecord(
                provider_activity_id=f"fit:{path.name}:{index}",
                start_time=start,
                duration_seconds=duration,
                distance_m=distance,
                sport=sport,
                name=sport.replace("_", " ").title(),
                source_file=path.name,
                source_hash=file_hash,
                fingerprint=fingerprint,
                source_kind="fit",
            ))
            file_included = True
        if file_included:
            included.append(path)
    return records, included


def load_snapshot(source_dir: Path, expected_profile_id: int) -> Snapshot:
    activities = load_activity_summaries(source_dir, expected_profile_id)
    sleep, nap_only = load_sleep_history(source_dir, expected_profile_id)
    newest_summary = max(record.start_time for record in activities)
    fits, fit_files = load_recent_fits(source_dir, newest_summary)
    all_activities = activities + fits
    return Snapshot(
        activities=all_activities,
        sleep=sleep,
        fit_files=fit_files,
        nap_only_rows=nap_only,
        oldest_activity=min(record.start_time for record in all_activities),
        newest_activity=max(record.start_time for record in all_activities),
    )


def _apply_postgres(snapshot: Snapshot, email: str, user_id: UUID, profile_id: int) -> dict[str, int]:
    from sqlalchemy import func
    from app.db import SESSION_FACTORY
    from app.models import Activity, ActivitySource, IngestRun, SleepSession, User

    db = SESSION_FACTORY()
    try:
        user = db.query(User).filter(func.lower(User.email) == email.lower()).one_or_none()
        if user is None or user.id != user_id:
            raise ValueError("Production account does not match expected email and UUID")
        # Only dedupe against rows that predated this run. Distinct Garmin IDs in
        # the export can legitimately have the same coarse fingerprint.
        existing_activities = {
            item.fingerprint_hash: item
            for item in db.query(Activity).filter(Activity.user_id == user_id).all()
        }
        existing_sources = {
            (source.provider, source.provider_activity_id)
            for source in db.query(ActivitySource)
            .join(Activity, Activity.id == ActivitySource.activity_id)
            .filter(Activity.user_id == user_id)
            .all()
        }
        existing_sleep = {
            (item.provider, item.daily_sleep_id)
            for item in db.query(SleepSession).filter(SleepSession.user_id == user_id).all()
        }
        run = IngestRun(provider="garmin_archive", status="running", user_id=user_id)
        db.add(run)
        db.commit()
        counts = {"activities_created": 0, "activities_reused": 0, "sources_created": 0,
                  "sleep_created": 0, "already_present": 0}
        for index, record in enumerate(snapshot.activities, 1):
            source_key = ("garmin_archive", record.provider_activity_id)
            if source_key in existing_sources:
                counts["already_present"] += 1
                continue
            activity = existing_activities.get(record.fingerprint)
            if activity is None:
                activity = Activity(
                    id=uuid4(), user_id=user_id, ingest_run_id=run.id,
                    start_time=record.start_time,
                    duration_seconds=int(record.duration_seconds) if record.duration_seconds is not None else None,
                    distance_m=record.distance_m,
                    sport=record.sport,
                    status="completed",
                    fingerprint_hash=record.fingerprint,
                    metadata_json={
                        "name": record.name,
                        "activity_type": record.sport,
                        "provider_activity_id": record.provider_activity_id,
                        "provider_user_id": str(profile_id),
                        "source_object_name": record.source_file,
                        "source_content_hash": record.source_hash,
                    },
                )
                db.add(activity)
                counts["activities_created"] += 1
            else:
                counts["activities_reused"] += 1
            db.add(ActivitySource(
                activity_id=activity.id,
                provider="garmin_archive",
                provider_activity_id=record.provider_activity_id,
                raw_hash=record.source_hash,
                decision="new" if activity.ingest_run_id == run.id else "merged",
                chosen_fields={"name": record.name, "sport": record.sport,
                               "source_file": record.source_file},
                raw_payload=None,
            ))
            existing_sources.add(source_key)
            counts["sources_created"] += 1
            if index % 100 == 0:
                db.commit()
        db.commit()
        for index, record in enumerate(snapshot.sleep, 1):
            daily_id = int(record.calendar_date.strftime("%Y%m%d"))
            sleep_key = ("garmin_archive", daily_id)
            if sleep_key in existing_sleep:
                continue
            db.add(SleepSession(
                user_id=user_id,
                provider="garmin_archive",
                daily_sleep_id=daily_id,
                calendar_date=record.calendar_date,
                ingest_run_id=run.id,
                summary_json=record.summary,
            ))
            existing_sleep.add(sleep_key)
            counts["sleep_created"] += 1
            if index % 100 == 0:
                db.commit()
        run.status = "completed"
        run.finished_at = datetime.now(timezone.utc)
        run.summary = {**counts, "profile_id": profile_id, "source": "Fenix8_Backup"}
        db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _finite_field(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _sleep_fields(summary: dict[str, Any]) -> dict[str, float]:
    fields: dict[str, float] = {"record_present": 1.0}
    for key in (
        "deepSleepSeconds", "lightSleepSeconds", "remSleepSeconds", "awakeSleepSeconds",
        "avgSleepStress", "averageRespiration", "restlessMomentCount",
    ):
        value = _finite_field(summary.get(key))
        if value is not None:
            fields[key] = value
    scores = summary.get("sleepScores")
    if isinstance(scores, dict):
        score = scores.get("overallScore") or scores.get("overall")
        if isinstance(score, dict):
            score = score.get("value")
        value = _finite_field(score)
        if value is not None:
            fields["sleepScore"] = value
    start_text = summary.get("sleepStartTimestampGMT")
    end_text = summary.get("sleepEndTimestampGMT")
    if isinstance(start_text, str) and isinstance(end_text, str):
        try:
            start = datetime.fromisoformat(start_text.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_text.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            window_seconds = (end - start).total_seconds()
            if 0 <= window_seconds <= 24 * 3600:
                fields["sleep_window_seconds"] = window_seconds
    return fields


def _fit_sample_points(path: Path, user_id: UUID) -> list[dict[str, Any]]:
    from fitparse import FitFile

    points = []
    for message in FitFile(str(path)).get_messages("record"):
        timestamp = message.get_value("timestamp")
        if not isinstance(timestamp, datetime):
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        fields = {}
        for key in ("heart_rate", "cadence", "distance", "speed", "altitude", "temperature", "power"):
            value = _finite_field(message.get_value(key))
            if value is not None:
                fields[key] = value
        for key in ("position_lat", "position_long"):
            value = _finite_field(message.get_value(key))
            if value is not None:
                fields[key] = value * 180 / (2**31)
        if fields:
            points.append({
                "measurement": SAMPLE_MEASUREMENT,
                "time": timestamp,
                "tags": {"user_id": str(user_id), "provider": "garmin_archive", "source_file": path.name},
                "fields": fields,
            })
    return points


def _apply_influx(snapshot: Snapshot, user_id: UUID, profile_id: int) -> dict[str, int]:
    from influxdb_client import InfluxDBClient
    from influxdb_client.client.write_api import SYNCHRONOUS

    url = os.environ.get("RUNTRAINER_INFLUX_URL") or "http://influxdb:8086"
    bucket = os.environ.get("INFLUXDB_DATABASE") or "GarminStats"
    org = os.environ.get("INFLUXDB_ORG") or "default"
    token = os.environ.get("INFLUXDB_TOKEN") or os.environ.get("INFLUXDB_PASSWORD")
    if not token:
        raise ValueError("Production Influx credentials are unavailable")
    client = InfluxDBClient(url=url, token=token, org=org, timeout=60000)
    counts = {"activity_points": 0, "sleep_points": 0, "fit_sample_points": 0}
    try:
        writer = client.write_api(write_options=SYNCHRONOUS)
        def flush(points: list[dict[str, Any]]) -> None:
            if points:
                writer.write(bucket=bucket, org=org, record=points)

        points: list[dict[str, Any]] = []
        for record in snapshot.activities:
            fields: dict[str, Any] = {
                "activity_id": record.provider_activity_id,
                "sport": record.sport,
                "name": record.name,
            }
            if record.duration_seconds is not None:
                fields["duration_seconds"] = record.duration_seconds
            if record.distance_m is not None:
                fields["distance_m"] = record.distance_m
            points.append({
                "measurement": SUMMARY_MEASUREMENT,
                "time": record.start_time,
                "tags": {"user_id": str(user_id), "provider": "garmin_archive",
                         "profile_id": str(profile_id), "activity_id": record.provider_activity_id},
                "fields": fields,
            })
            if len(points) >= 250:
                flush(points)
                counts["activity_points"] += len(points)
                points = []
        flush(points)
        counts["activity_points"] += len(points)

        points = []
        for record in snapshot.sleep:
            fields = _sleep_fields(record.summary)
            if not fields:
                continue
            points.append({
                "measurement": SLEEP_MEASUREMENT,
                "time": datetime.combine(record.calendar_date, datetime.min.time(), tzinfo=timezone.utc),
                "tags": {"user_id": str(user_id), "provider": "garmin_archive", "profile_id": str(profile_id)},
                "fields": fields,
            })
            if len(points) >= 250:
                flush(points)
                counts["sleep_points"] += len(points)
                points = []
        flush(points)
        counts["sleep_points"] += len(points)

        for path in snapshot.fit_files:
            samples = _fit_sample_points(path, user_id)
            for index in range(0, len(samples), 250):
                batch = samples[index:index + 250]
                flush(batch)
                counts["fit_sample_points"] += len(batch)
        writer.close()
        return counts
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_dir", type=Path)
    parser.add_argument("--email", required=True)
    parser.add_argument("--expected-user-id", type=UUID, required=True)
    parser.add_argument("--expected-profile-id", type=int, required=True)
    parser.add_argument("--expected-summary-count", type=int, required=True)
    parser.add_argument("--expected-sleep-count", type=int, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.source_dir.is_dir():
        raise SystemExit("Source directory does not exist")
    snapshot = load_snapshot(args.source_dir, args.expected_profile_id)
    summary_count = sum(item.source_kind == "summary" for item in snapshot.activities)
    if summary_count != args.expected_summary_count or len(snapshot.sleep) != args.expected_sleep_count:
        raise SystemExit("Export record counts differ from preflight; no writes performed")
    plan = {
        "mode": "apply" if args.apply else "dry_run",
        "user_id": str(args.expected_user_id),
        "profile_id": args.expected_profile_id,
        "summary_activities": summary_count,
        "recent_fit_activities": len(snapshot.activities) - summary_count,
        "sleep_days": len(snapshot.sleep),
        "nap_only_rows_skipped": snapshot.nap_only_rows,
        "earliest_activity": snapshot.oldest_activity.isoformat(),
        "latest_activity": snapshot.newest_activity.isoformat(),
    }
    print(json.dumps(plan, sort_keys=True), flush=True)
    if args.apply:
        postgres_result = _apply_postgres(
            snapshot, args.email, args.expected_user_id, args.expected_profile_id
        )
        print(json.dumps({"postgres": postgres_result}, sort_keys=True), flush=True)
        influx_result = _apply_influx(snapshot, args.expected_user_id, args.expected_profile_id)
        print(json.dumps({"influx": influx_result}, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
