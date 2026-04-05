# Option 3 Migration Plan

Last updated: 2026-04-04

## Goal
Adopt `Option 3: Hybrid Core + FHIR Projection` as the long-term architecture for `fitness-pals.com`.

This means:
- product-native canonical data lives in Postgres
- provider-specific ingestion is isolated behind adapters
- Influx and FHIR are projections, not the system of record
- product auth is unified around app-issued sessions
- sync execution moves out of request handlers and into explicit worker ownership

## Planning Standard
This document is not a backlog dump and not a generic roadmap. It is the delivery tracker for the selected architecture.

It should satisfy three standards:
- `thin-slice delivery`: every `next` item must be small enough to merge safely to `main`
- `clean architecture`: every slice must improve or preserve dependency direction and boundary clarity
- `platform thinking`: every slice should create or strengthen reusable seams for future providers, projections, and runtime components

## Section Semantics
- `Status Summary`: high-level rollup only; each line must point to concrete slices below
- `Target Architecture`: target state and non-negotiable boundaries
- `Completed Slices`: only slices merged to `main` and validated against their acceptance targets
- `Current State After Completed Slices`: descriptive facts about the repo/system today, not commitments
- `Next Slices`: issue-ready slices intended to be taken in the next few PRs
- `Later`: agreed direction, intentionally deferred
- `Operational Prerequisites`: environment/runtime requirements that must be true outside code
- `Open Gaps`: truths that are still wrong and need to stop being true
- `Out of Scope`: things we are explicitly not doing in this wave

## Status Definitions
- `done`: merged to `main`, green in CI/governance, validated against slice acceptance target, and reflected in this document
- `next`: the smallest valuable slice that should be turned into issue/PR work next
- `later`: aligned with the architecture, but not the immediate next integration step
- `blocked`: ready in principle, but waiting on an external dependency, environment prerequisite, approval, or unresolved design decision

## Definition Of Done
No item should be marked `done` unless all of the following are true:
- it is merged to `main`
- the PR passed CI and governance
- the slice is linked to exactly one issue/MMF
- tests were added or updated for the behavior the slice changes
- rollback risk is understood and was documented in the PR
- the slice acceptance target is true in the target runtime, not only in local/unit tests
- any required migration, env, or deploy prerequisite is documented
- this document was updated to reflect the new reality

Additional rules by section:
- a `Completed Slice` is not `done` unless its own acceptance target is fully true
- an `Operational Prerequisite` is not `done` until it is true in the real environment
- an `Open Gap` is only `done` when the gap stops being true
- `Current State` items are never `done`; they are observations

## Slice Standard
Every slice in this document should be stated in a way that supports trunk-based delivery.

Each slice must define:
- purpose: the smallest end-to-end improvement that matters
- boundary: which seam it introduces, protects, or clarifies
- likely files/modules: where the change is expected to land
- tests to add first: what should go red before implementation
- acceptance target: how we know the slice is actually done
- rollback: how to retreat safely if the slice misbehaves
- explicit non-goals: what the slice does not attempt to solve yet

## Architecture Guardrails
These are the rules that keep the migration on the chosen path.

- `fitness-core` owns product language; provider names must not become core entity names
- Postgres is the canonical store for product-native facts
- Influx and FHIR are downstream projections and may be rebuilt from canonical state
- provider adapters must normalize into product-native concepts before product logic uses the data
- routes should orchestrate use cases, not contain provider/business logic
- framework and infrastructure details should point inward only through ports and application services
- user-facing auth must converge on app-issued sessions; raw provider/browser tokens are not the long-term product contract
- new provider support should extend adapter seams rather than fork route/service behavior
- every slice should leave the system more replaceable, not more entangled

## Status Summary
- `done`: Garmin sync-job spine
- `done`: dev validation regression fixes for Garmin scheduler, ingest, Influx verify, metrics, and chat fallback
- `done`: deploy hardening with changed-service gating, readiness checks, and Cloudflare ingress smoke checks
- `done`: auth normalization to app-issued sessions only
- `next`: real worker/runtime separation for sync execution
- `later`: canonical core read/write rollout and FHIR projection

