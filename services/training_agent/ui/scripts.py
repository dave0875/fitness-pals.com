"""JavaScript blocks for training agent UI."""

from __future__ import annotations

GARMIN_ENDPOINT_BLOCK = """
        // Garmin endpoint tester
        const garminCategoryList = document.getElementById("garmin-category-list");
        const garminTestResult = document.getElementById("garmin-test-result");
        const garminCategoryRefresh = document.getElementById("garmin-category-refresh");

        async function loadGarminCategories() {
            if (!googleToken) {
                garminCategoryList.innerHTML = "<li>Sign in with Google, then click 'Load Garmin endpoints'.</li>";
                return;
            }
            const headers = { Authorization: `Bearer ${googleToken}` };
            const apiKey = apiKeyField.value.trim();
            if (apiKey) headers[API_KEY_HEADER] = apiKey;
            try {
                const res = await fetch(`${BACKEND_BASE}/api/providers/garmin/categories`, { headers });
                if (!res.ok) return;
                const cats = await res.json();
                garminCategoryList.innerHTML = "";
                if (!cats.length) {
                    garminCategoryList.innerHTML = "<li>No Garmin endpoints available</li>";
                }
                cats.forEach(cat => {
                    const li = document.createElement("li");
                    li.style.marginBottom = "8px";
                    const btn = document.createElement("button");
                    btn.textContent = "Test " + cat.key;
                    btn.style.marginRight = "6px";
                    li.appendChild(btn);
                    li.appendChild(document.createTextNode(" (" + (cat.type || "connectapi") + ")"));
                    if (cat.type === "stat") {
                        const dateInput = document.createElement("input");
                        dateInput.type = "text";
                        dateInput.value = new Date().toISOString().slice(0, 10);
                        dateInput.placeholder = "YYYY-MM-DD (date)";
                        dateInput.style.width = "130px";
                        dateInput.style.marginLeft = "6px";
                        btn.addEventListener("click", () => testGarminCategory(cat.key, null, null, null, dateInput.value, dateInput.value, cat.type, cat.per_day));
                        li.appendChild(dateInput);
                    } else {
                        const methodInput = document.createElement("input");
                        methodInput.type = "text";
                        methodInput.value = cat.method || "GET";
                        methodInput.placeholder = "method";
                        methodInput.style.width = "70px";
                        methodInput.style.marginRight = "6px";
                        const pathInput = document.createElement("input");
                        pathInput.type = "text";
                        pathInput.value = cat.path || "";
                        pathInput.placeholder = "path";
                        pathInput.style.width = "320px";
                        pathInput.style.marginRight = "6px";
                        const paramsInput = document.createElement("input");
                        paramsInput.type = "text";
                        paramsInput.value = cat.params ? JSON.stringify(cat.params) : "";
                        paramsInput.placeholder = "params JSON";
                        paramsInput.style.width = "220px";
                        paramsInput.style.marginRight = "6px";
                        const endDateInput = document.createElement("input");
                        endDateInput.type = "text";
                        endDateInput.value = new Date().toISOString().slice(0, 10);
                        endDateInput.placeholder = "YYYY-MM-DD (end)";
                        endDateInput.style.width = "130px";
                        endDateInput.style.marginRight = "6px";
                        const startDateInput = document.createElement("input");
                        startDateInput.type = "text";
                        const defaultStart = new Date();
                        defaultStart.setDate(defaultStart.getDate() - 30);
                        startDateInput.value = defaultStart.toISOString().slice(0, 10);
                        startDateInput.placeholder = "YYYY-MM-DD (start)";
                        startDateInput.style.width = "130px";
                        startDateInput.style.marginRight = "6px";
                        btn.addEventListener("click", () =>
                            testGarminCategory(
                                cat.key,
                                pathInput.value,
                                paramsInput.value,
                                methodInput.value,
                                endDateInput.value,
                                startDateInput.value,
                                cat.type,
                                cat.per_day
                            )
                        );
                        li.appendChild(document.createTextNode(cat.per_day ? " per-day" : " range"));
                        li.appendChild(methodInput);
                        li.appendChild(pathInput);
                        li.appendChild(paramsInput);
                        li.appendChild(startDateInput);
                        li.appendChild(endDateInput);
                    }
                    garminCategoryList.appendChild(li);
                });
            } catch (err) {
                console.error("loadGarminCategories failed", err);
            }
        }

        async function testGarminCategory(categoryKey, pathOverride, paramsJson, methodOverride, endDateVal, startDateVal, catType, perDay) {
            if (!googleToken) {
                showBanner("Sign in with Google first", "warn");
                return;
            }
            const headers = { "Authorization": `Bearer ${googleToken}`, "Content-Type": "application/json" };
            const apiKey = apiKeyField.value.trim();
            if (apiKey) headers[API_KEY_HEADER] = apiKey;
            let params = null;
            if (paramsJson) {
                try {
                    params = JSON.parse(paramsJson);
                } catch (_e) {}
            }
            const body = {
                category: categoryKey,
                path: pathOverride || null,
                params: params,
                method: methodOverride || null,
                date: endDateVal || null,
                start_date: startDateVal || null,
                end_date: endDateVal || null,
            };
            if (catType === "stat") {
                body.path = null;
                body.params = null;
                body.method = null;
                body.start_date = null;
            }
            try {
                const res = await fetch(`${BACKEND_BASE}/api/providers/garmin/test-category`, {
                    method: "POST",
                    headers,
                    body: JSON.stringify(body),
                });
                const data = await res.json();
                garminTestResult.textContent = JSON.stringify(data, null, 2);
                if (res.ok) {
                    showBanner("Test " + categoryKey + " succeeded", "info");
                } else {
                    showBanner("Test " + categoryKey + " failed: " + res.status, "warn");
                }
            } catch (err) {
                garminTestResult.textContent = String(err);
                showBanner("Test " + categoryKey + " failed: " + String(err), "warn");
            }
        }
        garminCategoryRefresh.addEventListener("click", loadGarminCategories);
        document.addEventListener("DOMContentLoaded", loadGarminCategories);
"""

