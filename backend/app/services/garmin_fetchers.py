"""
Fetch Garmin health data using only validated endpoints from test.py.
Provides a consolidated bundle for downstream timeseries and aggregates.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, Iterable, List, Tuple

from garth.data.hrv import HRVData
from garth.data.sleep import SleepData
from garth.stats.hrv import DailyHRV
from garth.stats.intensity_minutes import DailyIntensityMinutes
from garth.stats.sleep import DailySleep
from garth.stats.steps import DailySteps
from garth.stats.stress import DailyStress
from garth.utils import camel_to_snake_dict

logger = logging.getLogger("garmin_fetchers")
logger.setLevel(logging.INFO)

# ConnectAPI endpoints that were validated in the latest test run.
CONNECTAPI_SOURCES: Dict[str, Dict[str, Any]] = {
    "daily_stress": {"path": "wellness-service/wellness/dailyStress/{date}", "per_day": True},
    "daily_vo2max": {"path": "metrics-service/metrics/maxmet/latest/{date}", "per_day": True},
    "sleep_timeseries": {
        "path": "sleep-service/sleep/dailySleepData",
        "per_day": True,
        "params": {"date": "{date}", "nonSleepBufferMinutes": 60},
    },
    "weight_range": {
        "path": "weight-service/weight/dateRange",
        "per_day": True,
        "params": {"startDate": "{date}", "endDate": "{date}"},
    },
    "monthly_vo2max": {"path": "metrics-service/metrics/maxmet/monthly/{start}/{end}", "per_day": False},
    "acclimation": {
        "path": "wellness-service/stats/daily/acclimation",
        "per_day": False,
        "params": {"fromDate": "{start}", "untilDate": "{end}"},
    },
    # Activity list (summary)
    "activities": {
        "path": "activitylist-service/activities",
        "per_day": False,
        "params": {"start": 0, "limit": 20},
    },
}

# Stats endpoints (garth helpers) that returned data.
STAT_FETCHERS: Dict[str, Callable] = {
    "sleep_data": lambda client, end_date, days: SleepData.list(end=end_date, days=days, client=client),
    "sleep_score": lambda client, end_date, days: DailySleep.list(end=end_date, period=days, client=client),
    "steps": lambda client, end_date, days: DailySteps.list(end=end_date, period=days, client=client),
    "stress": lambda client, end_date, days: DailyStress.list(end=end_date, period=days, client=client),
    "intensity_minutes": lambda client, end_date, days: DailyIntensityMinutes.list(end=end_date, period=days, client=client),
    "hrv_status": lambda client, end_date, days: DailyHRV.list(end=end_date, period=days, client=client),
    "hrv_data": lambda client, end_date, days: HRVData.list(end=end_date, days=days, client=client),
}


def _json_ready(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return _json_ready(asdict(value))
    if isinstance(value, dict):
        return {k: _json_ready(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


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


def _date_list(end_date: date, days: int) -> Iterable[date]:
    for i in range(days):
        yield end_date - timedelta(days=i)


def fetch_stats(client, end_date: date, days: int) -> Dict[str, Any]:
    stats: Dict[str, Any] = {}
    for name, fetcher in STAT_FETCHERS.items():
        try:
            stats[name] = _json_ready(fetcher(client, end_date, days))
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("garmin stat fetch failed", extra={"stat": name, "error": str(exc)}, exc_info=True)
            stats[name] = {"error": str(exc)}
    return stats


def fetch_connectapi(
    client,
    dates: Iterable[date],
    start_date: date,
    end_date: date,
    include_extra: bool = False,
) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    per_day: Dict[str, Dict[str, Any]] = {}
    multi_day: Dict[str, Any] = {}
    sources = dict(CONNECTAPI_SOURCES)
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
                per_day.setdefault(date_str, {})
                try:
                    per_day[date_str][name] = _json_ready(client.connectapi(path, method=method, params=params))
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "garmin connectapi per-day fetch failed",
                        extra={"name": name, "date": date_str, "error": str(exc)},
                        exc_info=True,
                    )
                    per_day[date_str][name] = {"error": str(exc)}
        else:
            path = path_template.format(date=end_str, start=start_str, end=end_str)
            params = _render_params(params_template, date_str=end_str, start_str=start_str, end_str=end_str)
            try:
                multi_day[name] = _json_ready(client.connectapi(path, method=method, params=params))
            except Exception as exc:  # pylint: disable=broad-except
                logger.warning(
                    "garmin connectapi multi-day fetch failed",
                    extra={"name": name, "error": str(exc)},
                    exc_info=True,
                )
                multi_day[name] = {"error": str(exc)}
    return per_day, multi_day


def fetch_health_bundle(
    client,
    *,
    end_date: date,
    days: int,
    include_extra_connectapi: bool = False,
) -> Dict[str, Any]:
    """
    Fetch all validated stats + connectapi endpoints for a date window.
    """
    start_date = end_date - timedelta(days=days - 1)
    stats = fetch_stats(client, end_date, days)
    per_day, multi_day = fetch_connectapi(client, _date_list(end_date, days), start_date, end_date, include_extra_connectapi)
    return {
        "fetched_at": datetime.utcnow().isoformat(),
        "range": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "days": days},
        "stats": stats,
        "connectapi": {"per_day": per_day, "multi_day": multi_day},
    }
