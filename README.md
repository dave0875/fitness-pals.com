# fitness-pals

This repo drives my personal fitness stack. It keeps my code (backend, frontend, training agent) separate from the upstream [garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) project. Garmin data collection, InfluxDB, and Grafana dashboards now come entirely from published container images so I can pull upstream updates without merging their source into this repo.

## What stays in this repo
- My services (see `services/`, `backend/`, `frontend/`).
- Compose wiring for dependent services (InfluxDB, Grafana, ngrok, training-agent).
- Local environment and secrets files (not committed).

## What moved out
- Vendored garmin-grafana source, dashboards, and provisioning files have been removed. The stack now uses the upstream image `ghcr.io/arpanghosh8453/garmin-fetch-data:latest` directly. Grafana dashboards can be imported from Grafana Cloud (code `23245`) or the upstream repo if desired, but are no longer stored here.

## Running the stack
The repository-owned backend, worker, training-agent, and CI/deployment scripts use
Python 3.14. The `.python-version` file configures compatible local version managers;
the deployable services use the matching official slim image.

Create a `.env` with the required variables (examples from the upstream docs still apply: InfluxDB credentials, Garmin Connect auth, Grafana admin, tunnel token, etc.). Production uses the private Compose network and publishes no application or datastore ports on the host:

```bash
docker compose up -d
```

For local development, add the development override. Its debug ports bind only to
the loopback interface and can be changed with the corresponding `*_HOST_PORT`
variables:

```bash
docker compose -f compose.yml -f compose.dev.yml up -d
```

Key services:
- `garmin-fetch-data`: pulls data from Garmin into InfluxDB via the upstream image (no local build).
- `influxdb`: time-series database for metrics.
- `grafana`: visualization. Import the Garmin dashboard by ID `23245` or from the upstream repo when needed.
- `training-agent`: your local service (built from `services/training_agent`).
- `ngrok`: optional tunnel for remote access.

## Environment configuration (what each variable does and where to get it)
- `RUNTRAINER_JWT_SECRET`: random string used to sign app-issued JWTs (generate with `openssl rand -hex 32`).
- `RUNTRAINER_JWT_ISSUER` / `RUNTRAINER_JWT_ACCESS_AUDIENCE` / `RUNTRAINER_JWT_REFRESH_AUDIENCE`: stable app-token trust boundary. Access and refresh audiences must remain distinct across every backend/worker instance.
- `RUNTRAINER_WEB_OIDC_ISSUER` / `RUNTRAINER_WEB_OIDC_CLIENT_ID` / `RUNTRAINER_WEB_OIDC_CLIENT_SECRET` / `RUNTRAINER_WEB_OIDC_REDIRECT_URI`: Authentik OIDC client for the website. Point the issuer at the Authentik application slug for the web app (for example `https://auth.your-domain.com/application/o/fitness-pals-web/`) and set the callback to `https://your-domain.com/auth/callback`.
- `RUNTRAINER_OIDC_ISSUER` / `RUNTRAINER_OIDC_CLIENT_ID` / `RUNTRAINER_OIDC_CLIENT_SECRET`: Authentik OIDC client for the GPT/training-agent integration. Keep this as a separate Authentik application even though it resolves to the same upstream Google identity.
- `AUTHENTIK_GOOGLE_CLIENT_ID` / `AUTHENTIK_GOOGLE_CLIENT_SECRET`: Google OAuth client used only by Authentik as the upstream identity source. Store these only in the deployment secrets file; they are needed when creating or rotating the source, while routine reconciliation preserves credentials already stored in Authentik. The bootstrap never inherits the direct-app fallback pair.
- `RUNTRAINER_GOOGLE_FALLBACK_ENABLED` / `RUNTRAINER_GOOGLE_CLIENT_ID` / `RUNTRAINER_GOOGLE_CLIENT_SECRET` / `RUNTRAINER_GOOGLE_REDIRECT_URI`: rollback-only direct Google OAuth configuration. The fallback is disabled by default and registers only when the enable flag is `true` and the full credential/redirect set is present.