def build_script_block(api_header_escaped: str, google_client_id: str | None) -> str:
    """Return inline script for the explorer page."""
    endpoint_block = GARMIN_ENDPOINT_BLOCK
    return f"""
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
        const garminCredSection = document.getElementById("garmin-cred-section");
        const garminScraperSection = document.getElementById("garmin-scraper-section");
        const garminFetchSelf = document.getElementById("garmin-fetch-self");
        const garminFetchAll = document.getElementById("garmin-fetch-all");
        const testRunToggle = document.getElementById("test-run-toggle");
        const reviewTestDataBtn = document.getElementById("review-test-data");
        const clearTestDataBtn = document.getElementById("clear-test-data");
        const garminLog = document.getElementById("garmin-log");
        const testSummary = document.getElementById("test-summary");
        const reportModal = document.getElementById("report-modal");
        const reportBody = document.getElementById("report-body");
        const reportClose = document.getElementById("report-close");
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
let garminMode = "unknown";

        function checkGoogleClientConfigured() {{
            if (!GOOGLE_CLIENT_ID) {{
                showBanner("Missing RUNTRAINER_GOOGLE_CLIENT_ID; Google sign-in details (email/expiry) will be unavailable until configured.", "warn");
            }}
        }}

        const BACKEND_BASE = (() => {{
            try {{
                const u = new URL(window.location.origin);
                if (u.port === "9000") u.port = "8000";
                return u.toString().replace(/\\/$/, "");
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

function escapeHtml(str) {{
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}}

function renderReportTable(reportObj) {{
    if (!reportObj || typeof reportObj !== "object") {{
        return `<pre style="margin:0; white-space:pre-wrap;">${{escapeHtml(JSON.stringify(reportObj, null, 2) || "")}}</pre>`;
    }}
    const rows = Object.entries(reportObj)
        .map(([k, v]) => {{
            const val =
                v !== null && typeof v === "object"
                    ? `<pre style="margin:0; white-space:pre-wrap;">${{escapeHtml(JSON.stringify(v, null, 2))}}</pre>`
                    : escapeHtml(v);
            return `<tr><th style="text-align:left; padding:6px 8px; vertical-align:top; font-weight:600;">${{escapeHtml(k)}}</th><td style="padding:6px 8px;">${{val}}</td></tr>`;
        }})
        .join("");
    return `<table style="width:100%; border-collapse:collapse; font-size:0.95rem;"><tbody>${{rows}}</tbody></table>`;
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
            checkGoogleClientConfigured();
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

        function applyGarminModeUI(mode) {{
            garminMode = mode || "unknown";
            // Always show both panels so scraper mode users can still mint a scraper token via username/password.
            if (garminCredSection) {{
                garminCredSection.style.display = "";
            }}
            if (garminScraperSection) {{
                garminScraperSection.style.display = "";
            }}
            if (garminCredButton) {{
                garminCredButton.disabled = false;
                garminCredButton.title = "";
            }}
            const garminReconnectBtn = document.getElementById("garmin-reconnect-btn");
            if (garminReconnectBtn) {{
                garminReconnectBtn.disabled = false;
                garminReconnectBtn.title = "";
            }}
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
            const mode = data?.mode || "unknown";
            garminTokenMeta.innerHTML = `
                <span>Status: <span class="token-status">${{status}}</span></span>
                <span>Mode: ${{mode}}</span>
                <span>Provider user id: ${{providerId}}</span>
                <span>Expires: ${{expires}}</span>
                <span>Time remaining: ${{remaining}}</span>
                <span>Refresh token: ${{refreshPresent}}</span>
            `;
            applyGarminModeUI(mode);
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
            await loadGarminCategories();
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
                const url = new URL(`${{BACKEND_BASE}}${{path}}`);
                if (testRunToggle.checked) {{
                    url.searchParams.set("test_run", "true");
                }}
                const res = await fetch(url.toString(), {{ method: "POST", headers }});
                const text = await res.text();
                let parsed = null;
                try {{
                    parsed = JSON.parse(text);
                }} catch (_e) {{}}
                appendLog(`${{label}}: ${{res.status}} ${{text.slice(0, 300)}}`);
                if (res.ok) {{
                    showBanner(`${{label}} succeeded`, "info");
                    if (parsed && parsed.report) {{
                        const tableHtml = renderReportTable(parsed.report);
                        reportBody.innerHTML = tableHtml;
                        reportModal.style.display = "flex";
                    }}
                }} else {{
                    showBanner(`${{label}} failed (${{res.status}})`, "warn");
                }}
            }} catch (err) {{
                appendLog(`${{label}} error: ${{String(err)}}`);
                showBanner(`${{label}} error`, "warn");
            }}
        }}

        async function reviewTestData() {{
            if (!googleToken) {{
                showBanner("Sign in with Google first", "warn");
                return;
            }}
            const headers = {{ Authorization: `Bearer ${{googleToken}}` }};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) headers[API_KEY_HEADER] = apiKey;
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/test-data/summary`, {{ headers }});
                const data = await res.json();
                testSummary.textContent = JSON.stringify(data, null, 2);
                if (res.ok) {{
                    showBanner("Test data summary loaded", "info");
                }} else {{
                    showBanner(`Summary failed (${{res.status}})`, "warn");
                }}
            }} catch (err) {{
                testSummary.textContent = String(err);
                showBanner(`Summary failed: ${{String(err)}}`, "warn");
            }}
        }}

        async function clearTestData() {{
            if (!googleToken) {{
                showBanner("Sign in with Google first", "warn");
                return;
            }}
            await reviewTestData();
            const snapshot = testSummary.textContent || "";
            const proceed = window.confirm(`Clear all TEST_ data?\\n\\nCurrent summary:\\n${{snapshot}}`);
            if (!proceed) return;
            const headers = {{ Authorization: `Bearer ${{googleToken}}` }};
            const apiKey = apiKeyField.value.trim();
            if (apiKey) headers[API_KEY_HEADER] = apiKey;
            try {{
                const res = await fetch(`${{BACKEND_BASE}}/api/providers/garmin/test-data/clear`, {{
                    method: "POST",
                    headers,
                }});
                const data = await res.json();
                testSummary.textContent = JSON.stringify(data, null, 2);
                if (res.ok) {{
                    showBanner("Test data cleared", "info");
                }} else {{
                    showBanner(`Clear failed (${{res.status}})`, "warn");
                }}
            }} catch (err) {{
                showBanner(`Clear failed: ${{String(err)}}`, "warn");
            }}
        }}

        garminFetchSelf.addEventListener("click", () => fetchGarmin("/api/providers/garmin/fetch", "Fetch current user"));
        garminFetchAll.addEventListener("click", () => fetchGarmin("/api/providers/garmin/fetch/all", "Batch fetch all"));
        reviewTestDataBtn.addEventListener("click", reviewTestData);
        clearTestDataBtn.addEventListener("click", clearTestData);
        reportClose.addEventListener("click", () => {{
            reportModal.style.display = "none";
        }});
        reportModal.addEventListener("click", (e) => {{
            if (e.target === reportModal) reportModal.style.display = "none";
        }});

        {endpoint_block}
    
        """
