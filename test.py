"""
Quick Garmin health scraper using the garth client.

Prompts for Garmin credentials (MFA supported via garth) and pulls a wide set
of health/wellness endpoints for a recent date range. Results are printed as
JSON and can optionally be saved to disk.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
import io
import zipfile
from pathlib import Path
import sys
import os
from typing import Any, Callable, Dict, Iterable, Tuple
import getpass

import garth
from garth.data.hrv import HRVData
from garth.data.sleep import SleepData
from garth.stats.hrv import DailyHRV
from garth.stats.intensity_minutes import DailyIntensityMinutes
from garth.stats.sleep import DailySleep
from garth.stats.steps import DailySteps
from garth.stats.stress import DailyStress

# Connect API categories that do not have convenience wrappers in garth yet.
# Paths support {date}, {start}, {end} placeholders which will be rendered
# using YYYY-MM-DD strings.
# Default set trimmed to endpoints that returned data for this account.
CONNECTAPI_SOURCES: Dict[str, Dict[str, Any]] = {
    "daily_stress": {"path": "/wellness-service/wellness/dailyStress/{date}", "per_day": True},
    "daily_vo2max": {"path": "/metrics-service/metrics/maxmet/latest/{date}", "per_day": True},
    "sleep_timeseries": {
        "path": "/sleep-service/sleep/dailySleepData",
        "per_day": True,
        "params": {"date": "{date}", "nonSleepBufferMinutes": 60},
    },
    "weight_range": {
        "path": "/weight-service/weight/dateRange",
        "per_day": True,
        "params": {"startDate": "{date}", "endDate": "{date}"},
    },
    "monthly_vo2max": {"path": "/metrics-service/metrics/maxmet/monthly/{start}/{end}", "per_day": False},
    "acclimation": {
        "path": "/wellness-service/stats/daily/acclimation",
        "per_day": False,
        "params": {"fromDate": "{start}", "untilDate": "{end}"},
    },
    "activities": {"path": "/activitylist-service/activities", "per_day": False, "params": {"start": 0, "limit": 20}},
}

# Additional endpoints that were failing (403/404/405) for this account.
EXTRA_CONNECTAPI_SOURCES: Dict[str, Dict[str, Any]] = {
    "daily_summary": {"path": "/wellness-service/wellness/dailySummary/{date}", "per_day": True},
    "daily_heart_rate": {"path": "/wellness-service/wellness/dailyHeartRate/{date}", "per_day": True},
    "daily_respiration": {"path": "/wellness-service/wellness/dailyRespiration/{date}", "per_day": True},
    "daily_body_battery": {"path": "/wellness-service/wellness/dailyBodyBattery/{date}", "per_day": True},
    "daily_spo2": {"path": "/wellness-service/wellness/dailySpO2/{date}", "per_day": True},
}

try:
    import fitdecode  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    fitdecode = None


def _json_ready(value: Any) -> Any:
    if is_dataclass(value):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _safe_fetch(label: str, func: Callable[[], Any], log_err: Callable[[str], None]) -> Any:
    try:
        return func()
    except Exception as exc:  # pylint: disable=broad-except
        log_err(f"[warn] {label} failed: {exc}")
        return {"error": str(exc)}


def _render_params(
    params: Dict[str, Any] | None, *, date_str: str, start_str: str, end_str: str
) -> Dict[str, Any] | None:
    if not params:
        return None
    rendered: Dict[str, Any] = {}
    for key, value in params.items():
        if isinstance(value, str):
            rendered[key] = value.format(date=date_str, start=start_str, end=end_str)
        else:
            rendered[key] = value
    return rendered


def _convert_semicircles(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value * (180 / (2**31))
    return value


def _parse_fit_records(fit_bytes: bytes, log_err: Callable[[str], None]) -> list[dict[str, Any]]:
    if not fitdecode:
        log_err("[warn] fitdecode not installed; skipping FIT record parsing")
        return []
    records: list[dict[str, Any]] = []
    last_ts: datetime | None = None
    try:
        with fitdecode.FitReader(io.BytesIO(fit_bytes)) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name == "record":
                    rec: dict[str, Any] = {}
                    ts_seen: datetime | None = None
                    for field in frame.fields:
                        if field.value is None:
                            continue
                        val = field.value
                        if isinstance(val, datetime):
                            ts_seen = val
                            rec[field.name] = val.isoformat()
                        elif field.name in {"position_lat", "position_long"}:
                            rec[field.name] = _convert_semicircles(val)
                        else:
                            rec[field.name] = val
                    for dev_field in getattr(frame, "developer_fields", []):
                        try:
                            name = getattr(dev_field, "name", None) or f"dev_{getattr(dev_field, 'field_def_num', '')}"
                        except Exception:
                            name = None
                        if not name:
                            continue
                        try:
                            val = dev_field.value
                        except Exception:
                            continue
                        if isinstance(val, datetime):
                            ts_seen = ts_seen or val
                            rec[name] = val.isoformat()
                        else:
                            rec[name] = val
                    if ts_seen:
                        last_ts = ts_seen
                    if rec:
                        records.append(rec)
                elif frame.name == "hrv":
                    rr_list = frame.get_value("time") or []
                    if not isinstance(rr_list, list):
                        continue
                    ts_val = frame.get_value("timestamp")
                    base_ts = ts_val if isinstance(ts_val, datetime) else last_ts
                    for rr in rr_list:
                        try:
                            rr_ms = float(rr) * 1000.0
                        except Exception:
                            continue
                        rec = {"rr_ms": rr_ms}
                        if base_ts:
                            rec["timestamp"] = base_ts.isoformat()
                        records.append(rec)
    except Exception as exc:  # pylint: disable=broad-except
        log_err(f"[warn] FIT parse failed: {exc}")
    return records


def _download_activity_fit(client: garth.Client, activity_id: Any, log_err: Callable[[str], None]) -> bytes | None:
    """Fetch FIT bytes for an activity (export endpoint or zipped files endpoint)."""
    paths = [
        f"download-service/export/fit/activity/{activity_id}",
        f"download-service/files/activity/{activity_id}",
    ]
    failures: list[str] = []
    for path in paths:
        try:
            content = client.download(path)
        except Exception as exc:  # pylint: disable=broad-except
            failures.append(f"{path}: {exc}")
            continue
        if not content:
            continue
        if path.startswith("download-service/files"):
            try:
                with zipfile.ZipFile(io.BytesIO(content)) as zf:
                    fit_name = next((n for n in zf.namelist() if n.lower().endswith(".fit")), None)
                    if fit_name:
                        with zf.open(fit_name) as fh:
                            return fh.read()
            except Exception as exc:  # pylint: disable=broad-except
                failures.append(f"unzip:{exc}")
                continue
        else:
            return content
    if failures:
        log_err(f"[warn] activity_fit@{activity_id} failed: {'; '.join(failures)}")
    return None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Garmin health data via garth")
    parser.add_argument("--days", type=int, default=7, help="How many days of history to pull (includes the end date)")
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD (defaults to today, UTC)",
    )
    parser.add_argument(
        "--token-dir",
        type=str,
        default="garminconnect-tokens",
        help="Directory to load/save tokens (per email)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="health.txt",
        help="Path to write the JSON output (default: health.txt)",
    )
    parser.add_argument(
        "--domain",
        type=str,
        default=os.environ.get("GARTH_DOMAIN", "garmin.com"),
        help="Garmin domain to use (garmin.com or garmin.cn)",
    )
    parser.add_argument(
        "--error-output",
        type=str,
        default="health.err",
        help="Path to write errors/warnings (default: health.err)",
    )
    parser.add_argument(
        "--include-extra-connectapi",
        action="store_true",
        help="Also try extra connectapi endpoints that often return 403/404/405",
    )
    parser.add_argument(
        "--email",
        type=str,
        default=os.environ.get("GARTH_EMAIL"),
        help="Garmin email (default: GARTH_EMAIL env or prompt)",
    )
    return parser.parse_args()

def _make_error_logger(error_path: Path | None):
    def log_err(msg: str) -> None:
        print(msg, file=sys.stderr)
        if error_path:
            error_path.parent.mkdir(parents=True, exist_ok=True)
            with error_path.open("a", encoding="utf-8") as fh:
                fh.write(msg + "\n")
    return log_err

def _build_client(
    token_root: Path | None, domain: str, log_err: Callable[[str], None], email: str | None = None
) -> Tuple[garth.Client, str]:
    if not email:
        email = input("Garmin email: ").strip()
    client = garth.Client()
    client.configure(domain=domain)
    print(f"Using Garmin domain: {client.domain}")
    token_dir = (token_root / email) if token_root else None

    def tokens_ok() -> bool:
        if not client.oauth1_token or not client.oauth2_token:
            return False
        if client.oauth2_token.refresh_expired:
            return False
        if client.oauth2_token.expired:
            try:
                client.refresh_oauth2()
                if token_dir:
                    token_dir.mkdir(parents=True, exist_ok=True)
                    client.dump(str(token_dir))
                    print(f"[info] Refreshed tokens cached to {token_dir}")
            except Exception as exc:  # pylint: disable=broad-except
                log_err(f"[warn] Token refresh failed, will re-prompt credentials: {exc}")
                return False
        return True

    if token_dir and (token_dir / "oauth1_token.json").exists():
        print(f"Loading cached tokens from {token_dir}")
        try:
            client.load(str(token_dir))
            if tokens_ok():
                return client, email
        except Exception as exc:  # pylint: disable=broad-except
            log_err(f"[warn] Failed to load cached tokens, falling back to password login: {exc}")

    password = getpass.getpass("Garmin password: ")
    try:
        client.login(email, password)
    except garth.exc.GarthHTTPError as exc:
        log_err(f"[error] Garmin login failed (check email/password/MFA/domain): {exc}")
        raise SystemExit(1) from exc
    if token_dir:
        token_dir.mkdir(parents=True, exist_ok=True)
        client.dump(str(token_dir))
        print(f"Tokens cached in {token_dir}")
    return client, email


def _date_list(end_date: date, days: int) -> Iterable[date]:
    for i in range(days):
        yield end_date - timedelta(days=i)


def _collect_stat_blocks(client: garth.Client, end_date: date, days: int, log_err: Callable[[str], None]) -> Dict[str, Any]:
    fetchers: Dict[str, Callable[[], Any]] = {
        "sleep_data": lambda: SleepData.list(end=end_date, days=days, client=client),
        "hrv_data": lambda: HRVData.list(end=end_date, days=days, client=client),
        "sleep_score": lambda: DailySleep.list(end=end_date, period=days, client=client),
        "steps": lambda: DailySteps.list(end=end_date, period=days, client=client),
        "stress": lambda: DailyStress.list(end=end_date, period=days, client=client),
        "intensity_minutes": lambda: DailyIntensityMinutes.list(end=end_date, period=days, client=client),
        "hrv_status": lambda: DailyHRV.list(end=end_date, period=days, client=client),
    }
    return {name: _safe_fetch(name, getter, log_err) for name, getter in fetchers.items()}


def _collect_connectapi(
    client: garth.Client,
    dates: Iterable[date],
    start_date: date,
    end_date: date,
    log_err: Callable[[str], None],
    sources: Dict[str, Dict[str, Any]],
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    per_day: Dict[str, Dict[str, Any]] = defaultdict(dict)
    multi_day: Dict[str, Any] = {}
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    for name, spec in sources.items():
        method = spec.get("method", "GET")
        path_template = spec["path"]
        params_template = spec.get("params")
        if spec.get("per_day", False):
            for day in dates:
                date_str = day.strftime("%Y-%m-%d")
                path = path_template.format(date=date_str, start=start_str, end=end_str)
                params = _render_params(params_template, date_str=date_str, start_str=start_str, end_str=end_str)
                per_day[date_str][name] = _safe_fetch(
                    f"{name}@{date_str}",
                    lambda p=path, prm=params, m=method: client.connectapi(p, method=m, params=prm),
                    log_err,
                )
        else:
            path = path_template.format(date=end_str, start=start_str, end=end_str)
            params = _render_params(params_template, date_str=end_str, start_str=start_str, end_str=end_str)
            multi_day[name] = _safe_fetch(
                name, lambda p=path, prm=params, m=method: client.connectapi(p, method=m, params=prm), log_err
            )
    return per_day, multi_day


def _collect_activity_details(
    client: garth.Client, activity_list: list[dict[str, Any]], log_err: Callable[[str], None]
) -> Tuple[Dict[str, Any], Dict[str, list[dict[str, Any]]]]:
    details: Dict[str, Any] = {}
    fit_records: Dict[str, list[dict[str, Any]]] = {}
    for activity in activity_list:
        act_id = activity.get("activityId") or activity.get("id")
        if not act_id:
            continue
        act_key = str(act_id)
        details[act_key] = _safe_fetch(
            f"activity_details@{act_key}",
            lambda aid=act_id: client.connectapi(
                f"/activity-service/activity/{aid}/details",
                params={"maxChartSize": 5000, "maxPolylineSize": 5000},
            ),
            log_err,
        )
        fit_bytes = _download_activity_fit(client, act_id, log_err)
        if fit_bytes:
            fit_records[act_key] = _parse_fit_records(fit_bytes, log_err)
    return details, fit_records


def main() -> None:
    args = _parse_args()
    if args.days < 1:
        raise SystemExit("days must be >= 1")
    end_date = (
        datetime.strptime(args.end_date, "%Y-%m-%d").date()
        if args.end_date
        else datetime.now(timezone.utc).date()
    )
    start_date = end_date - timedelta(days=args.days - 1)
    token_root = Path(args.token_dir).expanduser() if args.token_dir else None
    error_log_path = Path(args.error_output).expanduser() if args.error_output else None
    if error_log_path:
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        error_log_path.write_text("", encoding="utf-8")
    log_err = _make_error_logger(error_log_path)

    client, email = _build_client(token_root, args.domain, log_err, args.email)
    # Profile via socialProfile endpoint (avoid 404 from user-service).
    profile = _safe_fetch("profile", lambda: client.user_profile, log_err)
    social_profile = profile

    stat_blocks = _collect_stat_blocks(client, end_date, args.days, log_err)
    dates = list(_date_list(end_date, args.days))
    connectapi_sources = dict(CONNECTAPI_SOURCES)
    if args.include_extra_connectapi:
        connectapi_sources.update(EXTRA_CONNECTAPI_SOURCES)
    connectapi_per_day, connectapi_multi = _collect_connectapi(
        client, dates, start_date, end_date, log_err, connectapi_sources
    )

    activity_list: list[dict[str, Any]] = []
    activity_details: Dict[str, Any] = {}
    activity_fit_records: Dict[str, list[dict[str, Any]]] = {}
    raw_activities = connectapi_multi.get("activities")
    if isinstance(raw_activities, dict):
        maybe_list = raw_activities.get("activityList") or raw_activities.get("activities")
        if isinstance(maybe_list, list):
            activity_list = maybe_list
            if activity_list:
                activity_details, activity_fit_records = _collect_activity_details(client, activity_list, log_err)

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "account": {"email": email, "username": getattr(client, "username", None)},
        "range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "days": args.days},
        "profile": profile,
        "social_profile": social_profile,
        "stats": {name: _json_ready(val) for name, val in stat_blocks.items()},
        "connectapi": {
            "per_day": {day: _json_ready(payloads) for day, payloads in connectapi_per_day.items()},
            "multi_day": {name: _json_ready(val) for name, val in connectapi_multi.items()},
        },
        "activities": {
            "list": _json_ready(activity_list),
            "details": {key: _json_ready(val) for key, val in activity_details.items()},
            "fit_records": {key: _json_ready(val) for key, val in activity_fit_records.items()},
        },
    }

    output = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).expanduser().write_text(output, encoding="utf-8")
        print(f"Wrote health data to {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
