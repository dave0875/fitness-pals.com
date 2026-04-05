const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "..", "pages", "index.js"), "utf8");

test("homepage exposes a loading or skeleton state while session is resolving", () => {
  assert.match(
    source,
    /loading|skeleton|authState|sessionState|sessionStatus|isAuthenticated/i,
    "expected homepage source to include session loading/skeleton state"
  );
});

test("homepage renders state-aware authenticated CTAs", () => {
  assert.ok(
    source.includes("Open dashboard") || source.includes("Connect Garmin"),
    'expected homepage source to include "Open dashboard" or "Connect Garmin"'
  );
  assert.match(
    source,
    /session|authState|sessionState|sessionStatus|isAuthenticated/i,
    "expected homepage source to include session state handling"
  );
  assert.ok(
    /(?:session|authState|sessionState|sessionStatus|isAuthenticated)[\s\S]{0,500}(Start with Google|View sample coach dossier)|(Start with Google|View sample coach dossier)[\s\S]{0,500}(?:session|authState|sessionState|sessionStatus|isAuthenticated)/i.test(
      source
    ),
    "expected anonymous-only CTAs to be gated by resolved session state"
  );
});
