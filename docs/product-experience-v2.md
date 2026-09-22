# Fitness Pals Product Experience V2

Status: Phase 0 architecture and UX reality audit  
Baseline: `main@4453c8f3fad44d3dc744d0650997a0860e3d201d`  
Issue: #233  
Phase-0 branch: `feat/product-experience-v2-phase0`

## 1. Executive diagnosis

Fitness Pals already contains much of the domain machinery needed for a differentiated endurance product: canonical athlete history, activity detail, per-signal freshness, Garmin ingestion, Google Drive archive import, dossiers, a persisted Today's Run lifecycle, goals, and a coaching endpoint. The main product problem is not absence of features. It is that the features still present themselves as separate implementation-era destinations rather than one continuous athlete workflow.

The highest-impact problems are:

1. **Coach is not yet the interface.** The authenticated shell labels Coach as a primary destination, but it is only an anchor into a card on `/dashboard` (`/dashboard#coach`). The dashboard chat stores one response in component state, with no visible thread/history model. Activity detail has no first-class "Ask Coach about this" action.
2. **The navigation exposes the underlying page decomposition.** Home, Journey, Activities, Dossiers, Coach, and Settings are shown as six peers even though Activities is an anchor into Journey and Coach is an anchor into Dashboard. The user must learn the application topology before learning about their training.
3. **Returning authentication still routes through onboarding semantics.** The public landing page's default sign-in return path is `/welcome`. A fully synced athlete reaching `/welcome` is shown a "First win" state and then offered a link to the dashboard instead of being taken directly to current personal value.
4. **The dashboard is overloaded.** It currently combines training trend, readiness, recovery signals, Today's Run, recent activities, dossier state, and coach chat. This makes the page simultaneously a home, a plan editor, an analytics summary, a report launcher, and a chat surface.
5. **Connection repair is separated from the task that exposed the problem.** Dashboard "Review connection" routes to `/welcome`; Settings exposes connection/archive actions; archive import is its own route. The underlying capabilities are increasingly truthful after PR #223/#225, but the recovery experience is still spread across several mental models.
6. **Reports are a product noun when they should usually be an outcome.** Dossiers have strong lifecycle/provenance semantics, but "Dossiers" competes for top-level navigation attention with immediate training decisions and conversation.
7. **The application has improved data truth faster than interaction truth.** PRs #218, #221, #223, and #225 materially improved canonical data validation, goal-aware planning, capability states, lifecycle recovery, and Google Drive authorization. Product V2 should preserve those contracts while reorganizing the experience around athlete intent.

The recommended north star is therefore validated with one refinement:

> **Talk → understand → decide → act → train → learn → repeat.**

Coach should be the connective tissue, but not the only interface. Fast structured actions should remain available without requiring conversation. Conversation and structured UI must operate on the same saved goals, plans, activities, filters, jobs, and evidence.

## 2. Evidence and audit boundary

This audit uses current source on the baseline commit, current open issue contracts, recently merged implementation PRs, and the latest successful merge-triggered deployment.

Latest verified trunk deployment evidence:

- GitHub Actions run `35671256184`, commit `4453c8f3fad44d3dc744d0650997a0860e3d201d`, conclusion: success.
- `Lint & Test`: success.
- `Deploy to Dev`: success, including complete runtime smoke and external Cloudflare ingress.
- `Deploy to Prod`: success, including complete production runtime smoke and `Verify public production journey`.
- The production smoke mints an ephemeral athlete token and verifies authenticated product API reachability including Journey.

The deployment smoke proves deployability and route/API reachability, not the quality of every browser interaction. The recent production navigation audit captured in #222 remains relevant UX evidence, while this document independently reconciles it against current source after PRs #223 and #225.

Primary source surfaces reviewed:

- `frontend/components/AuthenticatedShell.js`
- `frontend/pages/index.js`
- `frontend/pages/welcome.js`
- `frontend/pages/dashboard.js`
- `frontend/pages/journey.js`
- `frontend/pages/activities/[id].js`
- `frontend/pages/dossiers/index.js`
- `frontend/pages/settings.js`
- `frontend/pages/import/garmin-archive.js`
- current frontend contract tests
- #32, #116, #189, #220, #222
- merged PRs #218, #219, #221, #223, #225

