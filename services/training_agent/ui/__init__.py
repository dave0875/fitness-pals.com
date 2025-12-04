# ruff: noqa: E501
# pylint: disable=line-too-long
"""HTML harness for exercising training agent endpoints."""

from __future__ import annotations

import html
import os

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from .base import ACTIONS, API_KEY_NAME, render_action_card
from .scripts import build_script_block

router = APIRouter()


def render_action_index(
    base_url: str, api_key: str | None, google_client_id: str | None
) -> str:
    """Render the HTML action explorer page for the training agent harness."""
    api_header_escaped = html.escape(API_KEY_NAME)
    cards_html = "\n".join(render_action_card(spec) for spec in ACTIONS)
    escaped_base = html.escape(base_url)
    api_key_value = html.escape(api_key or "")
    script_block = build_script_block(api_header_escaped, google_client_id)
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
            <div class="api-key-input" id="garmin-cred-section">
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
            <div class="api-key-input" id="garmin-scraper-section">
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
                    <label style="display:flex;align-items:center;gap:6px;margin-left:8px;">
                        <input id="test-run-toggle" type="checkbox" />
                        Test run (tag Influx as TEST_*)
                    </label>
                    <button id="review-test-data" type="button">Review test data</button>
                    <button id="clear-test-data" type="button">Clear test data</button>
                </div>
                <pre id="test-summary" style="margin-top:10px; max-height:140px; overflow:auto; background:#0d2038; padding:10px; border-radius:4px;"></pre>
                <pre id="garmin-log" style="margin-top: 10px; max-height: 200px; overflow: auto; background: #0d2038; padding: 10px; border-radius: 4px;"></pre>
            </div>
        </div>
    </section>
    <section class="callout">
        <div class="callout-content">
            <details id="garmin-endpoint-panel">
                <summary><strong>Garmin endpoint tester</strong> — expand to probe individual Garmin APIs with your current token.</summary>
                <p style="margin-top:10px;">Each button issues a live call against the selected Garmin endpoint using the stored token. Results are not written to Influx.</p>
                <div style="margin: 8px 0;">
                    <button id="garmin-category-refresh" type="button">Load Garmin endpoints</button>
                </div>
                <ul id="garmin-category-list" style="list-style: none; padding-left: 0;"></ul>
                <pre id="garmin-test-result" style="max-height:240px; overflow:auto; background:#0d2038; padding:10px; border-radius:4px;"></pre>
            </details>
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
    <div id="report-modal" style="display:none; position:fixed; inset:0; background:rgba(0,0,0,0.6); z-index:9999; align-items:center; justify-content:center;">
        <div style="background:#0b1c30; color:#e2e8f0; padding:16px; border-radius:8px; max-width:720px; width:90%; max-height:80%; overflow:auto; box-shadow:0 10px 30px rgba(0,0,0,0.4);">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <h3 style="margin:0; font-size:1.1rem;">Ingest Report</h3>
                <button id="report-close" type="button" style="background:#1f3655; color:#e2e8f0; border:none; padding:6px 10px; border-radius:4px; cursor:pointer;">Close</button>
            </div>
            <div id="report-body" style="background:#0d2038; padding:10px; border-radius:4px; white-space:normal; overflow:auto;"></div>
        </div>
    </div>
        <script>
{script_block}
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
