const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const dashboardSource = fs.readFileSync(path.join(__dirname, "..", "pages", "dashboard.js"), "utf8");

test("Today CTA opens the concrete Today's run plan", () => {
  assert.ok(dashboardSource.includes('id="todays-run"'));
  assert.ok(dashboardSource.includes("/today#todays-run"));
  assert.ok(!dashboardSource.includes('href="/dashboard#coach"'));
});

test("Today supports the complete persisted coaching loop", () => {
  for (const contract of [
    'authenticatedJson("/api/today-plan")',
    'authenticatedJson("/api/today-plan/goal"',
    'action: "accept"',
    'action: "adjust"',
    'action: "skip"',
    'action: "complete"',
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
    "Why this session",
    "What is uncertain",
    "not a medical readiness score",
    "Post-race / recovery",
  ]) {
    assert.ok(dashboardSource.includes(copy), `expected Today's run copy: ${copy}`);
  }
  assert.ok(!dashboardSource.includes("heart-rate zone"));
  assert.ok(!dashboardSource.includes("target pace"));
});
