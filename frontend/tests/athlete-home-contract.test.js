const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const dashboardSource = fs.readFileSync(path.join(__dirname, "..", "pages", "dashboard.js"), "utf8");

test("athlete home reads the canonical home contract", () => {
  assert.ok(dashboardSource.includes('authenticatedJson("/api/athlete-home")'));
  assert.ok(!dashboardSource.includes("/api/metrics/summary"));
  assert.ok(!dashboardSource.includes("JSON.stringify"));
});

test("athlete home answers happened, current state, and next action", () => {
  for (const label of ["What happened", "Where you are now", "What to do next", "Latest activities", "Coaching dossier"]) {
    assert.ok(dashboardSource.includes(label), `expected athlete home to include ${label}`);
  }
});

test("athlete home presents trustworthy data states", () => {
  for (const state of [
    "Loading your athlete home",
    "No training history yet",
    "Some signals are missing or stale",
    "Your data needs a refresh",
    "We could not load your athlete home",
    "Data through",
  ]) {
    assert.ok(dashboardSource.includes(state), `expected athlete home state copy: ${state}`);
  }
  assert.ok(dashboardSource.includes('role="status"'));
  assert.ok(dashboardSource.includes('role="alert"'));
});

test("athlete home preserves the V2 Today route for sign in", () => {
  assert.ok(dashboardSource.includes("/auth/login?next=%2Ftoday"));
});

test("athlete home follows the backend recovery or coaching destination", () => {
  assert.ok(dashboardSource.includes("href={home.coaching.next_action.href}"));
});

test("athlete home renders owner-scoped dossier lifecycle state", () => {
  assert.ok(dashboardSource.includes("home.dossier.action.href"));
  assert.ok(dashboardSource.includes("home.dossier.action.label"));
  assert.ok(dashboardSource.includes("home.dossier.data_through"));
  assert.ok(!dashboardSource.includes("hasJourneyContext"));
  assert.ok(!dashboardSource.includes("journeyContext"));
});
