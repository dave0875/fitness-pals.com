# Athlete Orbit Phase 4: Goal Graph

Phase 4 adds a canonical athlete-owned Goal Graph without replacing the existing `AthleteGoal` root used by Today and onboarding.

## Canonical boundary

- `AthleteGoal` remains the backwards-compatible current-focus root.
- `AthleteGoalEvent` stores stable primary/supporting event identity, date, target fields, priority, lifecycle, and provenance.
- `AthleteGoalObjective` stores intermediate objectives, optional event linkage, priority, lifecycle, and provenance.
- Promoting a new planned primary event demotes the previous one to supporting rather than deleting history.
- Completed, cancelled, and archived nodes remain historical graph nodes but cannot become the active primary event.
- Existing event-like singleton goal data is migrated into a primary event without deriving target time from free text.
- Legacy Today/onboarding writes materialize or update the compatibility primary event.

## Truth semantics

Athlete-entered event and objective fields are explicit. Days-to-event/objective are derived calendar relationships and are labeled derived. Missing date, distance, performance, or target time stays unknown.

The Goal Graph does not predict finish time, readiness, race probability, or causality.

## Product consumers

The same bounded graph is exposed through Athlete State, canonical metrics, Today context, Progress, and athlete intelligence/Coach context. Coach receives summaries and identifiers, never raw FIT history.

## Rollback

Revert the Phase 4 code and migration. The downgrade removes only Goal Graph child tables; the existing `athlete_goals` root, Today plans, canonical activity history, recovery data, and training evidence remain intact.
