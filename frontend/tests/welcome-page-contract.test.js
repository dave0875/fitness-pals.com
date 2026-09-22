const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const welcomePath = path.join(__dirname, "..", "pages", "welcome.js");

test("welcome page is an activation surface, not a permanent integration wizard", () => {
  assert.ok(fs.existsSync(welcomePath), "expected frontend/pages/welcome.js to exist");
  const source = fs.readFileSync(welcomePath, "utf8");

  assert.match(source, /What would make Fitness Pals useful right now/i);
  assert.match(source, /Save and continue/i);
  assert.match(source, /First useful signal/i);
  assert.match(source, /Continue with Coach/i);
  assert.match(source, /activation\?\.requires_activation === false/);
  assert.match(source, /router\.replace/);
  assert.ok(source.includes("/api/onboarding/status"));
  assert.ok(source.includes("/api/onboarding/goal"));
  assert.ok(source.includes("/api/onboarding/first-sync"));
});