## 3. Current journey map and action audit

| Surface | Current primary intent/action | Current result | UX assessment | V2 direction |
| --- | --- | --- | --- | --- |
| Public `/` anonymous | Continue with Gmail | `/auth/login?next=/welcome` | Works, but all returning signed-out athletes are routed into onboarding semantics | Resolve identity first, then route established athletes directly to Today/Coach |
| Public `/` authenticated + synced | Open dashboard | `/dashboard` | Works | Rename/reframe destination as current athlete experience rather than "dashboard" |
| `/welcome` unauthenticated | Continue with Gmail | auth with `next=/welcome` | Works | Preserve only for new/incomplete activation |
| `/welcome` no Garmin | Connect Garmin | provider login callback to Welcome | Works | Keep, but explain value and permissions in athlete language |
| `/welcome` no/partial history | Import Garmin archive / first sync | archive route or queued sync | Capability logic is increasingly truthful | Let partial history produce value while deeper import continues |
| `/welcome` synced | First win → dashboard | explicit extra click | Functional but unnecessary for established athletes | Bypass Welcome after authentication when usable canonical data already exists |
| Authenticated shell | Home | `/dashboard` | Works | Become Today or unified athlete home |
| Authenticated shell | Journey | `/journey` | Works | Fold into Progress unless a distinct timeline proves necessary |
| Authenticated shell | Activities | `/journey#activities` | Anchor masquerades as a peer destination | Use real Training route/view with URL-backed state |
| Authenticated shell | Dossiers | `/dossiers` | Works but exposes internal artifact concept as primary | Move to reports/deep analysis under Progress and Coach |
| Authenticated shell | Coach | `/dashboard#coach` | Anchor masquerades as a peer destination | Dedicated Coach workspace plus global Ask Coach affordance |
| Dashboard | What happened / where now / next | several cards on one page | Useful data but too many product roles | Today should emphasize current change, goal position, and one decision |
| Dashboard | Today's run | persisted goal/plan actions | Strong underlying lifecycle from PR #221 | Keep same state model, simplify presentation, make conversation operate on same plan |
| Dashboard | Latest activities | summary list + Review connection | Review connection points to Welcome | Route repair to contextual connection state, not onboarding |
| Dashboard | Coaching dossier | generated artifact/library action | Works | Surface as deeper analysis, not a primary noun |
| Dashboard | Ask your coach | one message → one response | Functional endpoint, but no durable conversation UX | Persistent thread, evidence links, context handoff, failure retry |
| Journey | filters | query-backed API request | Good foundation | Preserve URL-backed filters in Progress/Training |
| Journey | weekly/monthly summaries | analytics display | Useful but navigation-heavy | Use progressive disclosure and goal-aware defaults |
| Journey | dossier handoff | opens dossier lifecycle | Works | "Analyze this period" should naturally hand context to Coach/report generation |
| Journey | Activities | activity list + pagination | Improved by PR #223 | Move into first-class Training view |
| Activity detail | Inspect workout | summary, completeness, provenance | Truthful foundation | Add splits/trends/comparisons and Ask Coach with attached activity |
| Dossiers | Generate/retry/open | persisted lifecycle | Strong lifecycle model | Reframe as saved deep analyses/reports; keep private/versioned behavior |
| Settings | Fitness connection | refresh/reconnect/sync/review | Improved truthfulness, but still narrow | Expand per #116 into Profile, Goals, Connections, Coaching, Data & Privacy, Account |
| Settings | Review existing activities | `/journey#activities` | Anchor coupling | Link to real Training view |
| Settings | Historical Garmin archive | `/import/garmin-archive` | Works | Keep as a Connections detail/recovery flow |
| Archive import | Google Drive import | capability-dependent action | Improved by #223/#225 | Preserve truthful capability state and persisted job recovery |
| Archive import | Upload export ZIP | import job | Works | Secondary recovery/import path, not part of normal daily UX |
| Logout | Sign out | `/auth/logout` | Works | Preserve; return path after future login must be safe and task-aware |

