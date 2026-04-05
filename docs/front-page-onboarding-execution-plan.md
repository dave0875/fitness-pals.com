# Front Page And Onboarding Execution Plan

Last updated: 2026-04-05

## Purpose
Replace the current split between:
- a marketing-heavy public `fitness-pals.com` landing page on `orin`
- a minimal Next frontend in `frontend/pages/`
- a real but poorly surfaced backend onboarding flow

with one coherent acquisition and activation funnel that:
- gets a user from anonymous to authenticated
- gets that user from authenticated to Garmin-connected
- gets that user from Garmin-connected to first sync
- shows meaningful product value immediately after first sync

This document is PR-ready. Each slice is intended to become one issue and one short-lived PR.

## Product Decision
The front page is not a brochure. It is the first screen of the product funnel.

The public site should optimize for:
- trust before data access
- speed to first value
- explicit state transitions
- clear provider and auth handoffs
- proof that the product produces serious output

The page should not optimize for:
- abstract brand language without product actions
- dead-end CTAs
- burying sign-in behind generic marketing copy
- sending users into debug-like post-login pages with no onboarding guidance

## Current Repo Reality

### What exists today
- Public production site is served by nginx on `orin` from `/var/www/fitness-pals`.
- Product frontend repo pages currently live in:
  - [index.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/index.js)
  - [dashboard.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/dashboard.js)
  - [settings.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/settings.js)
- Product login/session bootstrap already exists in:
  - [oauth.py](/home/dbarker/Code/fitness-pals.com/backend/app/auth/oauth.py)
- Product session resolution already exists in:
  - [deps.py](/home/dbarker/Code/fitness-pals.com/backend/app/deps.py)
- Garmin onboarding seams already exist in:
  - [providers.py](/home/dbarker/Code/fitness-pals.com/backend/app/routes/providers.py)
  - [providers_garmin.py](/home/dbarker/Code/fitness-pals.com/backend/app/routes/providers_garmin.py)

### What the backend already supports
- `GET /auth/login`
  - start Google auth flow
- `GET /auth/{provider}/login`
  - provider-specific auth flow
- `GET /auth/{provider}/callback`
  - creates or updates the user
  - issues app cookies
  - redirects to `/dashboard`
- `GET /api/providers/me`
  - list connected providers for current user
- `GET /api/providers/garmin/login`
  - start Garmin OAuth connect flow
- `GET /api/providers/garmin/callback`
  - store Garmin token
- `GET /api/providers/garmin/token-status`
  - current Garmin connection state
- `POST /api/providers/garmin/fetch`
  - enqueue first Garmin sync

### Main mismatch
- The public page implies a product that is ready for users.
- The actual onboarding flow exists, but the front page does not drive into it.
- The post-login experience is still too close to an internal/private app shell.

## Success Criteria
The new front page is successful when all of these are true:
- anonymous users can start the real auth flow from the page
- authenticated users do not see anonymous acquisition CTAs
- authenticated users with no Garmin connection are pushed toward Garmin connect
- connected users with no sync are pushed toward first sync
- synced users are pushed into a real first-value experience
- the page clearly explains what data is used, why, and what the user gets back
- the page looks like a serious endurance product, not a generic AI/fitness startup

## State Model
The page must be state-aware.

### State A: Anonymous
Show:
- primary CTA: `Start with Google`
- secondary CTA: `View sample coach dossier`
- tertiary CTA: `How it works`

Hide:
- Garmin-specific actions
- dashboard-only actions

### State B: Authenticated, Garmin not connected
Show:
- primary CTA: `Connect Garmin`
- supporting CTA: `Why Garmin?`
- supporting copy:
  - `Use Garmin to import training, recovery, and race-build context automatically.`

Hide:
- generic sign-in CTA

### State C: Garmin connected, no first sync
Show:
- primary CTA: `Import my training history`
- secondary CTA: `What sync includes`
- trust note:
  - `This pulls your recent training and recovery data into your private profile.`

### State D: Synced, first value available
Show:
- primary CTA: `Open my dashboard`
- secondary CTA: `See my latest readiness`
- tertiary CTA: `View my coach summary`

## Front Page Information Architecture

### 1. Hero
Headline:
- `Train with the full truth of your training.`

