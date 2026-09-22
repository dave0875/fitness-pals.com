const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const welcomeSource = fs.readFileSync(path.join(__dirname, "..", "pages", "welcome.js"), "utf8");

test("welcome consumes the unified activation contract", () => {
  assert.ok(welcomeSource.includes("/api/auth/session"));
  assert.ok(welcomeSource.includes("/api/onboarding/status"));
  assert.ok(welcomeSource.includes("activation?.state"));
  assert.ok(welcomeSource.includes("activation?.usable_now"));
  assert.ok(welcomeSource.includes("activation?.action"));
});

test("welcome persists intent and can start a supported live sync when offered", () => {
  assert.ok(welcomeSource.includes("/api/onboarding/goal"));
  assert.ok(welcomeSource.includes("/api/onboarding/first-sync"));
  assert.ok(welcomeSource.includes('sourceAction?.kind === "sync"'));
  assert.match(welcomeSource, /Save and continue/i);
});

test("welcome bypasses established athletes unless they explicitly edit or view first value", () => {
  assert.ok(welcomeSource.includes("activation?.requires_activation === false"));
  assert.ok(welcomeSource.includes('router.query.edit !== "intent"'));
  assert.ok(welcomeSource.includes('router.query.first !== "1"'));
  assert.ok(welcomeSource.includes("router.replace"));
});

test("welcome renders recoverable progressive states without raw errors", () => {
  for (const state of ["importing", "usable_partial"]) {
    assert.ok(welcomeSource.includes(state), `expected ${state} state`);
  }
  assert.match(welcomeSource, /Training history/i);
  assert.match(welcomeSource, /Continue with Coach/i);
  assert.ok(!welcomeSource.includes("first_sync.error"));
  assert.ok(!welcomeSource.includes("error_json"));
});

test("welcome keeps brokered sign-in and no provider-specific login requirement", () => {
  assert.ok(welcomeSource.includes("/auth/login?next=/welcome"));
  assert.match(welcomeSource, /Continue with Gmail/i);
  assert.ok(!welcomeSource.includes("/auth/google/login"));
});
