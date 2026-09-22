const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const welcomeSource = fs.readFileSync(path.join(__dirname, "..", "pages", "welcome.js"), "utf8");

test("welcome page renders an evidence-grounded first win and Coach continuation", () => {
  assert.match(welcomeSource, /First useful signal/i);
  assert.match(welcomeSource, /training_volume_preview/);
  assert.match(welcomeSource, /coach_insight/);
  assert.match(welcomeSource, /Continue with Coach/i);
  assert.match(welcomeSource, /Next action/i);
});
