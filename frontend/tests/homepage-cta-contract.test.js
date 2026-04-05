const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const homepageSource = fs.readFileSync(path.join(__dirname, "..", "pages", "index.js"), "utf8");

test('"Continue with Gmail" points to the brokered /auth/login entry', () => {
  assert.ok(
    homepageSource.includes("Continue with Gmail"),
    'expected homepage CTA text "Continue with Gmail"'
  );
  assert.ok(
    homepageSource.includes('href={authWelcomeHref}') ||
      homepageSource.includes('href={AUTH_WELCOME_HREF}') ||
      homepageSource.includes("/auth/login?next="),
    'expected "Continue with Gmail" to point to a brokered /auth/login?next=... entry'
  );
});

test("homepage keeps anonymous sign-in on the shared brokered route", () => {
  assert.ok(
    homepageSource.includes("/auth/login?next="),
    "expected homepage auth CTA to use /auth/login?next=..."
  );
  assert.ok(
    !homepageSource.includes("/auth/google/login"),
    "expected homepage not to reference provider-specific login routes"
  );
  assert.ok(
    !homepageSource.includes("accounts.google.com"),
    "expected homepage not to deep-link directly to Google OAuth"
  );
});

test('"View sample coach dossier" points to the public report URL', () => {
  assert.ok(
    homepageSource.includes("View sample coach dossier"),
    'expected homepage CTA text "View sample coach dossier"'
  );
  assert.ok(
    homepageSource.includes("https://fitness-pals.com/reports/urban-feet-coach-dossier-third-edition-2026-04-05.html"),
    'expected "View sample coach dossier" to point to the public report URL'
  );
});

test("homepage removes direct Google login copy from the anonymous view", () => {
  assert.ok(
    !homepageSource.includes("Start with Google"),
    'expected direct "Start with Google" copy to be removed'
  );
  assert.ok(
    !homepageSource.includes("Login with Google"),
    'expected direct "Login with Google" CTA to be removed'
  );
  assert.ok(
    !homepageSource.includes(">Dashboard<"),
    'expected dead-end "Dashboard" homepage link text to be removed'
  );
});
