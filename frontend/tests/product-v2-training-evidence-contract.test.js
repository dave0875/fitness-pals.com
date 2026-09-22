const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("Progress uses server-bounded evidence and athlete-to-self comparison", () => {
  const progress = read("pages/journey.js");
  assert.ok(!progress.includes("paginateActivities"));
  assert.ok(progress.includes("activity_page"));
  assert.ok(progress.includes("activity_page_size"));
  assert.ok(progress.includes("activity_pagination"));
  assert.match(progress, /Athlete-to-self/i);
  assert.match(progress, /Ask Coach about this window/i);
});

test("Training keeps filters and page state in the URL", () => {
  const training = read("pages/training.js");
  assert.ok(training.includes("useRouter"));
  assert.ok(training.includes("router.query.window"));
  assert.ok(training.includes("router.query.sport"));
  assert.ok(training.includes("router.query.goal"));
  assert.ok(training.includes("router.query.page"));
  assert.ok(training.includes("activity_page"));
  assert.ok(training.includes("activity_pagination"));
  assert.ok(!training.includes("paginateActivities"));
});

test("Activity detail exposes recent-self evidence and preserves return context", () => {
  const detail = read("pages/activities/[id].js");
  assert.ok(detail.includes("data.comparison"));
  assert.ok(detail.includes("router.query.page"));
  assert.match(detail, /Compared with your recent/i);
  assert.match(detail, /Ask Coach about this workout/i);
});

test("Dossiers are presented as saved analyses while the legacy route remains stable", () => {
  const dossiers = read("pages/dossiers/index.js");
  assert.match(dossiers, /Saved analyses/i);
  assert.ok(!dossiers.includes("<h1>Your coaching dossiers</h1>"));
  assert.ok(dossiers.includes("/api/dossiers"));
});

test("production smoke protects bounded Progress evidence contract", () => {
  const smoke = read("../scripts/smoke_production.py");
  assert.ok(smoke.includes("activity_page=1"));
  assert.ok(smoke.includes("activity_page_size=25"));
  for (const key of ["totals", "comparison", "activities", "activity_pagination"]) {
    assert.ok(smoke.includes(`"${key}"`), `expected smoke assertion for ${key}`);
  }
});
