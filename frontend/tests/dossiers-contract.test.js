const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("private dossiers remain available without competing in primary navigation", () => {
  const shell = read("components/AuthenticatedShell.js");
  const dashboard = read("pages/dashboard.js");

  assert.ok(!shell.includes('href: "/dossiers"'));
  assert.ok(dashboard.includes("home.dossier.action.href"));
  assert.match(dashboard, /private dossier library/i);
});

test("dossier library covers asynchronous and recoverable lifecycle states", () => {
  const source = read("pages/dossiers/index.js");
  assert.ok(source.includes('"/api/dossiers"'));
  assert.ok(source.includes('authenticatedJson("/api/dossiers"'));
  for (const state of ["queued", "generating", "completed", "superseded", "insufficient_data", "failed"]) {
    assert.ok(source.includes(state));
  }
  assert.match(source, /Generate analysis/i);
  assert.match(source, /Retry/i);
  assert.match(source, /Public sample/i);
  assert.ok(source.includes('<AuthenticatedShell active="progress">'));
});

test("private dossier detail discloses boundaries and reasoning classes", () => {
  const source = read("pages/dossiers/[id].js");
  assert.ok(source.includes("/api/dossiers/"));
  assert.match(source, /Data through/i);
  assert.match(source, /Connection window/i);
  assert.match(source, /Material gaps/i);
  assert.match(source, /Evidence/i);
  assert.match(source, /Inference/i);
  assert.match(source, /Uncertainty/i);
  assert.match(source, /Next actions/i);
  assert.match(source, /Back to Progress/i);
  assert.ok(source.includes("/export"));
  assert.ok(!source.includes("public share"));
  assert.ok(source.includes('<AuthenticatedShell active="progress">'));
});

test("dossier library is mobile-readable and keyboard visible", () => {
  const styles = read("styles/Dossiers.module.css");
  assert.match(styles, /@media\s*\(max-width:\s*720px\)/);
  assert.ok(styles.includes("min-height: 44px"));
  assert.ok(styles.includes(":focus-visible"));
});