Subhead:
- `Fitness Pals turns workouts, recovery, sleep, and consistency into coaching you can actually use.`

Anonymous CTAs:
- `Start with Google`
- `View sample coach dossier`

Authenticated/no-Garmin CTAs:
- `Connect Garmin`
- `How your data is used`

Connected/no-sync CTAs:
- `Import my training history`
- `What gets synced`

Synced CTAs:
- `Open my dashboard`
- `See my latest readiness`

Trust line under CTA:
- `Google for identity. Garmin for training data. Revocable anytime.`

### 2. Goal Handshake
This section should appear on the public page before signup, but should not block progress.

Prompt:
- `What are you here to do?`

Choices:
- `Train for a marathon`
- `Train for a half`
- `Rebuild consistency`
- `Understand recovery`

Behavior:
- choice should persist locally and later shape onboarding copy
- no account required to select

### 3. How It Works
Four-step strip:
1. `Sign in`
2. `Connect Garmin`
3. `Sync your training history`
4. `Get coaching that adapts to real load and recovery`

### 4. Why Trust This
Cards:
- `You stay in control`
  - `Disconnect Garmin or revoke access anytime.`
- `No credential scraping in the main path`
  - `The product path uses OAuth-based connect.`
- `App-session auth`
  - `You use Fitness Pals sessions, not provider tokens, as the product login contract.`
- `Transparent coaching`
  - `Recommendations should explain what changed and why.`

### 5. What Adapts
Cards:
- `Training load`
- `Sleep and recovery`
- `Consistency`
- `Race goals`

Each card needs:
- one sentence on what signal is used
- one sentence on what product behavior changes because of it

### 6. Proof
Show public sample artifacts, not claims.

Required links:
- sample coach dossier
- sample readiness summary
- sample training pattern insight

This is the section that separates the product from competitors with generic “AI coach” language.

### 7. Human + AI Positioning
Copy direction:
- `AI-supported, coach-readable, runner-trustworthy`

This section should explicitly reject black-box language.

### 8. Returning User Rail
Persistent top-right or sticky actions:
- `Sign in`
- `Open dashboard`
- `Connect Garmin`

Behavior depends on state.

## Exact CTA Contract

### Anonymous
- `Start with Google` -> `/auth/login`
- `View sample coach dossier` -> public report URL
- `How it works` -> scroll to onboarding explainer

### Authenticated, Garmin not connected
- `Connect Garmin` -> `/api/providers/garmin/login`
- `How your data is used` -> trust section anchor

### Garmin connected, not synced
- `Import my training history` -> `POST /api/providers/garmin/fetch`
- `What gets synced` -> sync explainer modal/section

### Synced
- `Open my dashboard` -> `/dashboard`
- `See my latest readiness` -> `/dashboard#readiness` or equivalent

## User-State Transition Contract

### Anonymous -> Authenticated
- user clicks `Start with Google`
- backend starts `/auth/login`
- callback issues app session cookies
- redirect target must stop being hard-coded to the generic dashboard over time

Required improvement:
- auth callback should be able to redirect to a front-page-aware onboarding route such as `/welcome`

### Authenticated -> Garmin connected
- frontend checks `GET /api/providers/me` and/or `GET /api/providers/garmin/token-status`
- if Garmin missing, CTA points to `/api/providers/garmin/login`
- Garmin callback should redirect into a guided product route, not end in raw JSON

Required improvement:
- `GET /api/providers/garmin/callback` should redirect to a guided frontend state such as `/welcome?garmin=connected`

### Garmin connected -> First sync
- onboarding page shows `Import my training history`
- frontend calls `POST /api/providers/garmin/fetch`
- UI enters `sync_queued` state and polls lightweight onboarding status

Required improvement:
- add a lightweight onboarding status endpoint or compose from existing status routes

### First sync -> First value
- show:
  - latest activities
  - one readiness summary
  - one coach insight
  - one next action

## Differentiators That Will Separate This Page
These are deliberate product choices, not decoration.

### 1. Goal-first onboarding
Most competitors ask for data before asking intent.

We should invert that:
- ask the runner’s goal first
- use the answer to shape the onboarding narrative

Why:
- supports self-efficacy
- lowers cognitive friction
- makes the product feel like a coach, not a data sink

### 2. Data contract as a trust feature
Do not hide the data model behind compliance language.

