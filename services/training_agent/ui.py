# ruff: noqa: E501
# pylint: disable=line-too-long
from __future__ import annotations

import html
import os
from typing import List

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

ActionParam = dict[str, object]
ActionSpec = dict[str, object]
API_KEY_NAME = os.environ.get("TRAINING_API_KEY_HEADER", "x-api-key")

router = APIRouter()

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
    """Render the HTML action explorer page for the training agent harness."""
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


@router.get("/", response_class=HTMLResponse)
def action_index(request: Request) -> HTMLResponse:
    """Serve the action explorer UI."""
    return HTMLResponse(
        render_action_index(str(request.base_url).rstrip("/"), os.environ.get("TRAINING_API_KEY"))
    )