- `RUNTRAINER_MICROSOFT_CLIENT_ID` / `RUNTRAINER_MICROSOFT_CLIENT_SECRET` / `RUNTRAINER_MICROSOFT_REDIRECT_URI`: App registration in Azure AD (Entra); create a Web redirect URI; copy the Application (client) ID and client secret.
- `RUNTRAINER_APPLE_CLIENT_ID` / `RUNTRAINER_APPLE_CLIENT_SECRET` / `RUNTRAINER_APPLE_REDIRECT_URI`: Apple Sign in client; create a Services ID in Apple Developer, set the redirect URI, generate a client secret (JWT signed with your key) and supply here.
- `RUNTRAINER_DATABASE_URL`: SQLAlchemy connection string to Postgres (e.g., `postgresql://user:pass@host:5432/runtrainer`).
- `RUNTRAINER_FERNET_KEY`: key used to encrypt user/provider tokens; generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `RUNTRAINER_INFLUX_URL`: operator-managed Influx endpoint used only for optional timeseries mirroring. Athletes cannot view or change it. `RUNTRAINER_INFLUX_DEFAULT_URL` remains a temporary deployment alias.
- `RUNTRAINER_OPENAI_API_KEY`: API key for GPT-based coaching responses (from platform.openai.com).
- `RUNTRAINER_ACCESS_TOKEN_EXP_MINUTES` / `RUNTRAINER_REFRESH_TOKEN_EXP_DAYS`: JWT lifetimes; leave defaults unless you need to shorten/extend sessions.

Deploying this boundary intentionally invalidates legacy app access and refresh cookies. Existing users must authenticate again; there is no permissive legacy decoder or refresh-session backfill.
- `RUNTRAINER_DEDUPE_START_TIME_TOLERANCE_SECONDS` / `RUNTRAINER_DEDUPE_DURATION_TOLERANCE_RATIO` / `RUNTRAINER_DEDUPE_DISTANCE_TOLERANCE_RATIO`: tweak dedup tolerances; defaults are ±90s start, ±10% duration, ±3% distance.
- `INFLUXDB_HOST` / `INFLUXDB_PORT` / `INFLUXDB_USERNAME` / `INFLUXDB_PASSWORD` / `INFLUXDB_DATABASE`: InfluxDB connection for training-agent and garmin-fetch-data.
- `GARMINCONNECT_EMAIL` / `GARMINCONNECT_BASE64_PASSWORD`: legacy single Garmin account for garmin-fetch-data; avoid for multi-tenant and move to per-user provider connections instead.
- `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD`: Grafana admin login.
- `GRAFANA_OIDC_CLIENT_ID` / `GRAFANA_OIDC_CLIENT_SECRET`: dedicated confidential Authentik client for Grafana SSO. Automated dev deploys receive these from the repository secrets `DEV_GRAFANA_OIDC_CLIENT_ID` / `DEV_GRAFANA_OIDC_CLIENT_SECRET`; production receives them from same-named secrets in the `production` GitHub environment. Local operators can still provide the pair through an untracked env file. The Authentik bootstrap owns the matching provider/application.
- `CLOUDFLARE_TUNNEL_TOKEN`: Cloudflare tunnel token to expose services.
- `CLOUDFLARE_SMOKE_URLS`: comma- or newline-delimited public URLs that should succeed through the Cloudflare tunnel after deploy, for example `https://api.fitness-pals.com/ready` and `https://grafana.fitness-pals.com/api/health`.
- `CLOUDFLARE_SMOKE_TIMEOUT_SECONDS`: optional external ingress smoke timeout; defaults to `90`.
- `TRAINING_API_KEY`: key used by the training-agent harness.
- `BOT_GITHUB_TOKEN`: token for any bot operations (keep out of commits).

### Garmin archive sources

Signed-in athletes can authorize the same Google account for read-only Drive access. Create one
platform-owned Google OAuth web client with this exact authorized redirect URI:

```text
https://fitness-pals.com/api/archive-imports/google-drive/callback
```

Register that shared app through the administrator-only provider-app API so its client secret is
encrypted in Postgres rather than stored in an environment file:

```json
{
  "provider": "google_drive",
  "display_name": "Google Drive",
  "client_id": "...",
  "client_secret": "...",
  "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
  "token_url": "https://oauth2.googleapis.com/token",
  "redirect_uri": "https://fitness-pals.com/api/archive-imports/google-drive/callback",
  "scopes": "openid email https://www.googleapis.com/auth/drive.readonly"
}
```

