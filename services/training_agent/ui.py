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
        .token-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
            gap: 1rem;
        }}
        .token-card {{
            background: rgba(30, 41, 59, 0.9);
            border: 1px solid rgba(56, 189, 248, 0.3);
            border-radius: 0.75rem;
            padding: 1rem;
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }}
        .token-card h3 {{
            margin: 0;
            font-size: 1.1rem;
            color: #38bdf8;
        }}
        .token-meta {{
            font-size: 0.9rem;
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
        }}
        .token-actions {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}
        .token-actions button {{
            background: rgba(59, 130, 246, 0.8);
            border: none;
            padding: 0.4rem 0.8rem;
            border-radius: 0.5rem;
            cursor: pointer;
        }}
        .token-status {{
            font-weight: bold;
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
    <section class="callout">
        <div class="token-grid">
            <div class="token-card" id="google-token-card">
                <h3>Google Token</h3>
                <div class="token-meta" id="google-token-meta">
                    <span>Status: <span class="token-status">Unknown</span></span>
                    <span>Email: –</span>
                    <span>Expires: –</span>
                    <span>Time remaining: –</span>
                </div>
                <div class="token-actions">
                    <button type="button" id="google-refresh-btn">Refresh Google token</button>
                </div>
            </div>
            <div class="token-card" id="garmin-token-card">
                <h3>Garmin Token</h3>
                <div class="token-meta" id="garmin-token-meta">
                    <span>Status: <span class="token-status">Unknown</span></span>
                    <span>Provider user id: –</span>
                    <span>Expires: –</span>
                    <span>Time remaining: –</span>
                    <span>Refresh token: –</span>
                </div>
                <div class="token-actions">
                    <button type="button" id="garmin-refresh-btn">Refresh Garmin token</button>
                    <button type="button" id="garmin-reconnect-btn">Reconnect Garmin</button>
                </div>
            </div>
        </div>
    </section>
    <section class="callout">
        <div class="callout-content">
            <div class="api-key-input">
                <h2>Garmin credentials (ephemeral)</h2>
                <p>Enter your Garmin username/password to generate tokens. Credentials are never stored.</p>
                <label for="garmin-username-field">Garmin username</label>
                <input id="garmin-username-field" type="text" placeholder="username@email.com" />
                <label for="garmin-password-field">Garmin password</label>
                <input id="garmin-password-field" type="password" placeholder="Password" />
                <label for="garmin-cred-expires-field">Optional expires_at (ISO8601)</label>
                <input id="garmin-cred-expires-field" type="text" placeholder="e.g., 2025-12-31T23:59:59Z" />
                <button id="garmin-cred-button" type="button">Generate Garmin token</button>
            </div>
            <div class="api-key-input">
                <h2>Garmin scraper token (manual)</h2>
                <p>Paste a scraper access token gathered via your client-side helper.</p>
                <label for="garmin-token-field">Scraper access token</label>
                <input id="garmin-token-field" type="password" placeholder="Paste scraper access token" />
                <label for="garmin-expires-field">Optional expires_at (ISO8601)</label>
                <input id="garmin-expires-field" type="text" placeholder="e.g., 2025-12-31T23:59:59Z" />
                <label for="garmin-token-secret-field">Optional token secret</label>
                <input id="garmin-token-secret-field" type="password" placeholder="OAuth1 token secret" />
                <button id="garmin-token-button" type="button">Save Garmin token</button>
                <small><a href="https://example.com/garmin-helper" target="_blank" rel="noopener noreferrer">Open helper to generate token</a></small>
            </div>
        </div>
    </section>
    <section class="callout">
        <div class="callout-content">
            <div class="api-key-input">
                <h2>Garmin ingestion</h2>
                <p>Trigger Garmin fetch jobs and view responses.</p>
                <div class="grid">
                    <button id="garmin-fetch-self" type="button">Fetch current user</button>
                    <button id="garmin-fetch-all" type="button">Batch fetch all users</button>
                </div>
                <pre id="garmin-log" style="margin-top: 10px; max-height: 200px; overflow: auto; background: #0d2038; padding: 10px; border-radius: 4px;"></pre>
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
        const garminTokenField = document.getElementById("garmin-token-field");
        const garminExpiresField = document.getElementById("garmin-expires-field");
        const garminTokenSecretField = document.getElementById("garmin-token-secret-field");
        const garminTokenButton = document.getElementById("garmin-token-button");
        const garminUsernameField = document.getElementById("garmin-username-field");
        const garminPasswordField = document.getElementById("garmin-password-field");
        const garminCredExpiresField = document.getElementById("garmin-cred-expires-field");
        const garminCredButton = document.getElementById("garmin-cred-button");
        const garminFetchSelf = document.getElementById("garmin-fetch-self");
        const garminFetchAll = document.getElementById("garmin-fetch-all");
        const garminLog = document.getElementById("garmin-log");
        const googleTokenMeta = document.getElementById("google-token-meta");
        const garminTokenMeta = document.getElementById("garmin-token-meta");
        const googleRefreshButton = document.getElementById("google-refresh-btn");
        const garminRefreshButton = document.getElementById("garmin-refresh-btn");
        const garminReconnectButton = document.getElementById("garmin-reconnect-btn");
        const googleLoginButton = document.getElementById("google-login-btn");
        const responseEndpoint = document.getElementById("response-endpoint");
        const responseStatus = document.getElementById("response-status");
        const responseBody = document.getElementById("response-body");
        const authStatus = document.getElementById("auth-status");
        const statusBanner = document.getElementById("status-banner");
        const signOutButton = document.getElementById("sign-out-button");
        let googleToken = null;

        const BACKEND_BASE = (() => {{
            try {{
                const u = new URL(window.location.origin);
                if (u.port === "9000") u.port = "8000";
                return u.toString().replace(/\/$/, "");
            }} catch (_err) {{
                return window.location.origin;
            }}
        }})();

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
            refreshTokenStatuses();
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
            refreshTokenStatuses();
        }};

        signOutButton.addEventListener("click", () => {{
            googleToken = null;
            if (window.google && window.google.accounts && window.google.accounts.id) {{
                window.google.accounts.id.disableAutoSelect();
            }}
            updateAuthDisplay();
            showBanner("Signed out", "info");
            refreshTokenStatuses();
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

        function formatDuration(seconds) {{
            if (seconds == null) {{
                return "–";
            }}
            const s = Math.max(0, seconds);
            const mins = Math.floor(s / 60);
            const secs = s % 60;
            if (mins <= 0) {{
                return `${{secs}}s`;
            }}
            return `${{mins}}m ${{secs}}s`;
        }}

        function renderGoogleTokenStatus(data) {{
            const status = data?.status || (googleToken ? "active" : "unknown");
            const email = data?.user_email || "–";
            const expires = data?.expires_at || "–";
            const remaining = formatDuration(data?.seconds_remaining);
            googleTokenMeta.innerHTML = `
                <span>Status: <span class="token-status">${{status}}</span></span>
                <span>Email: ${{email}}</span>
                <span>Expires: ${{expires}}</span>
                <span>Time remaining: ${{remaining}}</span>
            `;
        }}

        function renderGarminTokenStatus(data) {{
            const status = data?.status || "missing";
            const providerId = data?.provider_user_id || "–";
            const expires = data?.expires_at || "–";
            const remaining = formatDuration(data?.seconds_remaining);
            const refreshPresent = data?.refresh_token_present ? "Yes" : "No";
            garminTokenMeta.innerHTML = `
                <span>Status: <span class="token-status">${{status}}</span></span>
                <span>Provider user id: ${{providerId}}</span>
                <span>Expires: ${{expires}}</span>
                <span>Time remaining: ${{remaining}}</span>
                <span>Refresh token: ${{refreshPresent}}</span>
            `;
        }}

        async function fetchGoogleTokenStatus() {{
            if (!googleToken) {{
                renderGoogleTokenStatus(null);
                return;
            }}
            const headers = {{"Authorization": `Bearer ${{googleToken}}`}};
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/auth/token-status/google`, {{
                    headers,
                }});
                if (res.ok) {{
                    const data = await res.json();
                    renderGoogleTokenStatus(data);
                }} else {{
                    renderGoogleTokenStatus(null);
                }}
            }} catch (_err) {{
                renderGoogleTokenStatus(null);
            }}
        }}

        async function fetchGarminTokenStatus() {{
            if (!googleToken) {{
                renderGarminTokenStatus(null);
                return;
            }}
            const headers = {{"Authorization": `Bearer ${{googleToken}}`}};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) {{
                headers[API_KEY_HEADER] = apiKey;
            }}
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/token-status`, {{
                    headers,
                }});
                if (res.ok) {{
                    const data = await res.json();
                    renderGarminTokenStatus(data);
                }} else {{
                    renderGarminTokenStatus(null);
                }}
            }} catch (_err) {{
                renderGarminTokenStatus(null);
            }}
        }}

        async function refreshTokenStatuses() {{
            await Promise.all([fetchGoogleTokenStatus(), fetchGarminTokenStatus()]);
        }}

        setInterval(refreshTokenStatuses, 30000);

        async function saveGarminScraperToken() {{
            const token = garminTokenField.value.trim();
            const expires = garminExpiresField.value.trim();
            const secret = garminTokenSecretField.value.trim();
            if (!token) {{
                showBanner("Scraper token is required", "warn");
                return;
            }}
            const headers = {{"Content-Type": "application/json"}};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) {{
                headers[API_KEY_HEADER] = apiKey;
            }}
            if (googleToken) {{
                headers["Authorization"] = `Bearer ${{googleToken}}`;
            }} else {{
                showBanner("Sign in with Google to save the token", "warn");
                return;
            }}
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/scraper/token`, {{
                    method: "POST",
                    headers,
                    body: JSON.stringify({{
                        scraper_access_token: token,
                        expires_at: expires || null,
                        token_secret: secret || null,
                    }}),
                }});
                if (res.ok) {{
                    showBanner("Garmin scraper token saved", "info");
                    garminTokenField.value = "";
                    garminExpiresField.value = "";
                    garminTokenSecretField.value = "";
                    refreshTokenStatuses();
                }} else {{
                    const text = await res.text();
                    showBanner(`Failed to save token: ${{res.status}} ${{text.slice(0,120)}}`);
                }}
            }} catch (err) {{
                showBanner(`Failed to save token: ${{String(err)}}`);
            }}
        }}

        async function acquireGarminToken() {{
            const username = garminUsernameField.value.trim();
            const password = garminPasswordField.value.trim();
            const expires = garminCredExpiresField.value.trim();
            if (!username || !password) {{
                showBanner("Username and password required for acquisition", "warn");
                return;
            }}
            if (!googleToken) {{
                showBanner("Sign in with Google first", "warn");
                return;
            }}
            const headers = {{ "Content-Type": "application/json", "Authorization": `Bearer ${{googleToken}}` }};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) {{
                headers[API_KEY_HEADER] = apiKey;
            }}
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/acquire-token`, {{
                    method: "POST",
                    headers,
                    body: JSON.stringify({{
                        username,
                        password,
                        expires_at: expires || null,
                    }}),
                }});
                garminUsernameField.value = "";
                garminPasswordField.value = "";
                garminCredExpiresField.value = "";
                if (res.ok) {{
                    showBanner("Garmin token acquired", "info");
                    refreshTokenStatuses();
                }} else {{
                    const text = await res.text();
                    showBanner(`Acquire failed: ${{res.status}}`, "warn");
                    console.error(text.slice(0,200));
                }}
            }} catch (err) {{
                showBanner(`Acquire failed: ${{String(err)}}`);
            }}
        }}

        async function refreshGarminToken() {{
            if (!googleToken) {{
                showBanner("Sign in with Google first", "warn");
                return;
            }}
            const headers = {{ "Authorization": `Bearer ${{googleToken}}` }};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) {{
                headers[API_KEY_HEADER] = apiKey;
            }}
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/refresh-token`, {{
                    method: "POST",
                    headers,
                }});
                if (res.ok) {{
                    showBanner("Garmin token refreshed", "info");
                    refreshTokenStatuses();
                }} else {{
                    const text = await res.text();
                    showBanner(`Refresh failed: ${{res.status}}`, "warn");
                    console.error(text.slice(0,200));
                }}
            }} catch (err) {{
                showBanner(`Refresh failed: ${{String(err)}}`);
            }}
        }}

        garminTokenButton.addEventListener("click", saveGarminScraperToken);
        garminCredButton.addEventListener("click", acquireGarminToken);
        googleRefreshButton.addEventListener("click", () => {{
            if (window.google?.accounts?.id) {{
                window.google.accounts.id.prompt();
            }} else {{
                showBanner("Google prompt unavailable", "warn");
            }}
        }});
        garminRefreshButton.addEventListener("click", refreshGarminToken);
        garminReconnectButton.addEventListener("click", () => {{
            window.open(`${{BACKEND_BASE}}/api/providers/garmin/login`, "_blank");
        }});
        function appendLog(line) {{
            const ts = new Date().toISOString();
            garminLog.textContent = `${{ts}} ${{line}}\n${{garminLog.textContent}}`.slice(0, 4000);
        }}
        async function fetchGarmin(path, label) {{
            if (!googleToken) {{
                showBanner("Sign in with Google first", "warn");
                return;
            }}
            const headers = {{ Authorization: `Bearer ${{googleToken}}` }};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) {{
                headers[API_KEY_HEADER] = apiKey;
            }}
            try {{
                const res = await fetch(`${{BACKEND_BASE}}${{path}}`, {{ method: "POST", headers }});
                const text = await res.text();
                appendLog(`${{label}}: ${{res.status}} ${{text.slice(0, 300)}}`);
                if (res.ok) {{
                    showBanner(`${{label}} succeeded`, "info");
                }} else {{
                    showBanner(`${{label}} failed (${{res.status}})`, "warn");
                }}
            }} catch (err) {{
                appendLog(`${{label}} error: ${{String(err)}}`);
                showBanner(`${{label}} error`, "warn");
            }}
        }}
        garminFetchSelf.addEventListener("click", () => fetchGarmin("/api/providers/garmin/fetch", "Fetch current user"));
        garminFetchAll.addEventListener("click", () => fetchGarmin("/api/providers/garmin/fetch/all", "Batch fetch all"));
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


@router.get("/garmin-helper", response_class=HTMLResponse)
def garmin_helper() -> HTMLResponse:
    """Lightweight helper page for posting a scraper access token."""
    html_doc = """
    <!doctype html>
    <html>
    <head><title>Garmin Scraper Token Helper</title></head>
    <body style="font-family: sans-serif; max-width: 640px; margin: 2rem auto;">
      <h1>Garmin Scraper Token</h1>
      <p>Use your client-side helper to obtain a scraper access token, then submit it here. No usernames or passwords are collected.</p>
      <label>Scraper access token<br><input id="token" type="password" style="width:100%%;"></label><br><br>
      <label>Optional expires_at (ISO8601)<br><input id="expires" type="text" placeholder="2025-12-31T23:59:59Z" style="width:100%%;"></label><br><br>
      <button id="save">Save token</button>
      <div id="msg" style="margin-top:1rem;"></div>
      <script>
        const BACKEND_BASE = (() => {
          try {
            const u = new URL(window.location.origin);
            if (u.port === "9000") u.port = "8000";
            return u.toString().replace(/\\/$/, "");
          } catch (_err) {
            return window.location.origin;
          }
        })();
        async function save() {{
          const token = document.getElementById("token").value.trim();
          const expires = document.getElementById("expires").value.trim();
          const msg = document.getElementById("msg");
          if (!token) {{
            msg.textContent = "Token is required.";
            msg.style.color = "red";
            return;
          }}
          try {{
            const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/scraper/token`, {{
              method: "POST",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ scraper_access_token: token, expires_at: expires || null }})
            }});
            if (res.ok) {{
              msg.textContent = "Token saved.";
              msg.style.color = "green";
              document.getElementById("token").value = "";
              document.getElementById("expires").value = "";
            }} else {{
              const text = await res.text();
              msg.textContent = `Save failed: ${{res.status}}`;
              msg.style.color = "red";
              console.error(text.slice(0,200));
            }}
          }} catch (err) {{
            msg.textContent = `Save failed: ${{String(err)}}`;
            msg.style.color = "red";
          }}
        }}
        document.getElementById("save").addEventListener("click", save);
      </script>
    </body>
    </html>
    """
    return HTMLResponse(html_doc)
