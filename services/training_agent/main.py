from __future__ import annotations

import html
import os
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader
from influxdb import InfluxDBClient

API_KEY_NAME = "X-TRAINING-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)

app = FastAPI(title="Garmin Training API", version="0.1.0")


ActionParam = dict[str, object]
ActionSpec = dict[str, object]


RUN_TYPE_LABELS = {
    "running": "Outdoor run",
    "treadmill_running": "Treadmill run",
    "trail_running": "Trail run",
}


def resolve_cadence(row: dict) -> Optional[float]:
    """Garmin activities sometimes store cadence under different keys."""
    for key in (
        "averageRunCadence",
        "avgRunCadence",
        "averageCadence",
        "avgCadence",
        "cadence",
    ):
        value = row.get(key)
        if value is not None:
            return value
    return None


def fetch_cadence_from_gps(client: InfluxDBClient, activity_id: int) -> Optional[float]:
    query = (
        'SELECT MEAN("Cadence") AS cadence, MEAN("Fractional_Cadence") AS fractional '
        f'FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}'
    )
    points = list(client.query(query).get_points())
    if not points:
        return None
    cadence = points[0].get("cadence")
    if cadence is None:
        return None
    fractional = points[0].get("fractional") or 0
    return cadence + fractional


def get_average_cadence(client: InfluxDBClient, row: dict) -> Optional[float]:
    cadence = resolve_cadence(row)
    if cadence is not None:
        return cadence
    activity_id = row.get("Activity_ID") or row.get("activityId")
    if not activity_id:
        return None
    try:
        # Try lap-level cadence first (aggregated across laps), then fall back to GPS.
        lap_query = (
            'SELECT MEAN("Avg_Cadence") AS cadence FROM "ActivityLap" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
        )
        lap_points = list(client.query(lap_query).get_points())
        lap_cadence = lap_points[0].get("cadence") if lap_points else None
        if lap_cadence is not None:
            return lap_cadence
        return fetch_cadence_from_gps(client, int(activity_id))
    except (ValueError, TypeError):
        return None