The app requests `drive.readonly`, verifies that Google's returned email matches the signed-in
athlete, and stores each athlete's access and refresh tokens separately and encrypted in
`user_provider_tokens`. Imports search that Drive recursively from its root for FIT files, ZIP
exports, and Garmin summarized-activity JSON. The worker refreshes expiring grants and saves each
refreshed token encrypted. The shared OAuth app registration lives in `provider_apps`; it is not a
user grant and is never exposed by the provider API.

The older operator-assigned service-account mode remains available as a fallback. Share each
source folder read-only with the configured service account, then set:

```dotenv
RUNTRAINER_GOOGLE_DRIVE_ARCHIVE_SOURCES_JSON={"athlete@example.com":"drive-folder-id"}
RUNTRAINER_GOOGLE_DRIVE_SERVICE_ACCOUNT_FILE=/run/secrets/google-drive-service-account.json
```

`RUNTRAINER_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` may be used instead when the secret store injects
JSON directly. The worker recursively discovers FIT files, Garmin summarized-activity JSON, and
zip exports; its per-athlete object/version checkpoints make unchanged files idempotent. Uploaded
zip archives use the same checkpointed worker path. Filesystem staging shares the
`archive_import_data` volume; production can set `RUNTRAINER_ARCHIVE_IMPORT_STORAGE_BACKEND=gcs`
plus the GCS bucket and credential settings to return a direct signed upload URL.

## Multi-tenant fitness sources (in progress)
- Provider apps (Garmin/Strava/etc.) are registered per environment instead of committing credentials to `.env`. Use `/api/providers/apps` to store client ids/secrets (encrypted at rest).
- Users connect their own provider accounts via `/api/providers/{provider}/connect`, which stores per-user access/refresh tokens encrypted in the database.
- Data sources remain per-user (`data_sources` table) so each user can point the system to their own Influx bucket/org and token. Avoid sharing a single Garmin account or Influx token across users.
- The old GARMINCONNECT_* env vars only support a single shared Garmin account; prefer migrating to per-user provider connections and retire those envs when ready.

## Authentication providers
- The default `/auth/login` route uses the Authentik broker when web OIDC is configured. Direct provider routes remain available at `/auth/{provider}/login` as emergency fallbacks; their callbacks live at `/auth/{provider}/callback`.
- Tokens issued by these providers are exchanged for app JWTs the same way as Google. A first-time account link requires a verified, normalized email; later logins resolve by the durable `(issuer, subject)` identity binding. Missing or unverified email claims are rejected.

### Authentik upstream Google SSO

The production identity path is Google identity → Authentik → Fitness Pals web OIDC client. The training-agent/GPT uses a separate Authentik OIDC client behind the same Google identity source. Direct Fitness Pals → Google OAuth is fallback-only.

Create a Google Cloud Web OAuth client (or reuse one whose redirect restrictions include both required paths) and configure this exact authorized redirect URI for the Authentik source:

```text
https://auth.fitness-pals.com/source/oauth/callback/google/
```

If the direct fallback remains enabled, retain its separate authorized redirect URI too:

```text
https://fitness-pals.com/auth/google/callback
```

Place `AUTHENTIK_GOOGLE_CLIENT_ID` and `AUTHENTIK_GOOGLE_CLIENT_SECRET` in the untracked deployment secrets overlay when creating or rotating the Authentik Google source. Existing sources can be reconciled without reloading their secret. Missing, partial, or placeholder pairs fail before any API mutation when a create or rotation is requested, and direct-app fallback credentials are never reused by the broker bootstrap.

Every deployment runs the profile-scoped `authentik-bootstrap` one-shot service after the Authentik API is healthy. It idempotently creates or patches source slug `google`, resolves `default-source-authentication` and `default-source-enrollment`, discovers the Identification stage actually bound to `default-authentication-flow`, and appends the Google source UUID only when missing. Its Identification-stage PATCH contains only `sources`, so existing sources, `user_fields`, and local username/password login are preserved. The Google source gets a custom user-property mapping that stores the upstream verified-email bit and normalized address. It accepts boolean `verified_email` from Authentik’s built-in Google OAuth adapter, or `email_verified` from OIDC (an explicitly present OIDC claim takes precedence). Bootstrap adds an update-only User Write stage before the configured source authentication flow’s existing stages so returning users persist these mapped attributes before login; enrollment keeps its existing write stage. For the web OIDC application identified by `RUNTRAINER_WEB_OIDC_ISSUER`, bootstrap replaces only that provider's default `email` scope mapping with one that returns `email_verified=true` only while the Google-verified address still matches the user's current Authentik email. Other clients' scopes and the website provider's `openid`/`profile` mappings are preserved. It also reconciles a dedicated `grafana` OIDC provider/application with the strict callback `https://grafana.fitness-pals.com/login/generic_oauth`; it does not alter the training-agent OIDC client or enable automatic Google redirects.

