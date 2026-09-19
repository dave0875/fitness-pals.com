# Today's run coaching loop

This MMF stores one explicit athlete goal and one current next-session decision. The goal includes a phase (`build`, `maintenance`, or `recovery`) and an optional target date, so post-race recovery is representable without inferring a goal from an old race.

The recommendation uses only account-owned canonical run records. Its time and distance ranges are scaled from the athlete's latest valid run durations and distances, and it cites the two newest sessions directly. The athlete can accept, adjust, skip, or complete the recommendation with perceived-effort feedback; the next recommendation cites that feedback, while completed and skipped plans expose a transition back to a new decision.

## Data-trust dependency

This slice consumes the canonical distance validator and the per-signal freshness contract delivered by issue #217 / PR #218. It deliberately does not repair Garmin sentinel distances, re-aggregate fitness data, or infer readiness from activity consistency. Stale or missing workout, sleep, and intensity signals appear as uncertainty and are not used as proof of readiness.

## State transitions

`recommended` → `adjusted` or `accepted` or `skipped`

`adjusted` → `accepted` or `completed` or `skipped`

`accepted` → `adjusted` or `completed` or `skipped`

`completed` or `skipped` → a new `recommended` decision

## Rollback

Revert the feature commit and migration. The new tables are isolated from canonical activity, sleep, ingestion, and dossier records, so rollback does not rewrite account fitness history.
