const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const welcomePath = path.join(__dirname, "..", "pages", "welcome.js");

test("welcome page source contract includes guided onboarding states", () => {
  assert.ok(fs.existsSync(welcomePath), "expected frontend/pages/welcome.js to exist");
  const source = fs.readFileSync(welcomePath, "utf8");

  assert.match(source, /Connect Garmin/);
  assert.match(source, /Import my training history/);
  assert.match(source, /latest 5 activities|last 5 activities|recent 5 activities/i);
  assert.match(source, /training-volume preview/i);
  assert.match(source, /connect_garmin|ready_to_sync|sync_queued|synced/i);
});