After the mapping is first deployed, existing Authentik users must complete a fresh Google sign-in so Authentik can store the upstream verification attributes. If a user's Authentik email later changes, the website OIDC mapping deliberately returns `email_verified=false` until that address is verified through Google.

Run it manually with the current untracked `.env` when needed:

```bash
docker compose --env-file .env --profile bootstrap run --rm --no-deps authentik-bootstrap
```

The secret-free JSON output reports the source slug/UUID, Google verification-mapping status, website application/provider and email-scope reconciliation status, Identification-stage name/UUID, credential-pair origin, Grafana provider/application identifiers, and whether each resource was created, updated, or already attached.

### Grafana administrator access

Grafana disables anonymous and basic authentication and automatically enters
Authentik Generic OAuth. Authenticated users default to the `Viewer` role; only
members of the Authentik group `Grafana Admins` map to the Grafana `Admin` role.
Create and maintain that group in Authentik, and keep its membership limited to
operators. Production publishes no Grafana host port, so administration stays
behind the Cloudflare tunnel and Authentik SSO.

Before merging or deploying an SSO credential rotation, set a complete, unique
pair for dev in the repository's `DEV_GRAFANA_OIDC_CLIENT_ID` and
`DEV_GRAFANA_OIDC_CLIENT_SECRET` Actions secrets, and a different pair in the
`production` environment's `GRAFANA_OIDC_CLIENT_ID` and
`GRAFANA_OIDC_CLIENT_SECRET` secrets. The deploy jobs validate presence before
assembling the deployment environment or launching services, without logging
values. Compose model inspection (`config`, `ps`, or `images`) intentionally
allows the pair to be absent; the Authentik bootstrap independently rejects a
missing, partial, or placeholder pair before it changes Authentik.
Verify a Viewer cannot open Grafana administration and a `Grafana Admins` member
can. Retain the local Grafana admin credentials in the operator secret store for
CLI-assisted recovery; password login is disabled during normal production
operation. The loopback-only development overlay enables the basic login for
local recovery and testing.

Deployment-sensitive branches can be proven on dev before merge with an explicit
manual dispatch:

```bash
gh workflow run ci-cd.yml --ref <branch> -f deploy_dev=true
```

That path runs the full CI gate, reconciles the complete dev Compose runtime, and
runs local and external smoke checks. Production remains restricted to revisions
on `main`.

Production service-to-service probes run over Docker DNS. For local-only access to
InfluxDB, Grafana, the backend, training-agent, or Authentik, use
`compose.dev.yml`; its host mappings are restricted to `127.0.0.1`. The Authentik
worker runs as the image's unprivileged UID and has no Docker socket, so embedded
outposts must be deployed and managed separately if they are introduced later.

Authentik stores source, flow, stage, provider, application, and user state in the PostgreSQL database named by `AUTHENTIK_POSTGRESQL__NAME`; this stack intentionally points it at `RUNTRAINER_POSTGRES_DB`. Manual admin-UI configuration alone is not reproducible and must not be relied on.

To inspect the current source and binding through the API without exposing credentials, read only the bootstrap token from the deployment environment, then run:

