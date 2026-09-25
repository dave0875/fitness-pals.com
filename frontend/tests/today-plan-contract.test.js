const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const dashboardSource = fs.readFileSync(path.join(__dirname, "..", "pages", "dashboard.js"), "utf8");

test("Today pairs the persisted run plan with the canonical Athlete Orbit decision", () => {
  assert.ok(dashboardSource.includes('id="todays-run"'));
  assert.ok(dashboardSource.includes("AthleteOrbitStory"));
  assert.ok(dashboardSource.includes("todayContext?.decision || home?.decision"));
  assert.ok(!dashboardSource.includes("home.coaching.next_action"));
  assert.ok(!dashboardSource.includes('href="/dashboard#coach"'));
});

test("Today supports the complete persisted coaching loop", () => {
  for (const contract of [
    'authenticatedJson("/api/today-plan")',
    'authenticatedJson("/api/today-plan/context")',
    'authenticatedJson("/api/today-plan/goal"',
    'action: "accept"',
    'action: "adjust"',
    'action: "move"',
    'action: "skip"',
    'action: "complete"',
    'matched_activity_id',
    'authenticatedJson("/api/today-plan/next"',
  ]) {
    assert.ok(dashboardSource.includes(contract), `expected Today contract: ${contract}`);
  }
});

test("Today explains evidence and uncertainty without invented zones", () => {
  for (const copy of [
    "Session purpose",
    "Time or distance",
    "Effort",
    "Why this decision",
    "What is uncertain",
    "not a medical readiness score",
    "Post-race / recovery",
  ]) {
    assert.ok(dashboardSource.includes(copy), `expected Today's run copy: ${copy}`);
  }
  assert.ok(!dashboardSource.includes("heart-rate zone"));
  assert.ok(!dashboardSource.includes("target pace"));
});


test("Today makes the decision loop visually and semantically dominant", () => {
  const decisionIndex = dashboardSource.indexOf('id="todays-run"');
  const supportIndex = dashboardSource.indexOf('id="journey"');
  assert.ok(decisionIndex >= 0 && supportIndex >= 0 && decisionIndex < supportIndex);
  for (const copy of [
    "Your next decision",
    "Rolling week",
    "Goal trajectory inputs",
    "Modify",
    "Move",
    "Finish the loop",
    "Ask Coach about this decision",
  ]) {
    assert.ok(dashboardSource.includes(copy), `expected Phase 4 Today copy: ${copy}`);
  }
});

test("Today confirms a canonical match instead of auto-completing it", () => {
  assert.ok(dashboardSource.includes("Possible completed run found"));
  assert.ok(dashboardSource.includes("Confirm run and save feedback"));
  assert.ok(dashboardSource.includes("Report completion manually"));
  assert.ok(dashboardSource.includes("todayContext.match.id"));
  assert.ok(!dashboardSource.includes("auto-complete"));
});
