const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Coach opens with explainable athlete intelligence instead of a generic greeting", () => {
  const coach = read("pages/coach.js");
  assert.ok(coach.includes('authenticatedJson("/api/intelligence")'));
  assert.match(coach, /Athlete intelligence/);
  assert.match(coach, /What changed\?/);
  assert.match(coach, /Athlete-to-self/);
  assert.match(coach, /Goal trajectory/);
  assert.match(coach, /Inputs, not a readiness score or prediction/);
});

test("Coach labels hypotheticals, N-of-1 associations, and generated views truthfully", () => {
  const coach = read("pages/coach.js");
  assert.match(coach, /Hypothetical questions are labeled as projections, not observed facts/);
  assert.match(coach, /N-of-1 association/);
  assert.match(coach, /do not establish causation/);
  assert.match(coach, /Coach-generated view/);
  assert.match(coach, /paired observations/);
});

test("Coaching memory is deliberate and can be saved or cleared", () => {
  const coach = read("pages/coach.js");
  assert.ok(coach.includes('"/api/intelligence/preferences"'));
  assert.ok(coach.includes('method: "PATCH"'));
  assert.match(coach, /you deliberately want Coach to remember/i);
  assert.match(coach, /Save preferences/);
  assert.match(coach, /Clear saved preferences/);
});

test("Coach backend attaches bounded intelligence, preferences, and scenario context", () => {
  const backend = fs.readFileSync(
    path.join(root, "..", "backend", "app", "routes", "chat.py"),
    "utf8"
  );
  assert.ok(backend.includes('metrics["athlete_intelligence"]'));
  assert.ok(backend.includes('metrics["coaching_preferences"]'));
  assert.ok(backend.includes('metrics["scenario"]'));
  assert.ok(backend.includes("build_scenario_context(question)"));
  assert.match(backend, /Association does not establish causation/);
});

test("Phase 7 production smoke protects the read-only intelligence path", () => {
  const smoke = read("../scripts/smoke_production.py");
  assert.ok(smoke.includes("/api/intelligence"));
  assert.ok(smoke.includes('"briefing"'));
  assert.ok(smoke.includes('"trajectory"'));
  assert.ok(smoke.includes('"associations"'));
  assert.ok(smoke.includes('"preferences"'));
});
