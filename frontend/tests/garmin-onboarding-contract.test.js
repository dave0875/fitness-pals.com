const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repositoryRoot = path.join(__dirname, "..", "..");
const read = (relativePath) =>
  fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8");

test("welcome connects the athlete directly to Garmin", () => {
  const welcome = read("frontend/pages/welcome.js");

  assert.ok(welcome.includes("/api/providers/garmin/login?next=/welcome"));
  assert.ok(welcome.includes("/import/garmin-archive"));
  assert.ok(welcome.includes("Connect Garmin"));
  assert.ok(welcome.includes("Authorize Fitness Pals through Garmin"));
  assert.ok(welcome.includes("official Activity API is not yet configured"));
  assert.ok(!welcome.toLowerCase().includes("pulsai"));
});

test("homepage and onboarding API use Garmin as the primary provider", () => {
  const homepage = read("frontend/pages/index.js");
  const onboarding = read("backend/app/routes/onboarding.py");

  assert.ok(!homepage.toLowerCase().includes("pulsai"));
  assert.ok(onboarding.includes('"garmin_connected"'));
  assert.ok(onboarding.includes('provider="garmin"'));
  assert.ok(onboarding.includes("_enqueue_garmin_sync_job"));
  assert.ok(!onboarding.toLowerCase().includes("pulsai"));
});
