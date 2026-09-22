const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

test("Coach persists durable threads and represents them in the URL", () => {
  const coach = read("pages/coach.js");
  assert.ok(coach.includes('authenticatedJson("/api/chat/threads")'));
  assert.ok(coach.includes("router.query.thread"));
  assert.ok(coach.includes("threadId"));
  assert.ok(coach.includes('{ pathname: "/coach", query: { thread: data.thread.id } }'));
  assert.match(coach, /Saved Coach conversations|Conversations/);
});

test("Coach carries visible removable context and activity evidence", () => {
  const coach = read("pages/coach.js");
  const activity = read("pages/activities/[id].js");
  assert.ok(coach.includes("contextFromQuery"));
  assert.match(coach, /Talking about:/);
  assert.match(coach, /Remove Coach context/);
  assert.ok(coach.includes('"/context"'));
  assert.match(activity, /Ask Coach about this workout/);
  assert.ok(activity.includes("activity: activity.id"));
});

test("Coach exposes evidence classes and a retryable failed turn", () => {
  const coach = read("pages/coach.js");
  for (const label of [
    "Measured fact",
    "Derived metric",
    "Estimate / model output",
    "Coaching interpretation",
  ]) {
    assert.ok(coach.includes(label), "expected evidence label " + label);
  }
  assert.match(coach, /Evidence and limits/);
  assert.match(coach, /Retry this question/);
  assert.ok(coach.includes("retry_turn_id"));
});

test("Coach mutations use the existing saved Today-plan action contract", () => {
  const coach = read("pages/coach.js");
  const backend = fs.readFileSync(
    path.join(root, "..", "backend", "app", "routes", "chat.py"),
    "utf8"
  );
  assert.ok(coach.includes('action.kind !== "mutation"'));
  assert.ok(coach.includes("authenticatedJson(action.href"));
  assert.ok(backend.includes('endpoint = f"/api/today-plan/{plan[\'id\']}"'));
  assert.ok(backend.includes('"action": "accept"'));
  assert.ok(backend.includes('"action": "skip"'));
});

test("Today delegates free-form coaching to the durable Coach workspace", () => {
  const today = read("pages/dashboard.js");
  assert.ok(!today.includes('authenticatedJson("/api/chat"'));
  assert.ok(today.includes("/coach?from=%2Ftoday"));
  assert.match(today, /Open Coach workspace/);
});

test("Coach workspace has narrow-screen layout coverage", () => {
  const css = read("styles/AthletePages.module.css");
  assert.ok(css.includes(".coachWorkspace"));
  assert.match(css, /@media \(max-width: 720px\)[\s\S]*\.coachWorkspace/);
  assert.ok(css.includes(".suggestionRow button"));
});
