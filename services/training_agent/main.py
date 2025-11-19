# ruff: noqa: E501
from __future__ import annotations

import html
import json
import logging
import os
import time
from typing import List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Header
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.responses import HTMLResponse, Response
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google.auth import exceptions as google_exceptions
from influxdb import InfluxDBClient
from influxdb.exceptions import InfluxDBClientError, InfluxDBServerError
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
import requests

app = FastAPI(title="Garmin Training API", version="0.1.0")


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    """Capture request latency and counts for observability."""
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    route_template = getattr(request.scope.get("route"), "path", request.url.path)
    labels = {
        "method": request.method,
        "path": route_template,
        "status": str(response.status_code),
    }
    REQUEST_COUNTER.labels(**labels).inc()
    REQUEST_LATENCY.labels(**labels).observe(elapsed)
    return response


ActionParam = dict[str, object]
ActionSpec = dict[str, object]

GOOGLE_AUTH_URL = (
    os.environ.get("RUNTRAINER_GOOGLE_AUTH_URL")
    or os.environ.get("GOOGLE_AUTH_URL")
    or "https://accounts.google.com/o/oauth2/v2/auth"
)
GOOGLE_TOKEN_URL = (
    os.environ.get("RUNTRAINER_GOOGLE_TOKEN_URL")
    or os.environ.get("GOOGLE_TOKEN_URL")
    or "https://oauth2.googleapis.com/token"
)
GOOGLE_CLIENT_ID = os.environ.get("RUNTRAINER_GOOGLE_CLIENT_ID") or os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("RUNTRAINER_GOOGLE_CLIENT_SECRET") or os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = (
    os.environ.get("RUNTRAINER_GOOGLE_REDIRECT_URI")
    or os.environ.get("GOOGLE_REDIRECT_URI")
    or "https://chat.openai.com/aip/g-11e1b5846d447ba53af301061856b1a079cb91b9/oauth/callback"
)
DEFAULT_SCOPE = os.environ.get("RUNTRAINER_GOOGLE_SCOPE") or "openid email profile"
TOKENINFO_URL = "https://oauth2.googleapis.com/tokeninfo"
GOOGLE_REQUEST_TIMEOUT = 5
METRICS_NAMESPACE = "training_agent"
REQUEST_COUNTER = Counter(
    f"{METRICS_NAMESPACE}_requests_total",
    "HTTP requests processed",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    f"{METRICS_NAMESPACE}_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path", "status"],
)
API_KEY_NAME = os.environ.get("TRAINING_API_KEY_HEADER", "x-api-key")

logger = logging.getLogger("training_agent.oauth")
logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)
logger.propagate = True
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    logger.addHandler(handler)


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


def get_elevation_gain(client: InfluxDBClient, activity_id: int) -> Optional[float]:
    """Return total positive elevation gain for an activity, if available."""
    try:
        # If summary already has it, prefer that.
        summary = list(
            client.query(
                f'SELECT "totalElevationGain" FROM "ActivitySummary" WHERE "Activity_ID" = {int(activity_id)} LIMIT 1'
            ).get_points()
        )
        if summary:
            gain = summary[0].get("totalElevationGain")
            if gain is not None:
                return gain

        # Compute from GPS altitude deltas, summing only positive changes.
        q = (
            "SELECT SUM(\"alt_diff\") AS gain FROM ("
            'SELECT DIFFERENCE("Altitude") AS alt_diff FROM "ActivityGPS" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
            ") WHERE alt_diff > 0"
        )
        points = list(client.query(q).get_points())
        if points:
            return points[0].get("gain")
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Elevation gain query failed",
            extra={"activity_id": activity_id, "error": str(err), "error_type": type(err).__name__},
        )
        return None
    return None


def first_non_null(*values):
    for v in values:
        if v is not None:
            return v
    return None


