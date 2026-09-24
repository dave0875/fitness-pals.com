# Athlete State

Athlete State is the provider-neutral, athlete-owned product read model for daily recovery and physiology evidence.

## Phase 1 boundary

Phase 1 derives Athlete State from canonical `sleep_sessions` rows in Postgres. `SleepSession` remains the durable user-owned source record; Athlete State is the normalized read model. This avoids a second recovery store while centralizing provider-key interpretation in one service.

The contract exposes:

- latest normalized recovery state;
- bounded dated history;
- per-signal value and unit;
- known, unavailable, or stale status;
- observation date and stale-after boundary;
- canonical/provider provenance;
- a genuine seven-day average of available overnight-HRV observations, including sample count.

Missing values remain `null`; they are never converted to zero. Stale values remain visible and explicitly stale.

## Current signals

Phase 1 recognizes sleep duration, sleep score, overnight HRV, and resting heart rate when canonical sleep evidence contains them. Provider payload variants are normalized inside `app.services.athlete_state`; Dashboard, Coach, and other product consumers should not parse Garmin JSON keys themselves.

## Product integration

- Athlete Home / Dashboard uses Athlete State for its recovery card and recovery freshness.
- The canonical metrics summary used by Coach embeds Athlete State.
- The legacy `hrv_avg` compatibility field is derived only from actual available overnight-HRV observations in the last seven days and exposes its window and sample count.
- `GET /api/athlete-state?days=N` exposes the same user-scoped state and bounded history.

## Source boundaries

Product reads stay in user-owned canonical Postgres records. Global Influx series are not a product read source. Influx can continue to hold granular timeseries for diagnostics/analysis, but it is not authoritative for Athlete State.

Google Drive Garmin/Fenix backup import is the durable archive direction. The current archive importer intentionally treats supported activity FIT material separately from sleep/HRV/wellness material. Phase 1 does not broaden Drive import into an uncontrolled wellness importer. A later slice may decode wellness FIT records into canonical sleep/recovery evidence, after which Athlete State can consume them without changing its product contract.

The standalone training-agent HRV/sleep diagnostic endpoints remain a legacy diagnostic surface and are not the source of truth for the authenticated web product.

## Extension points

Later Athlete Orbit phases can add training load, cross-training contribution, rolling personal baselines/deviations, and goal context alongside recovery without changing provider-facing payloads into product contracts. No universal readiness score or HRV-based workout prescription is introduced in Phase 1.
