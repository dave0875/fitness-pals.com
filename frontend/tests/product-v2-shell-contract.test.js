const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("Product V2 primary navigation uses real intent routes", () => {
  const shell = read("components/AuthenticatedShell.js");
  for (const [label, href] of [
    ["Today", "/today"],
    ["Coach", "/coach"],
    ["Progress", "/progress"],
    ["Training", "/training"],
  ]) {
    assert.ok(shell.includes(`label: "${label}"`), `expected ${label} in primary navigation`);
    assert.ok(shell.includes(`href: "${href}"`), `expected ${href} primary route`);
  }
  assert.ok(!shell.includes("/dashboard#coach"));
  assert.ok(!shell.includes("/journey#activities"));
  assert.ok(shell.includes('href="/settings"'));
  assert.ok(shell.includes('href="/auth/logout"'));
  assert.ok(shell.includes('href={coachHref}'));
  assert.match(shell, /Ask Coach/i);
});

test("Today and Progress keep legacy implementations available while V2 routes stabilize", () => {
  const today = read("pages/today.js");
  const progress = read("pages/progress.js");
  const dashboard = read("pages/dashboard.js");
  const journey = read("pages/journey.js");

  assert.ok(today.includes('from "./dashboard"'));
  assert.ok(progress.includes('from "./journey"'));
  assert.ok(dashboard.includes('<AuthenticatedShell active="today">'));
  assert.ok(journey.includes('<AuthenticatedShell active="progress">'));
});

test("Coach is a dedicated contextual authenticated workspace", () => {
  const coach = read("pages/coach.js");
  assert.ok(coach.includes('<AuthenticatedShell active="coach">'));
  assert.ok(coach.includes('authenticatedJson("/api/chat"'));
  assert.ok(coach.includes("router.query.from"));
  assert.ok(coach.includes("safeSourcePath"));
  assert.ok(coach.includes('!value.includes("\\\\")'));
  assert.match(coach, /Talking about/i);
  assert.match(coach, /Ask about your training/i);
});

test("Training is a real activity-history route", () => {
  const training = read("pages/training.js");
  assert.ok(training.includes('<AuthenticatedShell active="training">'));
  assert.ok(training.includes('"/api/journey"'));
  assert.ok(training.includes("/activities/"));
  assert.match(training, /Training history/i);
});

test("returning public sign-in targets Today instead of Welcome", () => {
  const homepage = read("pages/index.js");
  assert.ok(homepage.includes('const DEFAULT_AUTH_NEXT = "/today"'));
  assert.ok(homepage.includes('href="/today"'));
  assert.match(homepage, /Open Today/i);
});

test("recovery and archive flows point to V2 destinations", () => {
  const dashboard = read("pages/dashboard.js");
  const settings = read("pages/settings.js");
  const archive = read("pages/import/garmin-archive.js");
  const flow = read("lib/coreFlowStates.mjs");

  assert.ok(dashboard.includes('href="/settings"'));
  assert.ok(settings.includes('href="/training"'));
  assert.ok(archive.includes('href="/training"'));
  assert.ok(flow.includes('resultHref: job?.status === "completed" ? "/training" : null'));
});

test("production smoke protects the new V2 page routes", () => {
  const smoke = fs.readFileSync(path.join(root, "..", "scripts", "smoke_production.py"), "utf8");
  for (const route of ["/today", "/coach", "/progress", "/training"]) {
    assert.ok(smoke.includes(route), `expected production smoke coverage for ${route}`);
  }
});
