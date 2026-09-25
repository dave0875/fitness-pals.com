# Athlete Orbit — Phase 6 Release Contract

Phase 6 closes Athlete Orbit by making the Phase 5 `athlete_orbit_v1` decision visibly consistent across the authenticated athlete experience.

## One athlete story

Today, Progress, and Coach render the same shared Athlete Orbit story. The story exposes:

- the active Goal Graph context;
- the canonical next action;
- training and recovery freshness;
- rationale;
- uncertainty or conflict;
- provenance back to Goal Graph, Athlete State recovery, and whole-training evidence.

Dashboard is the implementation behind Today, so it follows the same contract.

## Truth boundaries

The experience must not introduce a second readiness or recommendation source. Recovery values remain evidence, not a medical-readiness score. Unknown and stale values remain explicit. The product does not predict race outcomes or manufacture missing evidence.

## Release gate

Production acceptance is tied to the exact deployed SHA and requires:

1. the shared `data-contract="athlete-orbit-story-v1"` marker on Today, Progress, and Coach;
2. semantic equality of the canonical unified decision across Athlete State and product consumers;
3. traceable goal, recovery, and whole-training evidence;
4. explicit freshness, rationale, uncertainty/conflicts, and provenance;
5. all inherited Athlete Orbit contracts from Phases 1–5 to remain `pass`.

Only a terminal-green PR gate, merge-triggered Dev/Prod deployment, and SHA-tied production acceptance count as PASS.