## 4. What is broken vs confusing vs architectural

### Broken or incomplete interaction contracts

- Coach has no durable visible conversation/thread model on the current page.
- Coach and Activities are presented as top-level navigation destinations but resolve to anchors.
- Returning signed-out athletes default through `/welcome`, even when their canonical history is already usable.
- Current activity detail cannot carry the athlete directly into a contextual coaching discussion.
- Recovery from data/connection problems can redirect athletes to a conceptually unrelated onboarding surface.

### Confusing but functional

- "Home", "Journey", "Activities", and "Dossiers" overlap in what they mean to an athlete.
- "Dashboard" describes software organization, not athlete intent.
- "Dossier" is implementation/product language rather than a task an athlete wakes up wanting to do.
- Settings currently emphasizes connection operations but the open #116 contract expects a much broader athlete settings model.
- Freshness/status exists across product surfaces but is not yet a single human vocabulary across the whole application.

### Architectural UX problems

- Multiple product surfaces independently expose the same underlying goal, connection, freshness, and training-history concepts.
- Chat is embedded in Dashboard instead of being a durable application context.
- The product hierarchy is page-first rather than intent-first.
- The application requires navigation before natural-language investigation can begin.
- Deep analysis is modeled as a separate library before it is modeled as a response to an athlete question.

### Polish issues

- Welcome/public surfaces use substantial inline styling while authenticated areas increasingly use shared CSS modules.
- The experience has several card types and page-local patterns that should converge on a shared system.
- Mobile and accessibility requirements exist piecemeal in issue contracts but need to be product-wide acceptance gates.

## 5. Product north star

A returning athlete should authenticate and immediately reach a personal, current training story.

Within roughly one screen the athlete should understand:

1. **What changed?** The one or two meaningful changes since the athlete last engaged.
2. **Where am I relative to my goal?** Goal/phase and the most relevant evidence, not an opaque score.
3. **What should I do next?** One dominant training or recovery decision when evidence supports it.
4. **Why?** A concise explanation with expandable evidence and uncertainty.
5. **What can I ask?** A visible Coach entry with suggested questions grounded in the current state.

The core loop is:

**Talk → understand → decide → act → train → learn → repeat**

Structured UI and Coach must be alternate controls over the same domain state. There must never be a "chat plan" and a separate "dashboard plan."

## 6. Proposed information architecture

### Primary authenticated navigation

1. **Today**
   - current goal/phase
   - what changed
   - next training decision
   - concise recovery/data caveats
   - immediate Coach entry
2. **Coach**
   - durable conversation threads
   - contextual questions
   - evidence cards
   - structured actions that mutate the same saved plan/goal state
3. **Progress**
   - goal trajectory
   - longitudinal training/recovery trends
   - comparisons
   - saved deep analyses/reports
4. **Training**
   - activity calendar/list
   - activity detail
   - filters/search
   - plan/completion relationship
5. **Account menu**
   - Profile
   - Goals
   - Connections
   - Coaching preferences
   - Data & privacy
   - Account/session

### Legacy concept mapping

| Current concept | V2 home |
| --- | --- |
| `/dashboard` | Today, initially with compatibility redirect/alias |
| Journey | Progress |
| Activities | Training |
| Dossiers | Saved analyses/reports under Progress and Coach |
| Coach anchor | Dedicated Coach route |
| Settings | Account/settings sections |
| Welcome | Activation only for new/incomplete athletes |
| Garmin archive | Connections detail/import recovery |

Legacy URLs should remain functional through explicit redirects or compatibility routes during migration. Bookmarks must not fail silently.

## 7. Authentication and activation model

### Returning athlete

1. User requests a protected route or signs in from the public front door.
2. Authentication preserves a safe requested return path.
3. After identity resolution, the product checks athlete activation state.
4. If usable canonical history exists, route directly to the requested destination or Today.
5. Connection repair is requested only if the athlete's intended task truly requires it.
6. Session expiry preserves the pending task/context and returns the athlete there after reauthentication.

