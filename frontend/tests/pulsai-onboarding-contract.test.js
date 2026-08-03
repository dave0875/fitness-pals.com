const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const repositoryRoot = path.join(__dirname, "..", "..");
const read = (relativePath) =>
  fs.readFileSync(path.join(repositoryRoot, relativePath), "utf8");

test("welcome connects the athlete through PulsAI without exposing the private endpoint", () => {
  const welcome = read("frontend/pages/welcome.js");

  assert.ok(welcome.includes("/api/providers/pulsai/connection"));
  assert.ok(welcome.includes("https://pulsai.me"));
  assert.ok(welcome.includes('type="password"'));
  assert.ok(welcome.includes('autoComplete="off"'));
  assert.ok(!welcome.includes("/api/providers/garmin/login"));
  assert.ok(!welcome.includes('localStorage.setItem("pulsai'));
  assert.ok(!welcome.includes("URLSearchParams"));
});

test("homepage and onboarding API use PulsAI as the primary provider", () => {
  const homepage = read("frontend/pages/index.js");
  const onboarding = read("backend/app/routes/onboarding.py");

  assert.ok(!homepage.includes("/api/providers/garmin/login"));
  assert.ok(onboarding.includes('"pulsai_connected"'));
  assert.ok(onboarding.includes('provider="pulsai"'));
  assert.ok(!onboarding.includes("providers_garmin"));
  assert.ok(!onboarding.includes("enqueue_garmin_sync_job"));
});
