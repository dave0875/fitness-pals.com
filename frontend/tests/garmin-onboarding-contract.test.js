const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repositoryRoot = path.join(__dirname, "..", "..");
const read = (relativePath) =>
  fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8");

test("activation keeps Garmin implementation behind athlete-facing source actions", () => {
  const welcome = read("frontend/pages/welcome.js");

  assert.ok(welcome.includes("/import/garmin-archive") || welcome.includes("activation?.action"));
  assert.ok(!welcome.includes("GARMIN_CLIENT_ID"));
  assert.ok(!welcome.includes("service account"));
  assert.ok(!welcome.toLowerCase().includes("pulsai"));
});

test("onboarding API keeps canonical Garmin ingestion without PulsAI", () => {
  const homepage = read("frontend/pages/index.js");
  const onboarding = read("backend/app/routes/onboarding.py");

  assert.ok(!homepage.toLowerCase().includes("pulsai"));
  assert.ok(onboarding.includes('"garmin_connected"'));
  assert.ok(onboarding.includes('provider="garmin"'));
  assert.ok(onboarding.includes("_enqueue_garmin_sync_job"));
  assert.ok(!onboarding.toLowerCase().includes("pulsai"));
});