A returning athlete must not be forced through Welcome because onboarding metadata is incomplete while usable canonical data already exists.

### New/incomplete athlete

Collect only what cannot be inferred:

1. Goal/intention, supporting uncertainty ("I'm not sure yet").
2. Source authorization or truthful import option.
3. Show partial value as soon as any usable history exists.
4. Finish activation with a personalized observation/question that continues directly into Coach or Today.

Activation completion is **first useful value**, not "setup complete."

## 8. Conversation interaction model

### Dedicated Coach

Coach becomes a real route with durable thread state. The first screen should already know:

- current goal and phase;
- selected target date/event if any;
- recent meaningful training;
- available recovery signals and their freshness;
- one current training question worth discussing.

Avoid generic greetings that could apply to anyone.

### Global Ask Coach

All authenticated surfaces expose a consistent Ask Coach action. The context envelope may include:

- source route;
- activity ID;
- selected date/window;
- selected goal;
- selected metric/trend;
- current plan ID.

Context is visible and removable by the athlete, e.g. "Talking about: Bronx 10 Mile · Sep 19."

### Evidence-native response model

A substantive coaching answer should be able to distinguish:

- measured fact;
- derived/calculated metric;
- estimate/model output;
- coaching interpretation.

Evidence should deep-link back to the supporting activity/window/report. Default prose stays concise; evidence expands on demand.

### Conversation state

- Thread history survives route navigation and page reload.
- Follow-ups such as "Why?" resolve against thread/context.
- Leaving Coach to inspect evidence and returning does not discard the discussion.
- Failed model requests preserve the athlete's question and offer retry.
- Session expiry preserves a recoverable return to the thread.
- Structured actions from Coach use the same APIs/state transitions as buttons elsewhere.

## 9. URL and browser-state model

Meaningful state should be addressable.

- Dedicated routes for Today, Coach, Progress, Training, Settings.
- Activity detail remains a real route.
- Filterable Training/Progress state should use query parameters where it is useful to preserve/share/return.
- Chat thread identity should be represented by a stable route or route parameter when persistence is implemented.
- Browser back/forward must reverse user navigation rather than merely scrolling between pseudo-destinations.
- Anchors remain valid for in-page sections but are not presented as peer application destinations.
- Authentication `next` remains strictly validated against safe internal paths.

## 10. Product state vocabulary

Use the same semantics across Today, Coach, Progress, Training, Connections, and reports.

| State | Athlete-facing meaning | Required behavior |
| --- | --- | --- |
| Loading | We are retrieving saved state | Skeleton/progress; never blank page |
| Fresh | Relevant signal is current enough for this decision | May be used normally |
| Stale | Data exists but is older than the decision expects | Show data + caveat + refresh/reconnect path |
| Partial | Some relevant signals exist and others are missing/stale | Continue with available evidence and name limitation |
| Empty | No usable data exists for this view | Explain what unlocks value |
| Updating/importing | Background work is active | Persist job; navigation/refresh does not lose state |
| Failed | Background/read operation failed | Explain impact, preserve safe data, provide retry/recovery |
| Disconnected | Future provider updates cannot occur | Explain retained history vs future sync |
| Authorization expired | User action is required | Direct reconnect action, safe return to original task |
| Unavailable capability | Server/account cannot perform action | Disabled/hidden action with clear reason; never click-to-fail |
| Unknown metric | Metric is not known | Nullable/unknown, never numeric zero |

Freshness is per relevant signal when possible, e.g. Activities through Sep 21; Sleep through Sep 20; power available for 82% of runs in the selected period.

## 11. Design-system foundations

Phase 1 onward should converge touched surfaces onto shared primitives.

### Structure

- `AppShell`
- responsive primary navigation
- account menu
- page header
- section header
- breadcrumb/back affordance where task hierarchy requires it

### Actions

- primary button
- secondary button
- text action
- destructive action
- loading action
- unavailable action with reason
- contextual "Ask Coach"

