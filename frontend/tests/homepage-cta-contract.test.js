const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const homepageSource = fs.readFileSync(path.join(__dirname, "..", "pages", "index.js"), "utf8");

test('"Start with Google" points to /auth/login?next=/welcome', () => {
  assert.ok(
    homepageSource.includes("Start with Google"),
    'expected homepage CTA text "Start with Google"'
  );
  assert.ok(
    homepageSource.includes('href={AUTH_WELCOME_HREF}') ||
      homepageSource.includes('"/auth/login?next=/welcome"'),
    'expected "Start with Google" to point to /auth/login?next=/welcome'
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

test("homepage removes dead-end buttons from the anonymous view", () => {
  assert.ok(
    !homepageSource.includes("Login with Google"),
    'expected dead-end "Login with Google" CTA to be removed'
  );
  assert.ok(
    !homepageSource.includes(">Dashboard<"),
    'expected dead-end "Dashboard" homepage link text to be removed'
  );
});
