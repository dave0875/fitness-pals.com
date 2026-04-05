const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const homepageSource = fs.readFileSync(path.join(__dirname, "..", "pages", "index.js"), "utf8");

test("homepage renders a concrete trust module", () => {
  assert.match(
    homepageSource,
    /Disconnect Garmin or revoke access anytime/i,
    "expected homepage trust section to explain revocation"
  );
  assert.match(
    homepageSource,
    /app cookies, not provider tokens/i,
    "expected homepage trust section to explain the app-session contract"
  );
});

test("homepage renders an explainability preview", () => {
  assert.match(
    homepageSource,
    /Why this plan would change/i,
    "expected homepage to include an explainability-preview title"
  );
  assert.match(
    homepageSource,
    /Sleep dropped|load spiked|recovery compressed/i,
    "expected homepage explainability preview to show a concrete coaching example"
  );
});

test("homepage exposes public proof artifacts beyond the dossier", () => {
  assert.match(
    homepageSource,
    /Sample readiness summary/i,
    "expected homepage proof section to link to a sample readiness summary"
  );
  assert.match(
    homepageSource,
    /Sample training pattern insight/i,
    "expected homepage proof section to link to a sample training-pattern artifact"
  );
});