### Content

- insight card
- evidence card
- metric/value card
- trend card
- plan card
- activity card
- status/freshness badge
- provenance disclosure
- empty state
- error/recovery state
- skeleton

### Conversation

- thread list/history
- message
- coach response
- evidence attachment
- context chip
- composer
- suggested question
- structured action chip
- retry/error state

### Forms

- field
- select
- date/goal input
- inline validation
- confirmation dialog
- destructive confirmation

No touched athlete-facing page should introduce new one-off inline visual systems unless a shared primitive is demonstrably inappropriate.

## 12. Mobile and accessibility requirements

Changed core flows target WCAG 2.2 AA.

Required acceptance coverage:

- complete keyboard operation;
- visible focus;
- semantic landmarks/headings;
- form labels and error associations;
- status/error announcements;
- dialogs with correct focus trapping/return;
- chart/table text alternatives;
- touch target sizing appropriate to mobile;
- no hover-only essential information;
- reduced-motion behavior;
- no critical meaning encoded only by color;
- mobile primary navigation that keeps Today and Coach easy to reach;
- composer usable with virtual keyboard;
- long activity lists performant on narrow devices.

## 13. Competitive principles

Fitness Pals should not win by maximizing metric density.

Relevant current patterns:

- Strava Athlete Intelligence demonstrates demand for activity-specific AI explanation and expandable "say more" analysis.
- Strava Fitness & Freshness emphasizes longitudinal trend interpretation and athlete-to-self comparison rather than treating one score as absolute truth.
- Runalyze Marathon Shape demonstrates value in goal-specific endurance modeling that combines weekly volume and long-run history.
- Apple HIG's 2026 principles emphasize purpose, agency, recovery, familiarity, simplicity, responsibility, and clear feedback.
- Google PAIR emphasizes understandable data permissions, user supervision of automation, control when automation fails, calibrated trust, and graceful failure.

Fitness Pals' differentiator should be the integration of those strengths:

**a stateful coach that can inspect the athlete's full canonical history, explain evidence, mutate the actual saved training decision, and recognize what happened next.**

## 14. Existing issue ownership reconciliation

### #32 Coaching chat

**Disposition:** keep as the backend/domain foundation for Phase 3, but update its implementation assumptions when worked.

- Preserve authenticated athlete isolation, bounded canonical context, freshness, rate limiting, deterministic tests.
- Remove obsolete PulsAI-specific wording/assumptions.
- Phase 3 owns durable conversation UX, context handoff, evidence links, retries, and thread persistence.
- #32 should not create a separate chat state model from Product V2.

### #116 Athlete settings/connections/data controls

**Disposition:** primary dependency/owner for Phase 6 settings work.

- Preserve its privacy/legal boundary with #226.
- Preserve tenant isolation, secret redaction, destructive confirmation, and audit requirements.
- Product V2 supplies the IA and shared state vocabulary.
- Do not create a second settings implementation.

### #189 Canonical/freshness-aware summaries

**Disposition:** data-trust prerequisite for Coach/Progress surfaces.

- Its canonical Postgres-only product read requirement remains correct.
- Product V2 must not paper over any remaining Influx-derived product truth.
- Complete/reconcile before relying on metrics summary or race-readiness inside Coach.

### #220 Today's Run coaching loop

**Disposition:** underlying feature is substantially implemented by merged PR #221; keep the issue as the acceptance/reconciliation owner until its final production behavior is explicitly validated/closed.

- Product V2 Phase 4 should reuse the persisted goal/plan lifecycle.
- Do not build a parallel recommendation model.
- Phase 4 changes presentation and extends the loop into the broader Today/Coach experience.

### #222 Truthful/recoverable core actions

**Disposition:** underlying feature is substantially implemented by merged PR #223; treat its capability/lifecycle contracts as mandatory Product V2 foundations.

- Phase 6 reuses capability state and recovery semantics.
- Phase 1/2 must not regress truthful actions.
- Close/reconcile #222 only after its current acceptance criteria are confirmed against deployed behavior; do not duplicate it.

