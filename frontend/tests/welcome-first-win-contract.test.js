const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const welcomeSource = fs.readFileSync(path.join(__dirname, "..", "pages", "welcome.js"), "utf8");

test("welcome page renders coach insight and next action copy for first win", () => {
  assert.match(
    welcomeSource,
    /Coach insight/i,
    "expected welcome page to render a coach insight module"
  );
  assert.match(
    welcomeSource,
    /Next action/i,
    "expected welcome page to render a next action module"
  );
});