```bash
AUTHENTIK_BOOTSTRAP_TOKEN="$(python3 scripts/read_env_value.py .env AUTHENTIK_BOOTSTRAP_TOKEN)"
source_pk="$(curl -fsS -H "Authorization: Bearer ${AUTHENTIK_BOOTSTRAP_TOKEN}" \
  'http://127.0.0.1:9100/api/v3/sources/oauth/google/' | jq -r '.pk')"
curl -fsS -H "Authorization: Bearer ${AUTHENTIK_BOOTSTRAP_TOKEN}" \
  'http://127.0.0.1:9100/api/v3/sources/oauth/google/' |
  jq '{name, slug, pk, provider_type, enabled, promoted, authentication_flow, enrollment_flow, user_matching_mode, callback_url}'
curl -fsS -H "Authorization: Bearer ${AUTHENTIK_BOOTSTRAP_TOKEN}" \
  'http://127.0.0.1:9100/api/v3/stages/identification/?page_size=100' |
  jq --arg source_pk "$source_pk" \
    '.results[] | select(.sources | index($source_pk)) | {name, pk, sources, user_fields, flow_set}'
```

The `callback_url` returned through localhost uses the request host; the verified route path is `/source/oauth/callback/google/`. Through the public Authentik host the authorized callback is the HTTPS URL shown above.

Safe database evidence gathering is read-only. First list databases:

```bash
docker compose exec -T runtrainer-postgres sh -lc \
  'psql -U "$POSTGRES_USER" -d postgres -Atc "select datname from pg_database where datistemplate = false order by datname"'
```

Only if both `authentik` and `runtrainer` are listed, compare Google-source presence without switching databases or modifying state:

```bash
for database in authentik runtrainer; do
  docker compose exec -T runtrainer-postgres sh -lc \
    'psql -U "$POSTGRES_USER" -d '"$database"' -Atc \
    "select count(*) from authentik_sources_oauth_oauthsource oauth join authentik_core_source source on source.policybindingmodel_ptr_id = oauth.source_ptr_id where source.slug = '\''google'\''"'
done
```

Post-deploy verification:

```bash
curl -fsS https://auth.fitness-pals.com/-/health/ready/
curl -fsS https://auth.fitness-pals.com/application/o/fitness-pals-web/.well-known/openid-configuration | jq '{issuer, authorization_endpoint, token_endpoint, jwks_uri}'
curl -fsSI https://fitness-pals.com/auth/login | sed -n '1p;/^location:/Ip'
curl -fsS https://auth.fitness-pals.com/application/o/training-agent-gpt/.well-known/openid-configuration | jq '{issuer, authorization_endpoint, token_endpoint, jwks_uri}'
```

Then use a private browser window to complete the stateful checks: open `https://fitness-pals.com/auth/login`; confirm the Authentik page shows both the username/email form and Google; click Google and confirm the next host is `accounts.google.com`; complete login and confirm the browser returns through `auth.fitness-pals.com`, then `/auth/callback`, and an authenticated Fitness Pals session is created. Sign out and separately confirm the local Authentik username/password break-glass login still works. For the GPT client, start its OAuth connection and confirm it uses the training-agent discovery document and returns an Authentik-issued response.

To roll back the returning-user attribute update, remove only the binding for `fitness-pals-google-authentication-write` from the configured source authentication flow and revert the bootstrap change so deployment does not recreate it. The stage uses `never_create` and does not create duplicate users.

Rollback is to revert the repository change and stop invoking the `authentik-bootstrap` one-shot service. Do not switch or drop databases. Because the Google bootstrap only appends the source binding, an urgent UI rollback can disable the Google source or remove only its UUID from the Identification stage while leaving local login and the other OIDC clients intact. The Grafana provider/application can be disabled independently while break-glass access is used. Keep the direct Google route and callback configured until brokered login has been verified in production; do not restore anonymous Grafana Admin or the raw Docker socket as a routine rollback.

## Garmin authorization and activity import
- `GARMIN_MODE=scraper` uses existing per-user scraper tokens for legacy imports; it cannot authorize a new user by sending their browser to the ordinary Garmin Connect sign-in page. `/api/providers/garmin/login` returns 503 in this mode and onboarding offers Garmin archive upload instead. Existing scraper connections and imports remain available.
- With an approved Garmin Connect Developer Program application, configure `GARMIN_MODE=oauth`, `GARMIN_CLIENT_ID`, `GARMIN_CLIENT_SECRET`, and the registered `GARMIN_REDIRECT_URI` (the `/api/providers/garmin/callback` endpoint). `/api/providers/garmin/login` initiates Garmin OAuth2 PKCE consent; the callback checks state, verifier, and initiating user before exchanging the code and encrypting the access and refresh tokens. The normal Garmin Connect web login does **not** give third-party apps a grant.
- OAuth token capture is **not** an end-to-end official Activity API integration. The current scheduled importer uses private Connect endpoints, which are not compatible with partner OAuth tokens. Its fetch routes reject these grants rather than reporting a successful sync; an approved Activity API adapter, notification/backfill configuration, and consent/disconnect handling are still required for automatic coaching imports. Archive upload already writes into the authenticated athlete's data stores.
- Rollback: revert this change if needed; existing scraper tokens and imported activities are retained. Do not switch `GARMIN_MODE` in production solely to enable the consent button until the official ingestion path is implemented and tested.