def get_elevation_stats(client: InfluxDBClient, activity_id: int) -> dict[str, Optional[float]]:
    """Return ascent, descent, min, and max elevation for an activity."""
    stats = {"ascent": None, "descent": None, "min": None, "max": None}
    try:
        base = list(
            client.query(
                f'SELECT MIN("Altitude") AS min_alt, MAX("Altitude") AS max_alt '
                f'FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}'
            ).get_points()
        )
        if base:
            stats["min"] = base[0].get("min_alt")
            stats["max"] = base[0].get("max_alt")

        ascent_q = (
            "SELECT SUM(\"alt_diff\") AS gain FROM ("
            'SELECT DIFFERENCE("Altitude") AS alt_diff FROM "ActivityGPS" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
            ") WHERE alt_diff > 0"
        )
        ascent = list(client.query(ascent_q).get_points())
        if ascent:
            stats["ascent"] = ascent[0].get("gain")

        descent_q = (
            "SELECT SUM(\"alt_diff\") AS loss FROM ("
            'SELECT DIFFERENCE("Altitude") AS alt_diff FROM "ActivityGPS" '
            f'WHERE "Activity_ID" = {int(activity_id)}'
            ") WHERE alt_diff < 0"
        )
        descent = list(client.query(descent_q).get_points())
        if descent:
            loss = descent[0].get("loss")
            stats["descent"] = abs(loss) if loss is not None else None
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Elevation stats query failed", extra={"activity_id": activity_id, "error": str(err), "partial": stats}
        )
        return stats
    return stats


def get_temperature_stats(client: InfluxDBClient, activity_id: int) -> dict[str, Optional[float]]:
    """Return avg/min/max temperature for an activity if available."""
    stats = {"avg": None, "min": None, "max": None}
    try:
        temps = list(
            client.query(
                f'SELECT MEAN("Temperature") AS avg_temp, MIN("Temperature") AS min_temp, '
                f'MAX("Temperature") AS max_temp FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}'
            ).get_points()
        )
        if temps:
            row = temps[0]
            stats["avg"] = row.get("avg_temp")
            stats["min"] = row.get("min_temp")
            stats["max"] = row.get("max_temp")
        if stats["avg"] is None:
            lap = list(
                client.query(
                    f'SELECT MEAN("Avg_Temperature") AS avg_temp FROM "ActivityLap" WHERE "Activity_ID" = {int(activity_id)}'
                ).get_points()
            )
            if lap:
                stats["avg"] = lap[0].get("avg_temp")
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Temperature stats query failed", extra={"activity_id": activity_id, "error": str(err), "partial": stats}
        )
        return stats
    return stats


def get_max_cadence(client: InfluxDBClient, activity_id: int) -> Optional[float]:
    try:
        gps = list(
            client.query(
                f'SELECT MAX("Cadence") AS max_cadence FROM "ActivityGPS" WHERE "Activity_ID" = {int(activity_id)}'
            ).get_points()
        )
        if gps and gps[0].get("max_cadence") is not None:
            return gps[0].get("max_cadence")
        lap = list(
            client.query(
                f'SELECT MAX("Avg_Cadence") AS max_cadence FROM "ActivityLap" WHERE "Activity_ID" = {int(activity_id)}'
            ).get_points()
        )
        if lap:
            return lap[0].get("max_cadence")
    except (InfluxDBClientError, InfluxDBServerError, ValueError, TypeError) as err:
        logger.warning(
            "Max cadence query failed",
            extra={"activity_id": activity_id, "error": str(err), "error_type": type(err).__name__},
        )
        return None
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
    api_header = API_KEY_NAME
    api_header_escaped = html.escape(api_header)
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
        <p>Most endpoints require the <code>{api_header_escaped}</code> header.</p>
        <div class="api-key-input">
            <label for="api-key-field">API key used by harness</label>
            <input id="api-key-field" type="password" value="{api_key_value}" placeholder="Enter API key">
        </div>
        <p>Example curl:</p>
        <pre>curl -H "{api_header_escaped}: &lt;your key&gt;" {escaped_base}/weekly-summary</pre>
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
        const API_KEY_HEADER = "{api_header_escaped}";
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


