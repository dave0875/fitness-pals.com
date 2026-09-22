const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "..", "pages", "index.js"), "utf8");

test("homepage exposes a loading or skeleton state while session is resolving", () => {
  assert.match(source, /loading|skeleton|authState|sessionState|sessionStatus|isAuthenticated/i);
});

test("homepage renders state-aware authenticated CTAs", () => {
  assert.ok(
    source.includes("Start with my goal") &&
      source.includes("See activation progress") &&
      source.includes("Open Today")
  );
  assert.ok(source.includes("/api/onboarding/status"));
  assert.match(source, /activationNeeded|importing|synced|anonymous/i);
});

test("homepage preserves or defaults the next redirect for brokered login", () => {
  assert.match(source, /URLSearchParams|window\.location\.search|next=/);
  assert.match(source, /\/auth\/login\?next=/);
  assert.ok(source.includes('const DEFAULT_AUTH_NEXT = "/today"'));
  assert.ok(source.includes('!candidate.includes("\\\\")'));
});
