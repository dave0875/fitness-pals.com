# fitness-pals

This repo drives my personal fitness stack. It keeps my code (backend, frontend, training agent) separate from the upstream [garmin-grafana](https://github.com/arpanghosh8453/garmin-grafana) project. Garmin data collection, InfluxDB, and Grafana dashboards now come entirely from published container images so I can pull upstream updates without merging their source into this repo.

## What stays in this repo
- My services (see `services/`, `backend/`, `frontend/`).
- Compose wiring for dependent services (InfluxDB, Grafana, ngrok, training-agent).
- Local environment and secrets files (not committed).

## What moved out
- Vendored garmin-grafana source, dashboards, and provisioning files have been removed. The stack now uses the upstream image `ghcr.io/arpanghosh8453/garmin-fetch-data:latest` directly. Grafana dashboards can be imported from Grafana Cloud (code `23245`) or the upstream repo if desired, but are no longer stored here.

## Running the stack
Create a `.env` with the required variables (examples from the upstream docs still apply: InfluxDB credentials, Garmin Connect auth, Grafana admin, ngrok token, etc.). Then:

```bash
docker compose up -d
```

Key services:
- `garmin-fetch-data`: pulls data from Garmin into InfluxDB via the upstream image (no local build).
- `influxdb`: time-series database for metrics.
- `grafana`: visualization. Import the Garmin dashboard by ID `23245` or from the upstream repo when needed.
- `training-agent`: your local service (built from `services/training_agent`).
- `ngrok`: optional tunnel for remote access.

## Environment configuration (what each variable does and where to get it)
- `RUNTRAINER_JWT_SECRET`: random string used to sign app-issued JWTs (generate with `openssl rand -hex 32`).
- `RUNTRAINER_GOOGLE_CLIENT_ID` / `RUNTRAINER_GOOGLE_CLIENT_SECRET` / `RUNTRAINER_GOOGLE_REDIRECT_URI`: OAuth 2.0 Web client from Google Cloud Console; create credentials, add your redirect URI (e.g., `https://your-domain.com/auth/google/callback`), paste the ID/secret.
- `RUNTRAINER_MICROSOFT_CLIENT_ID` / `RUNTRAINER_MICROSOFT_CLIENT_SECRET` / `RUNTRAINER_MICROSOFT_REDIRECT_URI`: App registration in Azure AD (Entra); create a Web redirect URI; copy the Application (client) ID and client secret.
- `RUNTRAINER_APPLE_CLIENT_ID` / `RUNTRAINER_APPLE_CLIENT_SECRET` / `RUNTRAINER_APPLE_REDIRECT_URI`: Apple Sign in client; create a Services ID in Apple Developer, set the redirect URI, generate a client secret (JWT signed with your key) and supply here.
- `RUNTRAINER_DATABASE_URL`: SQLAlchemy connection string to Postgres (e.g., `postgresql://user:pass@host:5432/runtrainer`).
- `RUNTRAINER_FERNET_KEY`: key used to encrypt user/provider tokens; generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- `RUNTRAINER_INFLUX_DEFAULT_URL`: optional default Influx endpoint shown to users (can be empty if you don’t want a default).
- `RUNTRAINER_OPENAI_API_KEY`: API key for GPT-based coaching responses (from platform.openai.com).
- `RUNTRAINER_ACCESS_TOKEN_EXP_MINUTES` / `RUNTRAINER_REFRESH_TOKEN_EXP_DAYS`: JWT lifetimes; leave defaults unless you need to shorten/extend sessions.
- `RUNTRAINER_DEDUPE_START_TIME_TOLERANCE_SECONDS` / `RUNTRAINER_DEDUPE_DURATION_TOLERANCE_RATIO` / `RUNTRAINER_DEDUPE_DISTANCE_TOLERANCE_RATIO`: tweak dedup tolerances; defaults are ±90s start, ±10% duration, ±3% distance.
- `INFLUXDB_HOST` / `INFLUXDB_PORT` / `INFLUXDB_USERNAME` / `INFLUXDB_PASSWORD` / `INFLUXDB_DATABASE`: InfluxDB connection for training-agent and garmin-fetch-data.
- `GARMINCONNECT_EMAIL` / `GARMINCONNECT_BASE64_PASSWORD`: legacy single Garmin account for garmin-fetch-data; avoid for multi-tenant and move to per-user provider connections instead.
- `GF_SECURITY_ADMIN_USER` / `GF_SECURITY_ADMIN_PASSWORD`: Grafana admin login.
- `CLOUDFLARE_TUNNEL_TOKEN`: Cloudflare tunnel token to expose services.
- `TRAINING_API_KEY`: key used by the training-agent harness.
- `BOT_GITHUB_TOKEN`: token for any bot operations (keep out of commits).

## Multi-tenant fitness sources (in progress)
- Provider apps (Garmin/Strava/etc.) are registered per environment instead of committing credentials to `.env`. Use `/api/providers/apps` to store client ids/secrets (encrypted at rest).
- Users connect their own provider accounts via `/api/providers/{provider}/connect`, which stores per-user access/refresh tokens encrypted in the database.
- Data sources remain per-user (`data_sources` table) so each user can point the system to their own Influx bucket/org and token. Avoid sharing a single Garmin account or Influx token across users.
- The old GARMINCONNECT_* env vars only support a single shared Garmin account; prefer migrating to per-user provider connections and retire those envs when ready.

## Authentication providers
- OAuth login now supports Google, Microsoft, and Apple. Configure the relevant client id/secret + redirect URI in `.env` (RUNTRAINER_* variables) and hit `/auth/{provider}/login` (or `/auth/login` for Google). Callbacks live at `/auth/{provider}/callback`.
- Tokens issued by these providers are exchanged for app JWTs the same way as Google; user records are keyed by email. Ensure the IdP returns an email claim or the login is rejected.

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

### Garmin scraper (temporary multi-tenant bridge)
- Official Garmin Health API is the long-term solution; until approved, users can supply their own Garmin Connect credentials via `/api/providers/garmin/scraper/connect`. Credentials are encrypted per user. A scraper adapter (`backend/app/providers/garmin_scraper.py`) exists as a bridge and will be swapped for Garmin Health when available.
- The legacy `GARMINCONNECT_*` env values support only a single shared account; plan to retire them once per-user ingestion is wired up end-to-end.
- The scraper path uses the `garth` library (installed via backend requirements) to log in per user. It remains unofficial; expect occasional breakage if Garmin changes private endpoints.

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