## Target Architecture
- `identity-access`: app-issued sessions, user identity, operator access
- `provider-connectivity`: provider app config, user provider connections, token lifecycle
- `sync-orchestration`: sync jobs, checkpoints, retries, replay, scheduling
- `fitness-core`: canonical workouts, sleep periods, observations, provenance
- `projections-timeseries`: Influx projection for charts and Grafana
- `projections-fhir`: FHIR export/projection boundary
- `ops-admin`: operator tooling for token health, sync health, replay, repair

Dependency direction:
- routes and workers depend on application services
- application services depend on domain ports
- provider adapters, Influx projection, and FHIR projection sit at the edge
- product behavior must not depend directly on Garmin-specific or Influx-specific schemas

Canonical runtime intent:
- product frontend: user-facing application only
- product API: user-facing API and use-case entrypoint only
- worker/scheduler: sync execution, projection execution, replay/repair
- ops/admin surface: protected operator tooling, not product UX

## Completed Slices

### Slice 1: Sync Job Spine
- status: `done`
- issue/pr: `#30` / `#46`
- merge commit: `deb5605`
- acceptance target:
  - manual Garmin fetch creates a `sync_job`
  - scheduled Garmin fetch uses the same orchestration path
  - `sync_checkpoints` update on success/failure
  - request handlers no longer own sync state tracking directly
- outcome:
  - Garmin sync now runs through explicit `sync_job` and `sync_checkpoint` state
  - manual and scheduled fetches use the orchestration layer
  - sync execution is still in-process, but request handlers no longer own state tracking directly

### Slice 2: Dev Validation Regression Fixes
- status: `done`
- issue/pr: `#30` / `#47`
- merge commit: `9033634`
- acceptance target:
  - scheduler works for current Garmin mode
  - manual Garmin sync completes through the current path
  - batch fetch works again
  - checkpoint state updates correctly
  - metrics/chat/datasource regressions found during dev validation are corrected
- outcome:
  - Garmin scheduler respects scraper mode
  - Garmin ingest no longer fails on read-only username behavior
  - metrics and chat degrade more safely in broken dev environments
  - Influx verify path works against the current dev setup

### Slice 3: Deploy Hardening
- status: `done`
- issue/pr: `#33` / `#48`
- merge commit: `d9daa79`
- acceptance target:
  - deploy workflow validates compose config before restart
  - rebuild/restart is gated to changed services only
  - backend and training-agent expose readiness, not just liveness
  - compose dependency wiring waits for readiness where needed
  - Cloudflare ingress is smoke-tested through configured public URLs
- outcome:
  - deploy workflow validates compose config before restart
  - rebuild/restart is gated to changed services only
  - backend and training-agent expose readiness endpoints
  - compose health/dependency wiring is stricter
  - Cloudflare ingress is now smoke-tested via `CLOUDFLARE_SMOKE_URLS`

### Slice 4: Auth Normalization
- status: `done`
- issue/pr: `#26` / `pending`
- merge commit: `pending`
- acceptance target:
  - product API accepts app-issued sessions only
  - frontend login flow exchanges provider auth for app session
  - training-agent/admin auth path is separate and explicit
  - no product page stores raw Google credentials as the product access token
- outcome:
  - product API now resolves users from app-issued JWTs only, via bearer token or `runtrainer_session` cookie
  - raw Google browser tokens are rejected by product routes
  - OAuth callback now issues app session cookies and redirects the user to the product dashboard
  - product frontend pages no longer bootstrap from `localStorage` provider tokens and instead rely on the app session automatically
  - training-agent/admin remains on its separate Google-bearer auth surface rather than sharing the product auth contract

