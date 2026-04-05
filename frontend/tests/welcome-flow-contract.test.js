const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const welcomeSource = fs.readFileSync(path.join(__dirname, "..", "pages", "welcome.js"), "utf8");

test("welcome page includes the core onboarding states", () => {
  assert.match(
    welcomeSource,
    /connect_garmin|ready_to_sync|sync_queued|synced/i,
    "expected welcome page to define honest onboarding states"
  );
});

test("welcome page supports connect, first sync, and first-win copy", () => {
  assert.ok(welcomeSource.includes("Connect Garmin"), 'expected "Connect Garmin" state');
  assert.ok(
    welcomeSource.includes("Import my training history"),
    'expected "Import my training history" state'
  );
  assert.match(
    welcomeSource,
    /latest 5 activities|latest activities/i,
    "expected latest activities preview copy"
  );
  assert.match(
    welcomeSource,
    /readiness preview|readiness insight/i,
    "expected readiness preview copy"
  );
});

test("welcome page calls onboarding and sync endpoints", () => {
  assert.ok(
    welcomeSource.includes("/api/auth/session"),
    "expected welcome page to probe /api/auth/session"
  );
  assert.ok(
    welcomeSource.includes("/api/onboarding/status"),
    "expected welcome page to probe /api/onboarding/status"
  );
  assert.ok(
    welcomeSource.includes("/api/onboarding/first-sync"),
    "expected welcome page to POST /api/onboarding/first-sync"
  );
  assert.ok(
    welcomeSource.includes("/api/providers/garmin/login?next="),
    "expected welcome page to use Garmin login with next redirect"
  );
});