### Recent merged contracts to preserve

- **#218:** validated canonical activity distances, per-signal freshness, truthful unknowns, readiness/consistency separation, activity date contract.
- **#219:** Python/Garmin metric repair follow-up.
- **#221:** goal-aware persisted Today's Run lifecycle and explicit uncertainty.
- **#223:** capability-aware core flows, job recovery, dossier eligibility refresh, Journey pagination.
- **#225:** athlete-scoped Google Drive OAuth Garmin import while retaining archive alternatives.

## 15. Success measures

The Product V2 program is successful only if the following become durable acceptance contracts:

1. Returning athlete authentication reaches meaningful personal value without an onboarding detour.
2. New athlete activation reaches personalized value with the minimum required questions.
3. Every primary action has a real destination or server outcome.
4. No enabled athlete action is known in advance to be incapable of succeeding.
5. No athlete-facing page exposes infrastructure credentials/configuration.
6. Significant coaching conclusions can reveal supporting athlete evidence.
7. Missing/stale/partial data is explicit and does not become zero.
8. Every recoverable error offers a recovery path.
9. Conversation context can survive navigation to supporting evidence and back.
10. Structured actions and Coach mutate the same saved goal/plan state.
11. Critical flows are keyboard accessible and usable at narrow mobile widths.
12. Long histories do not require fetching/rendering the entire archive for a summary.
13. Browser refresh/back/forward preserve or reverse meaningful state predictably.
14. Deployment smoke continues to verify public/authenticated production reachability after every merge.

## 16. Sequential Phase 1–8 plan

Every phase begins only after the previous phase is merged and all merge-triggered Actions on `main` succeed. Each branch is cut fresh from that then-green `main`.

### Phase 1 — Coherent application shell

Proposed branch: `feat/product-experience-v2-shell`

Outcome:
- Today / Coach / Progress / Training / account IA.
- Real Coach and Training destinations.
- compatibility redirects/aliases for legacy routes.
- global Ask Coach context handoff contract.
- safe auth return paths and session recovery.

Dependencies:
- current AuthenticatedShell;
- #114 behavior contract;
- truthful capability state from #223.

Independent value:
- removes navigation deception before deeper feature changes.

Acceptance:
- anonymous protected route → auth → original safe destination;
- returning login → personalized destination;
- all primary navigation works;
- no primary nav anchor-as-page;
- mobile/keyboard shell;
- old major URLs deliberately work or redirect.

### Phase 2 — Activation and first value

Proposed branch: `feat/product-experience-v2-activation`

Outcome:
- Welcome only for genuinely incomplete athletes.
- flexible goal handshake.
- partial-value experience during imports.
- persistent activation state/recovery.
- first useful observation flows into Coach/Today.

Dependencies:
- Phase 1 shell;
- current onboarding/provider/archive contracts;
- #223/#225 capability model.

Independent value:
- fixes authentication-to-value path without requiring new analytics.

Acceptance:
- established athlete bypasses onboarding;
- new athlete reaches personalized value with minimal steps;
- all activation states survive refresh/navigation.

### Phase 3 — Coach workspace

Proposed branch: `feat/product-experience-v2-coach`

Outcome:
- durable conversation threads;
- contextual Coach launch from any authenticated view;
- evidence-linked answers;
- retries and graceful model failure;
- same saved state/actions as structured UI.

Dependencies:
- Phase 1 context envelope;
- #32;
- #189 canonical/freshness contract.

Independent value:
- transforms coaching from dashboard card into product interaction layer.

Acceptance:
- goal question, activity question, selected-window question, freshness disclosure, follow-up context, evidence navigation/return, failure/retry, mobile.

### Phase 4 — Today and goal-aware decisions

Proposed branch: `feat/product-experience-v2-today`

Outcome:
- focused Today surface;
- one dominant next decision;
- rolling week;
- explainable goal trajectory inputs;
- full accept/modify/move/skip/complete/feedback loop integrated with Coach.

Dependencies:
- merged #221/#220 lifecycle;
- Phase 3 Coach.

