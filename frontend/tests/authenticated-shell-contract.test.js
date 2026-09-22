const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const shellSource = fs.readFileSync(path.join(__dirname, "..", "components", "AuthenticatedShell.js"), "utf8");
const shellStyles = fs.readFileSync(path.join(__dirname, "..", "styles", "AuthenticatedShell.module.css"), "utf8");
const dashboardSource = fs.readFileSync(path.join(__dirname, "..", "pages", "dashboard.js"), "utf8");
const settingsSource = fs.readFileSync(path.join(__dirname, "..", "pages", "settings.js"), "utf8");

test("authenticated shell exposes the intent-based Product V2 navigation", () => {
  for (const destination of ["Today", "Coach", "Progress", "Training"]) {
    assert.ok(shellSource.includes(`label: "${destination}"`), `expected shell navigation to include ${destination}`);
  }
  for (const obsolete of ['label: "Home"', 'label: "Journey"', 'label: "Activities"', 'label: "Dossiers"', 'label: "Settings"']) {
    assert.ok(!shellSource.includes(obsolete), `expected primary navigation to drop ${obsolete}`);
  }
  assert.ok(shellSource.includes('aria-label="Primary navigation"'));
  assert.ok(shellSource.includes('href="/settings"'));
  assert.ok(shellSource.includes('href="/auth/logout"'));
});

test("dashboard and settings share the authenticated shell", () => {
  for (const source of [dashboardSource, settingsSource]) {
    assert.ok(source.includes('from "../components/AuthenticatedShell"'));
    assert.ok(source.includes("<AuthenticatedShell"));
  }
});

test("shell has a compact mobile navigation treatment", () => {
  assert.match(shellStyles, /@media\s*\(max-width:\s*720px\)/);
  assert.ok(shellStyles.includes("overflow-x: auto"));
  assert.ok(shellStyles.includes("min-height: 44px"));
  assert.ok(shellStyles.includes(".coachLink"));
  assert.ok(shellSource.includes("styles.accountName"));
  assert.ok(shellSource.includes("styles.settingsLabel"));
  assert.match(shellStyles, /@media[\s\S]*\.account\s*\{[\s\S]*gap:\s*0\.4rem/);
  assert.match(shellStyles, /@media[\s\S]*\.brand strong,[\s\S]*display:\s*none/);
});

test("protected routes enter sign in with their full safe return path", () => {
  assert.ok(shellSource.includes("router.asPath"));
  assert.ok(shellSource.includes("safeReturnPath"));
  assert.ok(shellSource.includes("encodeURIComponent"));
  assert.ok(shellSource.includes("/auth/login?next="));
  assert.ok(shellSource.includes("window.location.assign"));
  assert.ok(shellSource.includes('response.status === 401'));
  assert.ok(shellSource.includes('!asPath.startsWith("//")'));
  assert.ok(shellSource.includes('!asPath.includes("\\\\")'));
});

test("shell links only to real primary product routes and carries Coach source context", () => {
  for (const route of ["/today", "/coach", "/progress", "/training"]) {
    assert.ok(shellSource.includes(`href: "${route}"`));
  }
  assert.ok(!shellSource.includes("/dashboard#coach"));
  assert.ok(!shellSource.includes("/journey#activities"));
  assert.ok(shellSource.includes("coachHref"));
  assert.ok(shellSource.includes("encodeURIComponent(safeReturnPath(router.asPath))"));
  assert.ok(shellSource.includes('href={coachHref}'));
});
