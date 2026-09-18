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
    /training-volume preview/i,
    "expected honest training-volume preview copy"
  );
  assert.match(
    welcomeSource,
    /Continue with Gmail/i,
    'expected brokered "Continue with Gmail" unauthenticated entry copy'
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
    welcomeSource.includes("/api/providers/garmin/login?next=/welcome"),
    "expected welcome page to start direct Garmin authorization"
  );
  assert.ok(
    welcomeSource.includes("/auth/login?next=/welcome"),
    "expected welcome page to send unauthenticated users through /auth/login?next=/welcome"
  );
});

test("welcome page removes direct Google login copy", () => {
  assert.ok(
    !welcomeSource.includes("Start with Google"),
    'expected direct "Start with Google" copy to be removed from welcome'
  );
  assert.ok(
    !welcomeSource.includes("Login with Google"),
    'expected direct "Login with Google" copy to be removed from welcome'
  );
});

test("welcome page presents recoverable Garmin sync states", () => {
  for (const state of [
    "authorization_required",
    "sync_failed",
    "partial",
    "stale",
  ]) {
    assert.ok(
      welcomeSource.includes(state),
      `expected welcome page to render the ${state} state`
    );
  }

  assert.match(welcomeSource, /Reconnect Garmin/i);
  assert.match(welcomeSource, /Try sync again/i);
  assert.match(welcomeSource, /Refresh fitness data/i);
  assert.ok(
    !welcomeSource.includes("first_sync.error"),
    "expected welcome page to avoid rendering raw provider errors"
  );
});


test("synced athletes can queue an incremental fitness refresh", () => {
  assert.match(
    welcomeSource,
    /welcomeState === "synced"[\s\S]*onClick=\{queueFirstSync\}[\s\S]*Refresh fitness data/i,
    "expected the normal synced view to expose the incremental sync action"
  );
});
