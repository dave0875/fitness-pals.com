# Canonical athlete future intent

Athlete Orbit Phase 3 treats the existing user-owned `AthleteGoal` row as the durable source for current future intent. It does not create a second onboarding, race, or planning truth model.

## Explicit versus derived

Goal type, phase, target date, distance text, performance text, custom goal text, and structured target time are athlete-explicit fields. The canonical read model labels their provenance as `explicit` and identifies the `athlete_goal` record.

Calendar facts such as days to target are derived from an explicit target date and the read time. They are labeled `derived` and carry a caveat that they are not a finish-time, readiness, or race-outcome prediction.

A free-text performance target such as “3:15” or “break 3:15” is never parsed into a structured target time. `target.time_seconds` remains null unless the athlete explicitly supplied the structured field.

## Lifecycle

The current record exposes its actual created/updated timestamps and the lifecycle state `current`. Fitness Pals does not invent historical goal versions from an in-place update. Legacy SyncJob goal payloads may still support historical Progress attribution, but they are not the canonical current future-intent source.

## Product boundary

Athlete State exposes future intent as a sibling of recovery and whole-training evidence. Canonical metrics, Today context, Coach intelligence, and Progress consume the same bounded read model. Progress may place observed training beside current intent, but it must not imply causation or predict the event outcome.

Drive/Fenix remains the durable Garmin history direction, the official Garmin FIT SDK remains the decoder, and no raw FIT stream is part of future intent.