Show a concise module:
- what data is read
- what is stored
- what is not used for login
- how to disconnect

Why:
- recent trust research shows privacy clarity and transparent framing increase trust and adoption

### 3. Explainability preview
Show a single example insight on the front page:
- `Why this plan would change`
- example:
  - `Sleep dropped, long-run load spiked, and recovery compressed. A good coach would reduce intensity. Fitness Pals will too.`

Why:
- this is more convincing than generic personalization language

### 4. First-win design
After first sync, show something immediately useful.

Not:
- empty dashboard
- raw JSON
- setup forms

Show:
- latest 5 activities
- race-build pattern
- readiness summary
- next best action

### 5. Public proof artifacts
Competitors hide output behind signup walls.

We should show:
- a serious sample dossier
- a readiness preview
- an example insight artifact

## 2025-2026 Research Notes
These are the bets this plan is leaning on.

- Assisted onboarding improves adoption, but the default flow should still stay short and mostly skippable.
  - Source: JMIR mHealth, 2026, onboarding strategy study
  - https://mhealth.jmir.org/2026/1/e78827/

- Trust in digital health is strongly shaped by privacy, quality, human interaction, digital literacy, and satisfaction.
  - Source: `npj Digital Medicine`, 2025, systematic review
  - https://www.nature.com/articles/s41746-025-01510-8

- Users of direct-to-consumer mHealth AI care about trust, privacy, autonomy, and clear boundaries.
  - Source: JMIR mHealth, 2025, qualitative trust study
  - https://mhealth.jmir.org/2025/1/e64715

- Durable digital-health impact requires a full engagement loop, not just low-friction signup.
  - Source: Frontiers Digital Health, 2026, ENGAGE framework
  - https://www.frontiersin.org/journals/digital-health/articles/10.3389/fdgth.2025.1713334/full

- Effective physical-activity interventions repeatedly rely on goal setting, self-monitoring, feedback, instruction, and social support.
  - Source: JMIR, 2025, meta-analysis
  - https://www.jmir.org/2025/1/e62906

- Running participation is strongly mediated by self-efficacy.
  - Source: Frontiers Psychology, 2025
  - https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1649195/full

Inference:
- the page should increase confidence before it increases setup burden
- the page should explain trust before it asks for permissions
- the page should preview adaptive coaching before it asks the user to believe in it

## Swarm Execution Plan

### Orchestrator
Owns:
- slice definition
- acceptance criteria
- sequencing
- doc updates

### Agent 1: QA And TDD
Owns:
- tests-first for every slice

Likely tests:
- anonymous CTA renders and points to real auth flow
- authenticated homepage state suppresses anonymous CTA
- Garmin callback redirects into guided onboarding
- onboarding status endpoint reports state correctly
- first-sync dashboard state renders first-win modules

### Agent 2: Frontend Experience
Owns:
- public/front-page UI
- responsive behavior
- state-aware CTA rendering

Likely files:
- [index.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/index.js)
- new components under `frontend/components/`
- likely new [welcome.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/welcome.js)

### Agent 3: Identity Flow
Owns:
- frontend-visible session bootstrap
- redirect behavior from auth callback

Likely files:
- [oauth.py](/home/dbarker/Code/fitness-pals.com/backend/app/auth/oauth.py)
- [deps.py](/home/dbarker/Code/fitness-pals.com/backend/app/deps.py)
- likely new session status endpoint

### Agent 4: Provider Onboarding
Owns:
- Garmin connect redirect flow
- onboarding status aggregation

Likely files:
- [providers.py](/home/dbarker/Code/fitness-pals.com/backend/app/routes/providers.py)
- [providers_garmin.py](/home/dbarker/Code/fitness-pals.com/backend/app/routes/providers_garmin.py)

### Agent 5: Insights Preview
Owns:
- first-win insight payload
- lightweight summary after first sync

Likely files:
- [metrics.py](/home/dbarker/Code/fitness-pals.com/backend/app/routes/metrics.py)
- new onboarding summary service under `backend/app/services/`

### Agent 6: Trust And Content
Owns:
- trust module
- explainability preview
- coach-quality public copy

### Agent 7: Accessibility And Performance
Owns:
- keyboard flow
- mobile layout
- performance budget
- semantic markup