ACTIONS: List[ActionSpec] = [
        {
            "name": "Health Check",
            "path": "/health",
            "description": "Lightweight probe used by Docker/Kubernetes to confirm the service is running.",
            "params": [],
        },
        {
            "name": "Weekly Summary",
            "path": "/weekly-summary",
            "description": "Aggregated distance, calories, and average resting HR for the requested time window.",
            "params": [
                {
                    "name": "days",
                    "default": 7,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Sleep Summary",
            "path": "/sleep-summary",
            "description": "Average nightly sleep, stress, HRV, SpO₂, and stage durations for the time window.",
            "params": [
                {
                    "name": "days",
                    "default": 7,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "VO2 Trend",
            "path": "/vo2-trend",
            "description": "Latest and average VO₂ max value across the rolling window.",
            "params": [
                {
                    "name": "days",
                    "default": 30,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "HRV Trend",
            "path": "/hrv-trend",
            "description": "Latest and average overnight HRV values.",
            "params": [
                {
                    "name": "days",
                    "default": 30,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Last Run",
            "path": "/last-run",
            "description": "Most recent outdoor, treadmill, or trail running activity with summary metrics, running dynamics, and a run-type label.",
            "params": [],
        },
        {
            "name": "Recovery Score",
            "path": "/recovery-score",
            "description": "Latest body battery change and sleep stress metrics.",
            "params": [],
        },
        {
            "name": "Training Log",
            "path": "/training-log",
            "description": "Latest activities within the window including distance, speed, HR, training effect, and running dynamics when present.",
            "params": [
                {
                    "name": "limit",
                    "default": 20,
                    "description": "Maximum number of activities to return.",
                    "type": "number",
                    "min": 1,
                },
                {
                    "name": "days",
                    "default": 42,
                    "description": "Look-back window for activities (must be >= 1).",
                    "type": "number",
                    "min": 1,
                },
            ],
        },
        {
            "name": "Training Load Focus",
            "path": "/training-load",
            "description": "Latest low/high aerobic and anaerobic load values.",
            "params": [
                {
                    "name": "days",
                    "default": 14,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Running Dynamics",
            "path": "/running-dynamics",
            "description": "Most recent advanced running dynamics such as cadence, stride, and contact time.",
            "params": [
                {
                    "name": "days",
                    "default": 30,
                    "description": "Number of days to include when searching for the latest run.",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Recovery Time",
            "path": "/recovery-time",
            "description": "Latest prescribed recovery period from Training Status.",
            "params": [
                {
                    "name": "days",
                    "default": 7,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Sleep Metrics",
            "path": "/sleep-metrics",
            "description": "Most recent sleep stage durations, resting HR, and score.",
            "params": [
                {
                    "name": "days",
                    "default": 7,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Stress & Battery",
            "path": "/stress-battery",
            "description": "Combined stress percentage and body battery charge/drain metrics.",
            "params": [
                {
                    "name": "days",
                    "default": 7,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Lactate Threshold",
            "path": "/lactate-threshold",
            "description": "Most recent threshold heart rate and pace.",
            "params": [],
        },
        {
            "name": "Race Predictions",
            "path": "/race-predictions",
            "description": "Latest estimated finish times for common race distances.",
            "params": [
                {
                    "name": "days",
                    "default": 30,
                    "description": "Number of days to include (must be >= 1).",
                    "type": "number",
                    "min": 1,
                }
            ],
        },
        {
            "name": "Race Schedule",
            "path": "/race-schedule",
            "description": "Upcoming calendar items with location and start time.",
            "params": [
                {
                    "name": "limit",
                    "default": 5,
                    "description": "Maximum number of future events to return.",
                    "type": "number",
                    "min": 1,
                },
                {
                    "name": "days",
                    "default": 365,
                    "description": "Look-ahead window for calendar items (must be >= 1).",
                    "type": "number",
                    "min": 1,
                },
            ],
        },
    ]


def render_action_index(base_url: str, api_key: str | None) -> str:
    def render_field(param: ActionParam) -> str:
        input_type = html.escape(str(param.get("type", "text")))
        default = html.escape(str(param.get("default", "")))
        name = html.escape(str(param["name"]))
        desc = html.escape(str(param.get("description", "")))
        attrs = []
        for attr_name in ("min", "max", "step"):
            if attr_name in param:
                attrs.append(f" {attr_name}='{param[attr_name]}'")
        attr_str = "".join(attrs)
        return (
            "<label class='field'>"
            f"<span>{name}</span>"
            f"<input type='{input_type}' name='{name}' value='{default}'{attr_str}>"
            f"<small>{desc}</small>"
            "</label>"
        )

    action_cards = []
    for spec in ACTIONS:
        path = html.escape(str(spec["path"]))
        name = html.escape(str(spec["name"]))
        description = html.escape(str(spec.get("description", "")))
        params = spec.get("params") or []
        if params:
            fields = "".join(render_field(p) for p in params)
            form_html = f"""
                <form class="api-form" data-endpoint="{path}">
                    <div class="fields">
                        {fields}
                    </div>
                    <div class="form-actions">
                        <button type="submit">Send via harness</button>
                        <a href="{path}" target="_blank" rel="noreferrer">Open without header</a>
                    </div>
                </form>
            """
        else:
            form_html = f"""
                <p class="no-params">No query parameters</p>
                <div class="form-actions no-fields">
                    <button class="button-link ghost no-param" data-endpoint="{path}" type="button">Send via harness</button>
                    <a class="button-link" href="{path}" target="_blank" rel="noreferrer">Open without header</a>
                </div>
            """
        card = f"""
        <section class="card">
            <header>
                <h2>{name}</h2>
                <code>GET {path}</code>
            </header>
            <p class="description">{description}</p>
            {form_html}
        </section>
        """
        action_cards.append(card)

    cards_html = "\n".join(action_cards)
    escaped_base = html.escape(base_url)
    api_key_value = html.escape(api_key or "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Garmin Training API Explorer</title>
    <style>
        :root {{
            color-scheme: light dark;
            font-family: "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
        }}
        body {{
            margin: 0;
            padding: 2rem;
            background: #0b1120;
            color: #f8fafc;
        }}
        h1 {{
            margin-top: 0;
            font-size: 2rem;
        }}
        a {{
            color: #38bdf8;
        }}
        .cards {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
            gap: 1rem;
        }}
        .card {{
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid rgba(148, 163, 184, 0.2);
            border-radius: 0.75rem;
            padding: 1rem;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.6);
        }}
        .card header {{
            display: flex;
            justify-content: space-between;
            align-items: baseline;
            gap: 0.5rem;
        }}
        .card code {{
            background: rgba(15, 118, 110, 0.15);
            padding: 0.1rem 0.4rem;
            border-radius: 0.4rem;
            font-size: 0.8rem;
        }}
        .fields {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.75rem;
            margin-bottom: 0.75rem;
        }}
        .field {{
            flex: 1 1 140px;
            display: flex;
            flex-direction: column;
            font-size: 0.9rem;
        }}
        .field span {{
            font-weight: 600;
        }}
        .field input {{
            margin-top: 0.15rem;
            padding: 0.35rem 0.5rem;
            border-radius: 0.4rem;
            border: 1px solid rgba(148, 163, 184, 0.4);
            background: rgba(15, 23, 42, 0.6);
            color: inherit;
        }}
        .field small {{
            opacity: 0.7;
            font-size: 0.75rem;
        }}
        .no-params {{
            font-style: italic;
            opacity: 0.8;
        }}
        button {{
            background: #0ea5e9;
            color: #0f172a;
            border: none;
            padding: 0.5rem 0.9rem;
            border-radius: 0.5rem;
            cursor: pointer;
            font-weight: 600;
        }}
        button:hover {{
            background: #38bdf8;
        }}
        .form-actions {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 0.5rem;
        }}
        .form-actions.no-fields {{
            justify-content: flex-start;
        }}
        .form-actions a {{
            text-decoration: none;
        }}
        .callout {{
            background: rgba(56, 189, 248, 0.1);
            padding: 1rem;
            border-radius: 0.75rem;
            border: 1px solid rgba(56, 189, 248, 0.3);
            margin-bottom: 1.5rem;
        }}
        .button-link {{
            display: inline-flex;
            align-items: center;
            justify-content: center;
            background: #0ea5e9;
            color: #0f172a;
            padding: 0.5rem 0.9rem;
            border-radius: 0.5rem;
            font-weight: 600;
        }}
        .button-link:hover {{
            background: #38bdf8;
        }}
        .button-link.ghost {{
            border: 1px solid rgba(56, 189, 248, 0.6);
            background: transparent;
            color: #38bdf8;
        }}
        .button-link.ghost:hover {{
            background: rgba(56, 189, 248, 0.15);
        }}
        .api-key-input {{
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            margin-top: 0.5rem;
        }}
        .api-key-input input {{
            padding: 0.35rem 0.5rem;
            border-radius: 0.5rem;
            border: 1px solid rgba(148, 163, 184, 0.4);
            background: rgba(15, 23, 42, 0.6);
            color: inherit;
        }}
        pre {{
            background: rgba(15, 23, 42, 0.7);
            padding: 0.75rem;
            border-radius: 0.5rem;
            overflow-x: auto;
        }}
        #response-log {{
            margin-top: 2rem;
            background: rgba(15, 23, 42, 0.85);
            border-radius: 0.75rem;
            border: 1px solid rgba(56, 189, 248, 0.2);
            padding: 1rem;
        }}
        #response-log h2 {{
            margin-top: 0;
        }}
        #response-log pre {{
            margin: 0;
            white-space: pre-wrap;
            word-break: break-word;
        }}
        .response-meta {{
            display: flex;
            justify-content: space-between;
            flex-wrap: wrap;
            font-size: 0.85rem;
            margin-bottom: 0.5rem;
            opacity: 0.8;
        }}
    </style>
</head>
<body>
    <h1>Garmin Training API Explorer</h1>
    <section class="callout">
        <p>Most endpoints require the <code>{API_KEY_NAME}</code> header.</p>
        <div class="api-key-input">
            <label for="api-key-field">API key used by harness</label>
            <input id="api-key-field" type="password" value="{api_key_value}" placeholder="Enter API key">
        </div>
        <p>Example curl:</p>
        <pre>curl -H "{API_KEY_NAME}: &lt;your key&gt;" {escaped_base}/weekly-summary</pre>
    </section>
    <div class="cards">
        {cards_html}
    </div>
    <section id="response-log">
        <h2>Latest response</h2>
        <div class="response-meta">
            <span id="response-endpoint">Endpoint: –</span>
            <span id="response-status">Status: –</span>
        </div>
        <pre id="response-body">Use the harness to send a request and the body will appear here.</pre>
    </section>
    <script>
        const API_KEY_HEADER = "{API_KEY_NAME}";
        const apiKeyField = document.getElementById("api-key-field");
        const responseEndpoint = document.getElementById("response-endpoint");
        const responseStatus = document.getElementById("response-status");
        const responseBody = document.getElementById("response-body");

        function formatBody(body) {{
            if (!body) {{
                return "";
            }}
            const trimmed = body.trim();
            if (!trimmed) {{
                return "";
            }}
            if ((trimmed.startsWith("{{") && trimmed.endsWith("}}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {{
                try {{
                    const parsed = JSON.parse(trimmed);
                    return JSON.stringify(parsed, null, 2);
                }} catch (err) {{
                    // fall back to raw text
                }}
            }}
            return body;
        }}

        function logResponse(endpoint, status, body) {{
            responseEndpoint.textContent = `Endpoint: ${{endpoint}}`;
            responseStatus.textContent = `Status: ${{status}}`;
            responseBody.textContent = formatBody(body);
        }}

        async function sendRequest(endpoint, params) {{
            const url = new URL(endpoint, window.location.origin);
            params.forEach(([key, value]) => {{
                if (value !== "") {{
                    url.searchParams.append(key, value);
                }}
            }});
            const headers = {{}};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) {{
                headers[API_KEY_HEADER] = apiKey;
            }}
            try {{
                const res = await fetch(url.toString(), {{ headers }});
                const text = await res.text();
                logResponse(`${{url.pathname}}${{url.search}}`, res.status, text);
            }} catch (error) {{
                logResponse(endpoint, "error", String(error));
            }}
        }}

        document.querySelectorAll(".api-form").forEach((form) => {{
            form.addEventListener("submit", (event) => {{
                event.preventDefault();
                const data = new FormData(form);
                const params = [];
                for (const [key, value] of data.entries()) {{
                    params.push([key, value]);
                }}
                sendRequest(form.dataset.endpoint, params);
            }});
        }});

        document.querySelectorAll(".no-param").forEach((button) => {{
            button.addEventListener("click", () => {{
                sendRequest(button.dataset.endpoint, []);
            }});
        }});
    </script>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse)
def action_index(request: Request) -> HTMLResponse:
    return HTMLResponse(
        render_action_index(str(request.base_url).rstrip("/"), os.environ.get("TRAINING_API_KEY"))
    )


def get_influx_client() -> InfluxDBClient:
    return InfluxDBClient(
        host=os.environ.get("INFLUXDB_HOST", "influxdb"),
        port=int(os.environ.get("INFLUXDB_PORT", "8086")),
        username=os.environ.get("INFLUXDB_USERNAME", "influxdb_user"),
        password=os.environ.get("INFLUXDB_PASSWORD", "influxdb_secret_password"),
        database=os.environ.get("INFLUXDB_DATABASE", "GarminStats"),
        timeout=10,
    )


def require_api_key(header: Optional[str] = Security(api_key_header)) -> None:
    expected = os.environ.get("TRAINING_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="Server missing TRAINING_API_KEY env")
    if header != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/weekly-summary", dependencies=[Depends(require_api_key)])
def weekly_summary(days: int = 7):
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT SUM("distance") AS distance, SUM("calories") AS calories '
        f'FROM "ActivitySummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    stats = result[0] if result else {"distance": 0, "calories": 0}

    hr_query = (
        'SELECT MEAN("restingHeartRate") AS rhr FROM "DailyStats" '
        f'WHERE time >= now() - {window}d'
    )
    hr_result = list(client.query(hr_query).get_points())
    stats["resting_hr"] = hr_result[0]["rhr"] if hr_result else None
    stats["window_days"] = window
    return stats


@app.get("/sleep-summary", dependencies=[Depends(require_api_key)])
def sleep_summary(days: int = 7):
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT MEAN("sleepTimeSeconds") AS sleep, '
        'MEAN("avgSleepStress") AS stress, '
        'MEAN("avgOvernightHrv") AS hrv, '
        'MEAN("averageSpO2Value") AS spo2_avg, '
        'MIN("lowestSpO2Value") AS spo2_low, '
        'MAX("highestSpO2Value") AS spo2_high, '
        'MEAN("restingHeartRate") AS resting_hr, '
        'MEAN("deepSleepSeconds") AS deep, '
        'MEAN("lightSleepSeconds") AS light, '
        'MEAN("remSleepSeconds") AS rem, '
        'MEAN("awakeSleepSeconds") AS awake '
        f'FROM "SleepSummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"window_days": window}
    row = result[0]
    return {
        "sleep_seconds": row.get("sleep"),
        "avg_sleep_stress": row.get("stress"),
        "avg_hrv": row.get("hrv"),
        "spo2_average": row.get("spo2_avg"),
        "spo2_low": row.get("spo2_low"),
        "spo2_high": row.get("spo2_high"),
        "resting_heart_rate": row.get("resting_hr"),
        "deep_sleep_seconds": row.get("deep"),
        "light_sleep_seconds": row.get("light"),
        "rem_sleep_seconds": row.get("rem"),
        "awake_sleep_seconds": row.get("awake"),
        "window_days": window,
    }


@app.get("/vo2-trend", dependencies=[Depends(require_api_key)])
def vo2_trend(days: int = 30):
    window = max(days, 1)
    client = get_influx_client()
    query = (
        'SELECT LAST("VO2_max_value") AS latest, MEAN("VO2_max_value") AS average '
        f'FROM "VO2_Max" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"latest": None, "average": None, "window_days": window}
    row = result[0]
    latest = row.get("latest")
    avg = row.get("average")
    return {"latest": latest, "average": avg, "window_days": window}


@app.get("/hrv-trend", dependencies=[Depends(require_api_key)])
def hrv_trend(days: int = 30):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("avgOvernightHrv") AS latest, MEAN("avgOvernightHrv") AS average '
        f'FROM "SleepSummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    payload = result[0] if result else {"latest": None, "average": None}
    payload["window_days"] = window
    return payload


@app.get("/last-run", dependencies=[Depends(require_api_key)])
def last_run():
    client = get_influx_client()
    query = (
        'SELECT * FROM "ActivitySummary" '
        "WHERE activityType = 'running' "
        "OR activityType = 'treadmill_running' "
        "OR activityType = 'trail_running' "
        "ORDER BY time DESC LIMIT 1"
    )
    result = list(client.query(query).get_points())
    if not result:
        return {}
    row = result[0]
    run_type = row.get("activityType")
    cadence = get_average_cadence(client, row)
    return {
        "activity_id": row.get("Activity_ID"),
        "start_time": row.get("time"),
        "distance_m": row.get("distance"),
        "duration_s": row.get("elapsedDuration"),
        "moving_duration_s": row.get("movingDuration"),
        "avg_hr": row.get("averageHR"),
        "calories": row.get("calories"),
        "activity_type": run_type,
        "run_label": RUN_TYPE_LABELS.get(run_type, run_type or "run"),
        "average_cadence": cadence,
        "stride_length": row.get("strideLength"),
        "vertical_oscillation": row.get("verticalOscillation"),
        "ground_contact_time": row.get("groundContactTime"),
        "ground_contact_balance": row.get("groundContactBalance"),
        "stance_time_percent": row.get("stanceTimePercent"),
    }


@app.get("/recovery-score", dependencies=[Depends(require_api_key)])
def recovery_score():
    client = get_influx_client()
    query = (
        'SELECT LAST("bodyBatteryChange") AS body_battery, '
        'LAST("avgSleepStress") AS sleep_stress '
        'FROM "SleepSummary" WHERE time >= now() - 7d'
    )
    result = list(client.query(query).get_points())
    if not result:
        return {"body_battery": None, "sleep_stress": None}
    row = result[0]
    return {
        "body_battery_change": row.get("body_battery"),
        "sleep_stress": row.get("sleep_stress"),
    }


@app.get("/training-log", dependencies=[Depends(require_api_key)])
def training_log(limit: int = 20, days: int = 42):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "distance","elapsedDuration","movingDuration","averageSpeed","averageHR","calories",'
        '"activityType","totalElevationGain","trainingEffectLabel","activityId","Activity_ID","averageRunCadence","avgRunCadence",'
        '"averageCadence","avgCadence","strideLength","verticalOscillation","groundContactTime",'
        '"groundContactBalance","stanceTimePercent" '
        f'FROM "ActivitySummary" WHERE time >= now() - {window}d '
        "ORDER BY time DESC LIMIT {}".format(int(limit))
    )
    result = list(client.query(query).get_points())
    enriched = []
    for row in result:
        run_type = row.get("activityType")
        entry = dict(row)
        entry["run_label"] = RUN_TYPE_LABELS.get(run_type, run_type)
        entry["average_cadence"] = get_average_cadence(client, row)
        entry["stride_length"] = row.get("strideLength")
        entry["vertical_oscillation"] = row.get("verticalOscillation")
        entry["ground_contact_time"] = row.get("groundContactTime")
        entry["ground_contact_balance"] = row.get("groundContactBalance")
        entry["stance_time_percent"] = row.get("stanceTimePercent")
        enriched.append(entry)
    return {"window_days": window, "entries": enriched}


@app.get("/training-load", dependencies=[Depends(require_api_key)])
def training_load_focus(days: int = 14):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("lowAerobicLoad") AS low, LAST("highAerobicLoad") AS high, '
        'LAST("anaerobicLoad") AS anaerobic FROM "TrainingStatus" '
        f"WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    payload = result[0] if result else {"low": None, "high": None, "anaerobic": None}
    payload["window_days"] = window
    return payload


@app.get("/running-dynamics", dependencies=[Depends(require_api_key)])
def running_dynamics(days: int = 30):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "averageRunCadence","strideLength","verticalOscillation",'
        '"groundContactTime","activityId" FROM "ActivitySummary" '
        f"WHERE activityType = 'running' AND time >= now() - {window}d "
        "ORDER BY time DESC LIMIT 1"
    )
    result = list(client.query(query).get_points())
    if not result:
        return {}
    row = result[0]
    return {
        "activity_id": row.get("activityId") or row.get("Activity_ID"),
        "average_cadence": get_average_cadence(client, row),
        "stride_length": row.get("strideLength"),
        "vertical_oscillation": row.get("verticalOscillation"),
        "ground_contact_time": row.get("groundContactTime"),
    }


@app.get("/recovery-time", dependencies=[Depends(require_api_key)])
def recovery_time(days: int = 7):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("recoveryTime") AS hours FROM "TrainingStatus" '
        f"WHERE time >= now() - {window}d"
    )
    result = list(client.query(query).get_points())
    return {
        "recovery_time_hours": result[0]["hours"] if result else None,
        "window_days": window,
    }


@app.get("/sleep-metrics", dependencies=[Depends(require_api_key)])
def sleep_metrics(days: int = 7):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("sleepTimeSeconds") AS sleep, LAST("deepSleepSeconds") AS deep, '
        'LAST("lightSleepSeconds") AS light, LAST("remSleepSeconds") AS rem, '
        'LAST("awakeSleepSeconds") AS awake, LAST("sleepScore") AS score, '
        'LAST("restingHeartRate") AS rhr '
        f'FROM "SleepSummary" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    payload = result[0] if result else {}
    payload["window_days"] = window
    return payload


@app.get("/stress-battery", dependencies=[Depends(require_api_key)])
def stress_battery(days: int = 7):
    client = get_influx_client()
    window = max(days, 1)
    stress_query = (
        'SELECT LAST("stressPercentage") AS stress FROM "DailyStats" '
        f"WHERE time >= now() - {window}d"
    )
    battery_query = (
        'SELECT LAST("bodyBatteryChargedValue") AS charged, '
        'LAST("bodyBatteryDrainedValue") AS drained '
        f'FROM "DailyStats" WHERE time >= now() - {window}d'
    )
    stress = list(client.query(stress_query).get_points())
    battery = list(client.query(battery_query).get_points())
    return {
        "stress_percentage": stress[0]["stress"] if stress else None,
        "body_battery_charged": battery[0]["charged"] if battery else None,
        "body_battery_drained": battery[0]["drained"] if battery else None,
        "window_days": window,
    }


@app.get("/lactate-threshold", dependencies=[Depends(require_api_key)])
def lactate_threshold():
    client = get_influx_client()
    query = (
        'SELECT LAST("heartRate") AS heart_rate, LAST("pace") AS pace '
        'FROM "LactateThreshold"'
    )
    result = list(client.query(query).get_points())
    return result[0] if result else {"heart_rate": None, "pace": None}


@app.get("/race-predictions", dependencies=[Depends(require_api_key)])
def race_predictions(days: int = 30):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT LAST("time5K") AS time5K, LAST("time10K") AS time10K, '
        'LAST("timeHalfMarathon") AS half, LAST("timeMarathon") AS marathon '
        f'FROM "RacePredictions" WHERE time >= now() - {window}d'
    )
    result = list(client.query(query).get_points())
    payload = result[0] if result else {}
    payload["window_days"] = window
    return payload


@app.get("/race-schedule", dependencies=[Depends(require_api_key)])
def race_schedule(limit: int = 5, days: int = 365):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "summary","startTimeLocal","location" FROM "CalendarItems" '
        f"WHERE time >= now() AND time <= now() + {window}d "
        "ORDER BY time ASC LIMIT {}".format(int(limit))
    )
    result = list(client.query(query).get_points())
    return {"window_days": window, "entries": result}
