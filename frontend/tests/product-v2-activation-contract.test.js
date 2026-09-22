const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("activation supports flexible athlete intent without a questionnaire wall", () => {
  const welcome = read("pages/welcome.js");

  for (const goal of [
    "race",
    "consistency",
    "aerobic_fitness",
    "recovery",
    "healthy_activity",
    "other",
    "not_sure",
  ]) {
    assert.ok(welcome.includes(`"${goal}"`), `expected ${goal} activation intent`);
  }
  assert.match(welcome, /I’m not sure|I'm not sure/);
  assert.match(welcome, /target distance/i);
  assert.match(welcome, /target performance/i);
  assert.match(welcome, /current training phase/i);
  assert.match(welcome, /another goal/i);
});

test("established athletes bypass Welcome from durable activation truth", () => {
  const welcome = read("pages/welcome.js");

  assert.ok(welcome.includes("activation?.requires_activation === false"));
  assert.ok(welcome.includes("router.replace"));
  assert.ok(welcome.includes('activation.resume_href || "/today"'));
  assert.ok(welcome.includes('router.query.edit !== "intent"'));
});

test("activation provides progressive value and a contextual Coach continuation", () => {
  const welcome = read("pages/welcome.js");

  assert.match(welcome, /usable_partial/);
  assert.match(welcome, /Continue with Coach/i);
  assert.match(welcome, /activation\?\.coach_handoff\?\.href/);
  assert.match(welcome, /while.*import|import.*while/i);
  assert.ok(!welcome.includes('secondaryHref="/dashboard"'));
});

test("Settings consumes the same activation action contract instead of inventing provider actions", () => {
  const settings = read("pages/settings.js");

  assert.ok(settings.includes("connection.href"));
  assert.ok(settings.includes("connection.enabled"));
  assert.match(settings, /Training intent/i);
  assert.ok(settings.includes("/welcome?edit=intent"));
});

test("Coach carries a safe activation prompt into the durable Phase 3 composer", () => {
  const coach = read("pages/coach.js");

  assert.ok(coach.includes("router.query.prompt"));
  assert.ok(coach.includes("setMessage"));
  assert.ok(coach.includes("safeCoachPrompt"));
  assert.ok(coach.includes("threadId"));
  assert.ok(coach.includes("router.query.thread"));
});

test("activation UI avoids infrastructure implementation language", () => {
  const welcome = read("pages/welcome.js").toLowerCase();

  for (const forbidden of [
    "service account",
    "environment variable",
    "worker topology",
    "database",
    "garmin_client_id",
    "garmin_client_secret",
  ]) {
    assert.equal(welcome.includes(forbidden), false, `must not expose ${forbidden}`);
  }
});