## Current State After Completed Slices
- backend has explicit sync-job state but not a separate worker container/runtime yet
- Garmin remains the only real provider path and is still partly scraper/bridge oriented
- product auth now uses app-issued session tokens; raw Google browser tokens are no longer a valid product API contract
- product frontend no longer stores or boots from raw Google credentials in `localStorage`
- training-agent/admin auth is still separate from product auth and still uses its existing Google bearer flow
- product reads still rely on existing mixed paths rather than a fully canonical Postgres-backed read model
- deploy path is substantially safer, but environment configuration still needs cleanup and standardization

## Next Slices

### Slice 5: Worker Runtime Separation
- status: `next`
- target issue: should be created if not already present as a dedicated MMF
- purpose:
  - move sync execution out of request handlers
  - introduce worker/scheduler ownership as an actual runtime boundary
- boundary:
  - API creates/dispatches work; worker owns execution and checkpoint updates
- likely files:
  - `backend/app/services/sync_jobs.py`
  - Garmin scheduler/orchestration modules
  - `compose.yml`
  - deploy workflow if a new worker service is introduced
- tests to add first:
  - enqueue path creates runnable job without executing inline
  - worker processes a pending job and updates final state
  - failure/retry path updates checkpoints predictably
- acceptance target:
  - API enqueues/dispatches sync work
  - worker executes jobs and updates checkpoints independently
  - deploy topology includes the worker runtime explicitly
  - request/response latency no longer includes sync execution time
- rollback:
  - feature flag or route fallback to inline execution for emergency cutback
- non-goals:
  - full adapter rewrite
  - FHIR projection

### Slice 6: Provider Adapter Formalization
- status: `later`
- purpose:
  - isolate Garmin bridge behavior behind a real adapter contract
  - make future Garmin official and Apple Health adapters plug into the same sync port
- done means:
  - provider-specific runtime behavior is hidden behind an explicit adapter interface
  - sync orchestration depends on capabilities/contracts, not Garmin-specific implementations

### Slice 7: Canonical Core Write Model
- status: `later`
- purpose:
  - persist canonical workouts, sleep, observations, and provenance in Postgres
  - stop treating provider payloads as product-native entities
- done means:
  - product-native entities are written canonically in Postgres
  - provenance and source records are preserved without forcing provider schema into product logic

### Slice 8: Product Read Model Migration
- status: `later`
- purpose:
  - move product reads off provider-shaped/Influx-shaped assumptions
  - keep Influx as projection, not source of truth
- done means:
  - product endpoints read from canonical/core-backed read models
  - Influx remains optional/derived for charts and ops, not product truth

### Slice 9: FHIR Projection
- status: `later`
- purpose:
  - project canonical core data to FHIR resources
  - keep FHIR as an interoperability boundary, not the internal domain model
- done means:
  - canonical entities project to stable FHIR resources idempotently
  - product behavior does not depend on FHIR representations

## Operational Prerequisites
- dev secret env now needs `CLOUDFLARE_SMOKE_URLS`
- prod secret env also needs `CLOUDFLARE_SMOKE_URLS`
- currently verified public smoke URL: `https://fitness-pals.com/`
- ideal future smoke URLs once public routing exists:
  - `https://api.fitness-pals.com/ready`
  - `https://grafana.fitness-pals.com/api/health`

## Open Gaps
- the configured prod secret path does not currently exist on this host
- public `api.` and `grafana.` hostnames are not live yet from this environment
- frontend, backend, and deploy topology are still not fully rationalized into a single product ingress contract
- admin/ops surface is still represented mostly by the training-agent, not a cleanly separated ops application

## Out of Scope For Current Wave
- full FHIR coverage beyond initial projection/export boundary
- Garmin official OAuth/API migration before business approval
- Apple Health native implementation
- write-back to providers
- enterprise org/RBAC model
- broad UI redesign unrelated to auth and product boundary cleanup

## Working Rule
Do not treat this document as a wish list. Update it only when:
- a slice is merged to `main`
- a planned slice changes materially
- an operational prerequisite or blocker changes

When a slice is complete:
- move it to `Completed Slices`
- record issue, PR, and merge commit
- replace vague claims with concrete acceptance outcomes
- update `Current State`, `Operational Prerequisites`, and `Open Gaps` so the document remains true
