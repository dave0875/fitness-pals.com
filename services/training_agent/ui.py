# ruff: noqa: E501
# pylint: disable=line-too-long
"""HTML harness for exercising training agent endpoints."""

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


def render_field(param: ActionParam) -> str:
    """Render a single harness form field."""
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


def _render_action_card(spec: ActionSpec) -> str:
    """Build the markup for a single action card."""
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
    return f"""
    <section class="card">
        <header>
            <h2>{name}</h2>
            <code>GET {path}</code>
        </header>
        <p class="description">{description}</p>
        {form_html}
    </section>
    """


def render_action_index(
    base_url: str, api_key: str | None, google_client_id: str | None
) -> str:
    """Render the HTML action explorer page for the training agent harness."""
    api_header_escaped = html.escape(API_KEY_NAME)
    cards_html = "\n".join(_render_action_card(spec) for spec in ACTIONS)
    escaped_base = html.escape(base_url)
    api_key_value = html.escape(api_key or "")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <title>Garmin Training API Explorer</title>
    <script src="https://accounts.google.com/gsi/client" async defer></script>
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
        .status-banner {{
            display: none;
            margin-bottom: 1rem;
            padding: 0.75rem;
            border-radius: 0.5rem;
            background: rgba(236, 72, 153, 0.1);
            border: 1px solid rgba(236, 72, 153, 0.4);
        }}
        .status-banner.visible {{
            display: block;
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
        .callout {{
            margin-bottom: 1.5rem;
            background: rgba(15, 23, 42, 0.85);
            border-radius: 0.75rem;
            border: 1px solid rgba(56, 189, 248, 0.2);
            padding: 1rem;
        }}
        .callout-content {{
            display: flex;
            gap: 2rem;
            flex-wrap: wrap;
            align-items: flex-start;
        }}
        .auth-status {{
            margin-top: 0.5rem;
            font-size: 0.9rem;
            color: #a5b4fc;
        }}
    </style>
</head>
<body>
    <h1>Garmin Training API Explorer</h1>
    <div id="status-banner" class="status-banner"></div>
    <section class="callout">
        <div class="callout-content">
            <div>
                <h2>Authorization</h2>
                <p>Sign in with Google to automatically add a bearer token to requests.</p>
                <div id="google-login"></div>
                <button id="google-login-btn" type="button">Sign in with Google</button>
                <div id="auth-status" class="auth-status">Not signed in</div>
                <button id="sign-out-button" style="display:none;">Sign out</button>
            </div>
            <div class="api-key-input">
                <label for="api-key-field">Optional API key (x-api-key header)</label>
                <input id="api-key-field" type="password" value="{api_key_value}" placeholder="Enter API key">
                <small>Example curl:</small>
                <pre>curl -H "{api_header_escaped}: &lt;your key&gt;" {escaped_base}/weekly-summary</pre>
            </div>
        </div>
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
        const GOOGLE_CLIENT_ID = "{google_client_id or ''}";
        const API_KEY_HEADER = "{api_header_escaped}";
        const apiKeyField = document.getElementById("api-key-field");
        const googleLoginButton = document.getElementById("google-login-btn");
        const responseEndpoint = document.getElementById("response-endpoint");
        const responseStatus = document.getElementById("response-status");
        const responseBody = document.getElementById("response-body");
        const authStatus = document.getElementById("auth-status");
        const statusBanner = document.getElementById("status-banner");
        const signOutButton = document.getElementById("sign-out-button");
        let googleToken = null;

        const isLocalhost =
            window.location.hostname === "localhost" ||
            window.location.hostname === "127.0.0.1";
        const REDIRECT_BASE = isLocalhost ? "http://localhost:9000" : window.location.origin;

let bannerTimeout;
function showBanner(message, level = "warn") {{
    statusBanner.textContent = message;
    statusBanner.className = `status-banner visible ${{level}}`;
    clearTimeout(bannerTimeout);
    bannerTimeout = setTimeout(() => {{
        statusBanner.classList.remove("visible");
    }}, 4000);
}}

        function parseJwt(token) {{
            try {{
                const base64 = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
                const jsonPayload = decodeURIComponent(
                    atob(base64)
                        .split("")
                        .map((c) => "%" + ("00" + c.charCodeAt(0).toString(16)).slice(-2))
                        .join("")
                );
                return JSON.parse(jsonPayload);
            }} catch (err) {{
                return {{}};
            }}
        }}

        function buildGoogleAuthUrl() {{
            const base = REDIRECT_BASE;
            return `${{base}}/oauth/google/auth?redirect_uri=${{encodeURIComponent(base + "/oauth/google/callback")}}`;
        }}

        function updateAuthDisplay() {{
            if (googleToken) {{
                const payload = parseJwt(googleToken);
                authStatus.textContent = payload.email ? `Signed in as ${{payload.email}}` : "Signed in";
                signOutButton.style.display = "inline-flex";
            }} else {{
                authStatus.textContent = "Not signed in";
                signOutButton.style.display = "none";
            }}
        }}

        function handleCredentialResponse(response) {{
            googleToken = response.credential;
            showBanner("Google sign-in successful", "info");
            updateAuthDisplay();
        }}

        window.initializeGoogle = function () {{
            if (!GOOGLE_CLIENT_ID) {{
                showBanner("Server missing Google client id; Google sign-in unavailable");
                return;
            }}
            const loader = () => {{
                if (window.google && window.google.accounts && window.google.accounts.id) {{
                    window.google.accounts.id.initialize({{
                        client_id: GOOGLE_CLIENT_ID,
                        callback: handleCredentialResponse,
                    }});
                    window.google.accounts.id.renderButton(document.getElementById("google-login"), {{
                        theme: "filled_black",
                        size: "large",
                        text: "signin_with",
                        shape: "pill",
                    }});
                }} else {{
                    setTimeout(loader, 300);
                }}
            }};
            loader();
        }};

        window.onload = () => {{
            updateAuthDisplay();
            initializeGoogle();
        }};

        signOutButton.addEventListener("click", () => {{
            googleToken = null;
            if (window.google && window.google.accounts && window.google.accounts.id) {{
                window.google.accounts.id.disableAutoSelect();
            }}
            updateAuthDisplay();
            showBanner("Signed out", "info");
        }});

        googleLoginButton.addEventListener("click", () => {{
            window.location.href = buildGoogleAuthUrl();
        }});

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
            if (googleToken) {{
                headers["Authorization"] = `Bearer ${{googleToken}}`;
            }} else {{
                showBanner("Sign in with Google to call protected endpoints");
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
        render_action_index(
            str(request.base_url).rstrip("/"),
            os.environ.get("TRAINING_API_KEY"),
            os.environ.get("RUNTRAINER_GOOGLE_CLIENT_ID")
            or os.environ.get("GOOGLE_CLIENT_ID"),
        )
    )
