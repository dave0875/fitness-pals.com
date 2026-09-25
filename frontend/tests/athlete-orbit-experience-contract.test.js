const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("shared Athlete Orbit story exposes one explainable release contract", () => {
  const source = read("components/AthleteOrbitStory.js");
  for (const contract of [
    'data-contract="athlete-orbit-story-v1"',
    "athlete_orbit_v1",
    "Goal context",
    "Next action",
    "Evidence freshness",
    "Why:",
    "Uncertainty or conflict:",
    "canonical Goal Graph + recovery + whole-training evidence",
    "provenance?.caveat",
  ]) {
    assert.ok(source.includes(contract), `expected shared Orbit contract: ${contract}`);
  }
  assert.ok(!source.includes("readiness score"));
  assert.ok(!source.includes("race prediction"));
});

test("Today, Progress, and Coach render the same shared decision story", () => {
  const dashboard = read("pages/dashboard.js");
  const progress = read("pages/journey.js");
  const coach = read("pages/coach.js");

  assert.ok(dashboard.includes("AthleteOrbitStory"));
  assert.ok(dashboard.includes("todayContext?.decision || home?.decision"));
  assert.ok(
    progress.includes(
      '<AthleteOrbitStory decision={journey?.decision} surface="Progress" />'
    )
  );
  assert.ok(coach.includes("decision={intelligence?.decision || home?.decision}"));
  assert.ok(!dashboard.includes("home?.readiness"));
  assert.ok(!dashboard.includes("home.coaching.next_action"));
});

test("production acceptance publishes an explicit Phase 6 experience contract", () => {
  const smoke = read("../scripts/smoke_production.py");
  assert.ok(smoke.includes("_validate_experience_acceptance"));
  assert.ok(smoke.includes('"experience_contract": "pass"'));
  assert.ok(smoke.includes('data-contract="athlete-orbit-story-v1"'));
  assert.match(smoke, /visible story is traceable/i);
});