def verify_google_bearer(token: str, audience: str) -> dict:
    """
    Accept either a Google ID token (JWT) or an OAuth access token issued for the same client.
    - ID tokens are verified locally via google.oauth2.id_token.
    - Access tokens are verified by calling Google's tokeninfo endpoint.
    """
    request_obj = google_requests.Request()

    # First try ID token validation (JWT signed by Google).
    try:
        claims = id_token.verify_oauth2_token(token, request_obj, audience=audience)
        claims["_token_type"] = "id_token"
        return claims
    except (ValueError, google_exceptions.GoogleAuthError) as err:
        logger.info(
            "Bearer did not validate as ID token; will try access token path",
            extra={"error": str(err), "error_type": type(err).__name__},
        )

    # Fallback: access token introspection via tokeninfo endpoint.
    try:
        resp = requests.get(TOKENINFO_URL, params={"access_token": token}, timeout=GOOGLE_REQUEST_TIMEOUT)
        if resp.status_code != 200:
            logger.warning(
                "tokeninfo request failed",
                extra={"status_code": resp.status_code, "body": resp.text[:200]},
            )
            raise HTTPException(status_code=401, detail="Invalid Google token")
        data = resp.json()
        if data.get("aud") != audience:
            logger.warning(
                "Access token audience mismatch",
                extra={"expected": audience, "got": data.get("aud")},
            )
            raise HTTPException(status_code=401, detail="Invalid Google token")
        data["_token_type"] = "access_token"
        return data
    except HTTPException:
        raise
    except requests.RequestException as err:
        logger.error(
            "Access token validation request failed",
            extra={"error": str(err), "error_type": type(err).__name__},
        )
        raise HTTPException(status_code=401, detail="Invalid Google token")
    except ValueError as err:
        # JSON decode, type errors, or malformed responses.
        logger.error("Access token validation failed", extra={"error": str(err), "error_type": type(err).__name__})
        raise HTTPException(status_code=401, detail="Invalid Google token")


def require_google_auth(authorization: Optional[str] = Header(None, alias="Authorization")) -> dict:
    client_id = GOOGLE_CLIENT_ID
    if not client_id:
        raise HTTPException(status_code=500, detail="Server missing RUNTRAINER_GOOGLE_CLIENT_ID env")
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return verify_google_bearer(token, client_id)


# --- OAuth proxy endpoints for GPT Actions (Google OAuth) ---
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