```mermaid
flowchart LR
  U[User trigger /fetch] --> BE[Backend]
  BE --> DB[(IngestRun, tokens)]
  BE --> GAPI[Garmin API]
  GAPI --> BE
  BE --> PG[(Postgres)]
  BE -.-> IFX[(InfluxDB)]
  classDef dashed stroke-dasharray: 4 4;
  class IFX dashed;
```

## Activity de-duplication & provenance (Garmin / Strava / Apple Health)
When multiple providers surface the same workout, the backend keeps one canonical activity per user and tracks every provider source for transparency:
- Canonical tables: `activities` holds the merged record; `activity_sources` links every provider item with decisions, chosen fields, and optional trimmed payload; `ingest_runs` + `ingest_decisions` capture batch runs and per-activity decisions for audit.
- Matching logic: A fingerprint is built from start time (UTC), duration, distance, and sport. Defaults tolerate ±90s start, ±10% duration, ±3% distance. These can be tuned via env (`RUNTRAINER_DEDUPE_START_TIME_TOLERANCE_SECONDS`, `RUNTRAINER_DEDUPE_DURATION_TOLERANCE_RATIO`, `RUNTRAINER_DEDUPE_DISTANCE_TOLERANCE_RATIO`) or code.
- Priority rules: Per metric, you can prefer certain providers (e.g., HR/cadence from Garmin, segments from Strava, rings from Apple). A per-user “primary provider” flag can skip double-import when Garmin already forwards to Strava.
- Transparency: Admin endpoints expose ingest state and decisions:
  - `GET /api/ingest/runs` lists recent ingestion runs (provider, status, summary).
  - `GET /api/ingest/runs/{id}` shows a single run.
  - `GET /api/ingest/runs/{id}/decisions` lists per-activity decisions, including reasons, fingerprints, tolerances, and chosen fields.
- User-facing provenance (to be wired in UI): show which providers contributed to a workout and which fields came from where; allow marking duplicates or keeping both to override the matcher.
- Safety: Provider records are never deleted; decisions are logged for replay. Conflicts (multiple close matches with disagreements) should be flagged as `conflict` and surfaced for review rather than silently merged.

### Garmin Connect bridge (temporary multi-tenant bridge)
- Official Garmin Activity/Health APIs are the long-term solution. The scraper adapter (`backend/app/providers/garmin_scraper.py`) remains for existing tokens; it does not provide a supported browser authorization flow for new users.
- The legacy `GARMINCONNECT_*` env values support only a single shared account; plan to retire them once per-user ingestion is wired up end-to-end.
- Existing scraper ingestion uses unofficial Garmin Connect endpoints; expect occasional breakage if Garmin changes them. The legacy `/sso/callback/{state}` endpoint is not part of the new-user flow.

## Updating garmin-grafana
Because we rely on published images, updating is as simple as pulling new tags:
```bash
docker compose pull garmin-fetch-data grafana
```
No source merges are required.

## Notes
- Tokens and data directories are ignored via `.gitignore` (`garminconnect-tokens/`, `DATA/`, `.env`, etc.).
- If you need provisioning files from upstream, consume them directly from their repo or dashboard import; avoid copying them back here to keep the codebases separate.

## Custom GPT setup (manual steps, files tracked here)
- Prompt template: `gpt/prompt.md` (paste into the GPT system/instructions field).
- Action manifest: `gpt/action-manifest.json` (update `your-domain.com` and verification token, then import in the GPT builder). Host your OpenAPI at `https://your-domain.com/openapi.json` so the builder can ingest it.
- The GPT UI still requires manual import; versioning these files here keeps the configuration reproducible alongside code changes.