Independent value:
- creates daily habit loop on existing persisted plan foundation.

Acceptance:
- goal → recommendation → explanation → modification → acceptance → matching completion → feedback → next decision.

### Phase 5 — Progress, Training, and evidence

Proposed branch: `feat/product-experience-v2-training-evidence`

Outcome:
- Progress longitudinal views;
- Training list/calendar for large histories;
- richer activity detail;
- athlete-to-self comparisons;
- Ask Coach from evidence;
- Dossiers reframed as saved deep analysis.

Dependencies:
- Phase 1 IA;
- Phase 3 context handoff;
- existing Journey/activity/dossier canonical APIs.

Independent value:
- makes coach conclusions inspectable and history efficient to navigate.

Acceptance:
- thousands-of-activities performance;
- URL-backed filters;
- activity detail truthfulness;
- Coach handoff/return;
- no unexplained Unknown when canonical value exists.

### Phase 6 — Connections, trust, and recovery

Proposed branch: `feat/product-experience-v2-trust`

Outcome:
- coherent Connections surface;
- consistent freshness vocabulary;
- job/error recovery;
- complete athlete Settings IA;
- data/provenance trust center.

Dependencies:
- #116;
- #189;
- #222/#223;
- #225.

Independent value:
- makes degraded upstream states understandable instead of derailing the product.

Acceptance:
- expired authorization, archive-only, pending sync, partial import, provider outage, failed import, stale sleep/fresh activities, duplicate input, empty account.

### Phase 7 — Athlete intelligence

Proposed branch: `feat/product-experience-v2-intelligence`

Outcome:
- "What changed?" briefing;
- athlete-to-self intelligence;
- explainable goal trajectory;
- hypothetical scenario conversation;
- deliberate coaching memory/preferences;
- N-of-1 associations;
- Coach-generated charts/views.

Dependencies:
- reliable Coach, Today, Progress, data-trust layers from Phases 3–6.

Independent value:
- differentiates Fitness Pals from dashboard-first competitors.

Acceptance:
- competitive scenario suite of at least 20 athlete questions answered directly, with evidence, from athlete-scoped canonical data, with truthful uncertainty.

### Phase 8 — Experience hardening

Proposed branch: `feat/product-experience-v2-hardening`

Outcome:
- whole-site action/link audit;
- automated critical E2E flows;
- WCAG 2.2 AA gate for changed core flows;
- performance budgets;
- privacy-safe UX telemetry;
- durable regression gates;
- deployed acceptance report.

Dependencies:
- all prior phases.

Independent value:
- converts the redesigned experience into an enforceable release contract.

Acceptance:
- new athlete, returning athlete, workout analysis, training decision, broken connection, failed job, and mobile journeys pass from the real front door.
- post-merge dev/prod Actions and production acceptance pass.

## 17. Serial execution rule

No downstream Product V2 branch should be pre-created.

For each phase:

1. confirm prior phase merge-triggered `main` Actions are terminal and successful;
2. capture the green `main` SHA;
3. create/reconcile exactly one MMF issue in a GitHub Project;
4. create the phase branch from that SHA;
5. TDD/implement only that phase;
6. open one PR referencing exactly that issue;
7. fix-forward until PR CI is green;
8. squash/rebase merge;
9. wait for all merge-triggered Actions;
10. if any required Action fails, repair via proper branch/PR workflow and do not advance;
11. only then mark the phase PASS and create the next branch.

"PR merged" is not synonymous with "Done."

## 18. Phase 1 handoff

Phase 1 should start by changing the application's navigation semantics without changing the underlying training algorithms:

- establish Today, Coach, Progress, Training, and account/settings as the authenticated IA;
- make Coach and Training real destinations;
- preserve legacy URLs;
- route returning authenticated athletes toward personal value;
- define the context envelope that later lets any evidence surface launch Coach;
- keep #221 plan state, #223 truthful capability state, and #218 data-truth contracts unchanged.

That slice is independently valuable and creates the stable skeleton for all subsequent Product V2 work.
