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

## Updating garmin-grafana
Because we rely on published images, updating is as simple as pulling new tags:
```bash
docker compose pull garmin-fetch-data grafana
```
No source merges are required.

## Notes
- Tokens and data directories are ignored via `.gitignore` (`garminconnect-tokens/`, `DATA/`, `.env`, etc.).
- If you need provisioning files from upstream, consume them directly from their repo or dashboard import; avoid copying them back here to keep the codebases separate.
