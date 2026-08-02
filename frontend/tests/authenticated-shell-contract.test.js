const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const shellSource = fs.readFileSync(
  path.join(__dirname, "..", "components", "AuthenticatedShell.js"),
  "utf8"
);
const shellStyles = fs.readFileSync(
  path.join(__dirname, "..", "styles", "AuthenticatedShell.module.css"),
  "utf8"
);
const dashboardSource = fs.readFileSync(
  path.join(__dirname, "..", "pages", "dashboard.js"),
  "utf8"
);
const settingsSource = fs.readFileSync(
  path.join(__dirname, "..", "pages", "settings.js"),
  "utf8"
);

test("authenticated shell exposes the athlete journey navigation", () => {
  for (const destination of ["Home", "Journey", "Activities", "Dossiers", "Coach", "Settings"]) {
    assert.ok(shellSource.includes(destination), `expected shell navigation to include ${destination}`);
  }
  assert.ok(shellSource.includes('aria-label="Primary navigation"'));
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
});

test("shell links only to implemented pages or dashboard sections", () => {
  for (const section of ["journey", "activities", "dossiers", "coach"]) {
    assert.ok(shellSource.includes(`/dashboard#${section}`));
    assert.ok(dashboardSource.includes(`id="${section}"`));
  }
});
