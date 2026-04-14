"""Garmin export zip import and dossier publication helpers."""

from __future__ import annotations

import html
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.models import PublishedDossier
from app.services import dedupe
from app.services.garmin import activity as garmin_activity


def _normalize_email(value: str | None) -> str | None:
    if not value or not isinstance(value, str):
        return None
    return value.strip().lower()


def _slugify(value: str) -> str:
    lowered = value.strip().lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return normalized or "athlete"


def _read_json(archive: zipfile.ZipFile, name: str) -> Any | None:
    try:
        return json.loads(archive.read(name))
    except KeyError:
        return None


def _extract_export_identity(archive: zipfile.ZipFile) -> tuple[str | None, set[str]]:
    emails: set[str] = set()
    athlete_name: str | None = None

    customer = _read_json(archive, "customer_data/customer.json") or {}
    if isinstance(customer, dict):
        athlete_name = customer.get("fullName") or customer.get("displayName")
        for key in ("primaryEmailAddress", "username"):
            normalized = _normalize_email(customer.get(key))
            if normalized:
                emails.add(normalized)
        for identifier in customer.get("loginIdentifiers") or []:
            if not isinstance(identifier, dict):
                continue
            for key in ("id", "value", "loginId"):
                normalized = _normalize_email(identifier.get(key))
                if normalized:
                    emails.add(normalized)

    contacts = _read_json(archive, "DI_CONNECT/DI-Connect-User/user_contact.json") or []
    if isinstance(contacts, list):
        for contact in contacts:
            if not isinstance(contact, dict):
                continue
            if not athlete_name:
                first = contact.get("firstName") or ""
                last = contact.get("lastName") or ""
                full_name = f"{first} {last}".strip()
                if full_name:
                    athlete_name = full_name
            for email in contact.get("emails") or []:
                normalized = _normalize_email(email)
                if normalized:
                    emails.add(normalized)

    return athlete_name, emails


def _iter_summarized_activities(archive: zipfile.ZipFile) -> list[dict[str, Any]]:
    activities: list[dict[str, Any]] = []
    for name in archive.namelist():
        if not name.endswith("_summarizedActivities.json"):
            continue
        data = json.loads(archive.read(name))
        if not isinstance(data, list):
            continue
        for wrapper in data:
            if not isinstance(wrapper, dict):
                continue
            exported = wrapper.get("summarizedActivitiesExport") or []
            for item in exported:
                if isinstance(item, dict):
                    activities.append(item)
    return activities


def _ms_to_iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return None


def _normalize_activity(item: dict[str, Any]) -> dict[str, Any]:
    distance_cm = float(item.get("distance") or 0.0)
    duration_ms = float(item.get("duration") or 0.0)
    return {
        "activityId": item.get("activityId"),
        "activityName": item.get("name") or item.get("activityName") or item.get("sportType"),
        "activityType": item.get("sportType") or item.get("activityType"),
        "startTimeGmt": _ms_to_iso(item.get("startTimeGmt") or item.get("beginTimestamp")),
        "distance": distance_cm / 100.0 if distance_cm else 0.0,
        "duration": duration_ms / 1000.0 if duration_ms else 0.0,
        "elapsedDuration": float(item.get("elapsedDuration") or 0.0) / 1000.0
        if item.get("elapsedDuration") is not None
        else None,
        "averageHeartRate": item.get("avgHr"),
        "maxHeartRate": item.get("maxHr"),
        "metadata": {
            "provider_user_id": item.get("userProfileId"),
            "location_name": item.get("locationName"),
            "device_id": item.get("deviceId"),
        },
    }


def _miles(distance_m: float) -> float:
    return distance_m / 1609.34 if distance_m else 0.0