### Agent 8: Production Publish
Owns:
- public-site deployment path on `orin`
- smoke checks for landing page and artifact links

## Thin Slices

### Slice FP-1: Honest CTA Replacement
- purpose:
  - replace dead-end or generic homepage actions with real auth and product-entry links
- boundary:
  - public acquisition layer points into real auth flow
- likely files/modules:
  - public front-page source
  - [index.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/index.js)
- tests to add first:
  - homepage renders `Start with Google`
  - CTA targets `/auth/login`
  - sample artifact CTA targets public report
- acceptance target:
  - an anonymous user can begin the real login flow from the page
- rollback:
  - revert to the current static page if auth routing breaks
- non-goals:
  - no state-aware behavior yet

### Slice FP-2: Session-Aware Front Page
- purpose:
  - make homepage CTA behavior depend on whether the user is already signed in
- boundary:
  - public page becomes session-aware without becoming app-coupled
- likely files/modules:
  - frontend homepage
  - new session status endpoint if needed
- tests to add first:
  - anonymous sees sign-in CTA
  - authenticated user sees non-anonymous CTA set
- acceptance target:
  - returning users do not get pushed back into generic acquisition
- rollback:
  - degrade back to anonymous-safe CTA set
- non-goals:
  - Garmin connect still may happen on dashboard

### Slice FP-3: Garmin Guided Onboarding
- purpose:
  - remove the dead end between auth completion and Garmin connection
- boundary:
  - provider onboarding becomes part of the product funnel
- likely files/modules:
  - [oauth.py](/home/dbarker/Code/fitness-pals.com/backend/app/auth/oauth.py)
  - [providers_garmin.py](/home/dbarker/Code/fitness-pals.com/backend/app/routes/providers_garmin.py)
  - new `welcome` page
- tests to add first:
  - auth callback redirects to guided route
  - Garmin callback redirects to guided route
  - Garmin connection state is visible in onboarding UI
- acceptance target:
  - user can complete login and Garmin connect without falling into raw JSON or a generic debug page
- rollback:
  - revert callbacks to current destinations
- non-goals:
  - first-value experience not yet implemented

### Slice FP-4: First Sync And First Win
- purpose:
  - show real product value immediately after the first Garmin sync
- boundary:
  - onboarding ends when insight begins
- likely files/modules:
  - onboarding summary service
  - [dashboard.js](/home/dbarker/Code/fitness-pals.com/frontend/pages/dashboard.js)
  - metrics/read-model endpoints
- tests to add first:
  - synced user sees latest activities and one insight
  - empty-state behavior remains safe
- acceptance target:
  - first sync leads to visible value, not just “sync complete”
- rollback:
  - fall back to current dashboard summary rendering
- non-goals:
  - not a full dashboard redesign

### Slice FP-5: Trust, Explainability, And Publish Hardening
- purpose:
  - make the public page credible, measurable, and durable in production
- boundary:
  - trust and product explanation become first-class public product features
- likely files/modules:
  - public front-page source
  - production publish contract on `orin`
  - smoke checks
- tests to add first:
  - trust section renders required copy
  - explainability preview renders
  - smoke checks cover homepage and sample artifact links
- acceptance target:
  - public page is production-ready and directly supports the onboarding funnel
- rollback:
  - preserve the prior front page while disabling new modules
- non-goals:
  - not a full CMS or marketing platform

## Recommended Issue List
These should be created as separate issues/MMFs.

1. `Front page CTA realignment to actual auth and sample artifact flow`
2. `Session-aware homepage with returning-user CTA states`
3. `Guided Garmin onboarding after login`
4. `First-sync first-value experience`
5. `Trust and explainability module for public homepage`
6. `Public-site deployment path for repo-owned homepage on orin`

## Definition Of Done For This Workstream
A slice in this front-page program is not done unless:
- it is merged to `main`
- it links to exactly one issue
- it has tests added first or updated first
- CTA behavior is verified in the real runtime
- `orin` publish behavior is verified where public behavior is involved
- this document is updated if the plan changes materially

## Strong Recommendation
Do not lead with brand polish alone.

Lead with:
- trust
- real onboarding
- real provider connection
- real sample outputs
- real first value

That is the shortest path from “interesting page” to “serious product.”
