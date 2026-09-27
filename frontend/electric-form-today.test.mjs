import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.dirname(new URL(import.meta.url).pathname);
const dashboard = fs.readFileSync(path.join(root, "pages", "dashboard.js"), "utf8");
const shell = fs.readFileSync(path.join(root, "components", "AuthenticatedShell.js"), "utf8");
const shellCss = fs.readFileSync(path.join(root, "styles", "AuthenticatedShell.module.css"), "utf8");
const athleteCss = fs.readFileSync(path.join(root, "styles", "AthletePages.module.css"), "utf8");

test("Electric Today preserves canonical athlete and plan contracts", () => {
  assert.match(dashboard, /authenticatedJson\("\/api\/athlete-home"\)/);
  assert.match(dashboard, /authenticatedJson\("\/api\/today-plan"\)/);
  assert.match(dashboard, /authenticatedJson\("\/api\/today-plan\/context"\)/);
  assert.match(dashboard, /not a medical readiness score or a prediction/);
  assert.match(dashboard, /AthleteOrbitStory/);
});

test("Electric Today is explicitly scoped to the Today authenticated surface", () => {
  assert.match(dashboard, /variant="electric"/);
  assert.match(dashboard, /contentClassName=\{styles\.electricToday\}/);
  assert.match(shell, /variant = "standard"/);
  assert.match(shell, /data-shell-variant=\{variant\}/);
  assert.match(shellCss, /\.electricShell/);
});

test("Electric Today carries imagery, Amanda, accessibility and motion boundaries", () => {
  assert.match(dashboard, /Amanda/);
  assert.match(dashboard, /voice never autoplays/);
  assert.doesNotMatch(dashboard, /playElectricFormCue/);
  assert.match(athleteCss, /electric-entry-athletes\.svg/);
  assert.match(athleteCss, /var\(--ef-color-electric\)/);
  assert.match(athleteCss, /min-height: 44px/);
  assert.match(athleteCss, /prefers-reduced-motion: reduce/);
  assert.match(athleteCss, /animation: none/);
});
