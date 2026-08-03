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
    source.includes("Connect through PulsAI") &&
      source.includes("Import my training history") &&
      source.includes("Open dashboard"),
    'expected homepage source to include "Connect through PulsAI", "Import my training history", and "Open dashboard"'
  );
  assert.match(
    source,
    /session|authState|sessionState|sessionStatus|isAuthenticated/i,
    "expected homepage source to include session state handling"
  );
  assert.ok(
    source.includes("/api/onboarding/status"),
    "expected homepage source to probe /api/onboarding/status for first-win funnel state"
  );
  assert.match(
    source,
    /authenticatedNoPulsai|readyToSync|synced|anonymous/i,
    "expected homepage source to model anonymous, connected, ready-to-sync, and synced states"
  );
  assert.ok(
    /(?:session|authState|sessionState|sessionStatus|isAuthenticated)[\s\S]{0,500}(Continue with Gmail|View sample coach dossier)|(Continue with Gmail|View sample coach dossier)[\s\S]{0,500}(?:session|authState|sessionState|sessionStatus|isAuthenticated)/i.test(
      source
    ),
    "expected anonymous-only CTAs to be gated by resolved session state"
  );
});

test("homepage preserves or defaults the next redirect for brokered login", () => {
  assert.match(
    source,
    /URLSearchParams|window\.location\.search|next=/,
    "expected homepage source to read or construct a next redirect"
  );
  assert.match(
    source,
    /\/auth\/login\?next=/,
    "expected homepage source to route anonymous users through /auth/login?next="
  );
});