@app.get("/oauth/google/auth")
def oauth_google_auth(
    state: Optional[str] = None,
    scope: Optional[str] = DEFAULT_SCOPE,
    response_type: str = "code",
    access_type: str = "offline",
    prompt: str = "consent",
    code_challenge: Optional[str] = None,
    code_challenge_method: Optional[str] = None,
):
    """Proxy to Google's OAuth authorize endpoint for the configured client."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Server missing Google OAuth env")

    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": response_type,
        "scope": scope,
        "access_type": access_type,
        "prompt": prompt,
    }
    if state:
        params["state"] = state
    if code_challenge:
        params["code_challenge"] = code_challenge
    if code_challenge_method:
        params["code_challenge_method"] = code_challenge_method

    url = requests.Request("GET", GOOGLE_AUTH_URL, params=params).prepare().url
    return RedirectResponse(url)


@app.post("/oauth/google/token")
async def oauth_google_token(request: Request):
    """Proxy to Google's token endpoint; accepts form/JSON/query and forwards with client credentials."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=500, detail="Server missing Google client credentials/env")

    # Accept form, JSON, or query fallback
    data: dict = {}
    try:
        form = await request.form()
        data = dict(form)
    except (ValueError, RuntimeError) as err:
        logger.warning("Form parse failed", extra={"error": str(err), "error_type": type(err).__name__})
        try:
            data = await request.json()
        except (json.JSONDecodeError, ValueError, RuntimeError) as err2:
            logger.warning("JSON parse failed", extra={"error": str(err2), "error_type": type(err2).__name__})
            data = {}
    # query fallback for transparency
    if not data:
        data = dict(request.query_params)

    logger.info(
        "Incoming token request",
        extra={
            "data": data,
            "data_keys": list(data.keys()),
            "query_keys": list(request.query_params.keys()),
        },
    )

    code = data.get("code") or request.query_params.get("code")
    grant_type = data.get("grant_type", "authorization_code")
    code_verifier = data.get("code_verifier")
    refresh_token = data.get("refresh_token")

    # Support refresh_token grant
    if grant_type == "refresh_token":
        if not refresh_token:
            logger.info("Refresh token request missing refresh_token", extra={"data": data})
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_request", "error_description": "refresh_token is required"},
            )
        payload = {
            "refresh_token": refresh_token,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        }
    else:
        if not code:
            logger.info("Token request missing code", extra={"data": data})
            return JSONResponse(
                status_code=400,
                content={"error": "invalid_request", "error_description": "code is required"},
            )
        payload = {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        if code_verifier:
            payload["code_verifier"] = code_verifier

    try:
        safe_payload = dict(payload)
        if "client_secret" in safe_payload:
            safe_payload["client_secret"] = "***REDACTED***"
        logger.info("Posting token request to Google", extra={"payload": safe_payload})
        resp = requests.post(
            GOOGLE_TOKEN_URL,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        logger.info(
            "Token response from Google",
            extra={"status_code": resp.status_code, "response_body": resp.text},
        )
        return JSONResponse(status_code=resp.status_code, content=resp.json())
    except requests.RequestException as err:
        logger.error("Token exchange failed (request)", exc_info=err)
        return JSONResponse(
            status_code=502,
            content={"error": "token_exchange_failed", "error_description": str(err)},
        )
    except (ValueError, json.JSONDecodeError) as err:
        logger.error("Token exchange failed (unexpected)", exc_info=err)
        return JSONResponse(
            status_code=500,
            content={"error": "token_exchange_failed", "error_description": str(err)},
        )


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    """Prometheus metrics endpoint."""
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


@app.get("/weekly-summary", dependencies=[Depends(require_google_auth)])
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


@app.get("/sleep-summary", dependencies=[Depends(require_google_auth)])
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


@app.get("/vo2-trend", dependencies=[Depends(require_google_auth)])
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


@app.get("/hrv-trend", dependencies=[Depends(require_google_auth)])
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


@app.get("/last-run", dependencies=[Depends(require_google_auth)])
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


@app.get("/recovery-score", dependencies=[Depends(require_google_auth)])
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


@app.get("/training-log", dependencies=[Depends(require_google_auth)])
def training_log(limit: int = 20, days: int = 42):
    client = get_influx_client()
    window = max(days, 1)
    query = (
        'SELECT "distance","elapsedDuration","movingDuration","averageSpeed","averageHR","calories",'
        '"activityType","totalElevationGain","trainingEffectLabel","activityId","Activity_ID","averageRunCadence","avgRunCadence",'
        '"averageCadence","avgCadence","strideLength","verticalOscillation","groundContactTime",'
        '"groundContactBalance","stanceTimePercent" '
        f'FROM "ActivitySummary" WHERE time >= now() - {window}d '
        "ORDER BY time DESC LIMIT {}".format(int(limit * 2))
    )
    result = list(client.query(query).get_points())
    # Prefer richer rows per activity_id (non-null activityType/distance/HR)
    def score(row: dict) -> int:
        s = 0
        if row.get("activityType"):
            s += 2
            if row.get("activityType") != "No Activity":
                s += 1
        for key in ("distance", "averageSpeed", "averageHR", "calories"):
            if row.get(key) is not None:
                s += 1
        return s

    best_by_id: dict[str, dict] = {}
    for row in result:
        activity_id = row.get("Activity_ID") or row.get("activityId")
        if activity_id is None:
            continue
        row_score = score(row)
        existing = best_by_id.get(str(activity_id))
        if existing is None or row_score > score(existing):
            best_by_id[str(activity_id)] = row

    deduped = []
    # Sort by time descending
    for row in sorted(best_by_id.values(), key=lambda r: r.get("time", ""), reverse=True):
        if len(deduped) >= limit:
            break
        run_type = row.get("activityType")
        entry = dict(row)
        entry["activity_id"] = row.get("Activity_ID") or row.get("activityId")
        entry["run_label"] = RUN_TYPE_LABELS.get(run_type, run_type)
        entry["average_cadence"] = get_average_cadence(client, row)
        entry["elevation_gain_m"] = first_non_null(
            get_elevation_gain(client, int(entry["activity_id"])),
            row.get("totalElevationGain"),
        )
        # Enrich elevation details
        elev = get_elevation_stats(client, int(entry["activity_id"]))
        entry["elevation_gain_m"] = first_non_null(entry.get("elevation_gain_m"), elev.get("ascent"))
        entry["elevation_loss_m"] = elev.get("descent")
        entry["elevation_min_m"] = elev.get("min")
        entry["elevation_max_m"] = elev.get("max")
        # Running dynamics
        entry["stride_length"] = first_non_null(row.get("strideLength"), entry.get("stride_length"))
        entry["vertical_oscillation"] = first_non_null(
            row.get("verticalOscillation"), entry.get("vertical_oscillation")
        )
        entry["ground_contact_time"] = first_non_null(
            row.get("groundContactTime"), entry.get("ground_contact_time")
        )
        entry["ground_contact_balance"] = first_non_null(
            row.get("groundContactBalance"), entry.get("ground_contact_balance")
        )
        entry["stance_time_percent"] = first_non_null(
            row.get("stanceTimePercent"), entry.get("stance_time_percent")
        )
        entry["max_cadence"] = get_max_cadence(client, int(entry["activity_id"]))
        # Temperature
        temps = get_temperature_stats(client, int(entry["activity_id"]))
        entry["avg_temperature"] = temps.get("avg")
        entry["min_temperature"] = temps.get("min")
        entry["max_temperature"] = temps.get("max")
        # Pace (sec per km/mile if speed present)
        speed_mps = row.get("averageSpeed")
        if speed_mps and speed_mps > 0:
            entry["avg_pace_sec_per_km"] = 1000.0 / speed_mps
            entry["avg_pace_sec_per_mile"] = 1609.34 / speed_mps
        # Drop raw or duplicate fields to avoid null duplicates
        for k in (
            "averageRunCadence",
            "avgRunCadence",
            "averageCadence",
            "avgCadence",
            "Activity_ID",
            "activityId",
            "strideLength",
            "verticalOscillation",
            "groundContactTime",
            "groundContactBalance",
            "stanceTimePercent",
        ):
            entry.pop(k, None)
        if entry.get("elevation_gain_m") is not None:
            entry.pop("totalElevationGain", None)
        deduped.append(entry)
    return {"window_days": window, "entries": deduped}


@app.get("/training-load", dependencies=[Depends(require_google_auth)])
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


@app.get("/running-dynamics", dependencies=[Depends(require_google_auth)])
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


@app.get("/recovery-time", dependencies=[Depends(require_google_auth)])
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


@app.get("/sleep-metrics", dependencies=[Depends(require_google_auth)])
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


@app.get("/stress-battery", dependencies=[Depends(require_google_auth)])
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


@app.get("/lactate-threshold", dependencies=[Depends(require_google_auth)])
def lactate_threshold():
    client = get_influx_client()
    query = (
        'SELECT LAST("heartRate") AS heart_rate, LAST("pace") AS pace '
        'FROM "LactateThreshold"'
    )
    result = list(client.query(query).get_points())
    return result[0] if result else {"heart_rate": None, "pace": None}


@app.get("/race-predictions", dependencies=[Depends(require_google_auth)])
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


@app.get("/race-schedule", dependencies=[Depends(require_google_auth)])
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