def _build_dossier_html(athlete_name: str, user_email: str, activities: list[dict[str, Any]]) -> tuple[str, str]:
    dated = [item for item in activities if item.get("startTimeGmt")]
    dated.sort(key=lambda item: item["startTimeGmt"])
    total_distance_m = sum(float(item.get("distance") or 0.0) for item in activities)
    longest_run_m = max((float(item.get("distance") or 0.0) for item in activities), default=0.0)
    cutoff_30 = datetime.now(timezone.utc).timestamp() - (30 * 24 * 60 * 60)
    cutoff_90 = datetime.now(timezone.utc).timestamp() - (90 * 24 * 60 * 60)

    mileage_30 = 0.0
    mileage_90 = 0.0
    for item in dated:
        started = datetime.fromisoformat(item["startTimeGmt"])
        ts = started.timestamp()
        distance_m = float(item.get("distance") or 0.0)
        if ts >= cutoff_30:
            mileage_30 += distance_m
        if ts >= cutoff_90:
            mileage_90 += distance_m

    start_label = dated[0]["startTimeGmt"][:10] if dated else "unknown"
    end_label = dated[-1]["startTimeGmt"][:10] if dated else "unknown"
    summary = (
        f"Imported Garmin export for {athlete_name}, covering {start_label} through {end_label} "
        f"across {len(activities)} activities."
    )

    recent_rows = []
    for item in reversed(dated[-8:]):
        recent_rows.append(
            "<tr>"
            f"<td>{html.escape(item['startTimeGmt'][:10])}</td>"
            f"<td>{html.escape(str(item.get('activityName') or 'Workout'))}</td>"
            f"<td>{_miles(float(item.get('distance') or 0.0)):.1f}</td>"
            "</tr>"
        )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{html.escape(athlete_name)} Garmin Archive Dossier</title>
    <style>
      body {{ font-family: system-ui, sans-serif; margin: 0; background: #eef4f8; color: #13202c; }}
      main {{ max-width: 980px; margin: 0 auto; padding: 2rem 1.5rem 3rem; }}
      .card {{ background: #fff; border: 1px solid #dbe6ed; border-radius: 24px; padding: 1.5rem; box-shadow: 0 16px 36px rgba(19, 32, 44, 0.08); }}
      .eyebrow {{ text-transform: uppercase; letter-spacing: 0.14em; font-size: 0.78rem; color: #0d5a55; font-weight: 800; }}
      .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 0.9rem; margin-top: 1rem; }}
      .metric {{ background: #f7fbff; border-radius: 18px; padding: 1rem; }}
      table {{ width: 100%; border-collapse: collapse; margin-top: 1rem; }}
      th, td {{ text-align: left; padding: 0.7rem 0.5rem; border-bottom: 1px solid #e3edf4; }}
    </style>
  </head>
  <body>
    <main>
      <div class="card">
        <div class="eyebrow">Coach Dossier</div>
        <h1 style="margin:0.5rem 0 0;">{html.escape(athlete_name)} Garmin Archive Dossier</h1>
        <p style="color:#526472; line-height:1.7;">
          Generated from an imported Garmin export for {html.escape(user_email)}. This dossier stays isolated to the athlete account that matched the archive email.
        </p>
        <div class="grid">
          <div class="metric"><strong>Activities</strong><br />{len(activities)}</div>
          <div class="metric"><strong>Coverage</strong><br />{html.escape(start_label)} to {html.escape(end_label)}</div>
          <div class="metric"><strong>Total distance</strong><br />{_miles(total_distance_m):.1f} mi</div>
          <div class="metric"><strong>Longest run</strong><br />{_miles(longest_run_m):.1f} mi</div>
          <div class="metric"><strong>Last 30 days</strong><br />{_miles(mileage_30):.1f} mi</div>
          <div class="metric"><strong>Last 90 days</strong><br />{_miles(mileage_90):.1f} mi</div>
        </div>
      </div>
      <div class="card" style="margin-top:1rem;">
        <h2 style="margin-top:0;">Recent imported activity snapshot</h2>
        <table>
          <thead>
            <tr><th>Date</th><th>Activity</th><th>Miles</th></tr>
          </thead>
          <tbody>
            {''.join(recent_rows) or '<tr><td colspan="3">No activities found in archive.</td></tr>'}
          </tbody>
        </table>
      </div>
    </main>
  </body>
</html>"""
    return summary, html_doc


def _upsert_published_dossier(db, *, user, athlete_name: str, activities: list[dict[str, Any]]) -> PublishedDossier:
    slug = f"{_slugify(athlete_name)}-garmin-archive-dossier"
    summary, html_doc = _build_dossier_html(athlete_name, user.email, activities)
    dossier = db.query(PublishedDossier).filter(PublishedDossier.slug == slug).first()
    if dossier is None:
        dossier = PublishedDossier(
            user_id=user.id,
            slug=slug,
            title=f"{athlete_name} Garmin Archive Dossier",
            summary=summary,
            athlete_name=athlete_name,
            source="garmin_export",
            public=True,
            html_content=html_doc,
        )
        db.add(dossier)
    else:
        dossier.user_id = user.id  # type: ignore[assignment]
        dossier.title = f"{athlete_name} Garmin Archive Dossier"  # type: ignore[assignment]
        dossier.summary = summary  # type: ignore[assignment]
        dossier.athlete_name = athlete_name  # type: ignore[assignment]
        dossier.source = "garmin_export"  # type: ignore[assignment]
        dossier.public = True  # type: ignore[assignment]
        dossier.html_content = html_doc  # type: ignore[assignment]
    db.commit()
    db.refresh(dossier)
    return dossier


def import_garmin_export_archive(*, db, user, filename: str, archive_bytes: bytes) -> dict[str, Any]:
    """Import a Garmin export zip for the current user and publish a dossier."""
    if not archive_bytes:
        raise HTTPException(status_code=400, detail="Garmin export zip is empty")

    try:
        archive = zipfile.ZipFile(io.BytesIO(archive_bytes))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Invalid Garmin export zip") from exc

    athlete_name, archive_emails = _extract_export_identity(archive)
    current_email = _normalize_email(getattr(user, "email", None))
    if archive_emails and current_email not in archive_emails:
        raise HTTPException(
            status_code=409,
            detail="Garmin export belongs to another athlete account",
        )

    raw_activities = _iter_summarized_activities(archive)
    if not raw_activities:
        raise HTTPException(
            status_code=400,
            detail="Garmin export does not contain summarized activities",
        )

    normalized_activities = [_normalize_activity(item) for item in raw_activities]
    athlete_name = athlete_name or getattr(user, "name", None) or current_email or "Athlete"
    run = dedupe.record_ingest_run(db, provider="garmin_export", user_id=user.id)

    try:
        garmin_activity.persist_activity_summaries(
            db,
            user,
            run,
            normalized_activities,
            provider="garmin_export",
        )
        dossier = _upsert_published_dossier(
            db, user=user, athlete_name=athlete_name, activities=normalized_activities
        )
        dedupe.finish_ingest_run(
            db,
            run,
            "completed",
            summary={
                "filename": filename,
                "activities": len(normalized_activities),
                "dossier_slug": dossier.slug,
            },
        )
    except HTTPException:
        dedupe.finish_ingest_run(db, run, "failed", summary={"filename": filename})
        raise
    except Exception as exc:  # pylint: disable=broad-except
        dedupe.finish_ingest_run(
            db,
            run,
            "failed",
            summary={"filename": filename, "error": type(exc).__name__},
        )
        raise HTTPException(status_code=500, detail="Garmin export import failed") from exc

    return {
        "status": "imported",
        "activity_count": len(normalized_activities),
        "dossier_slug": dossier.slug,
        "dossier_url": f"/coach-dossiers/{dossier.slug}",
        "athlete_name": athlete_name,
    }
