const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (name) => fs.readFileSync(path.join(root, name), "utf8");

test("settings resolves connected, archive-only, pending, and failed connection actions", () => {
  const source = read("pages/settings.js");
  assert.ok(source.includes("/api/onboarding/status"));
  assert.ok(source.includes("/api/onboarding/first-sync"));
  assert.ok(source.includes("/api/providers/garmin/login?next=/settings"));
  assert.match(source, /Connection is active/i);
  assert.match(source, /Archive history is available/i);
  assert.match(source, /Refresh in progress/i);
  assert.match(source, /Retry refresh/i);
});

test("archive page checks capabilities before exposing actions and links completed imports", () => {
  const source = read("pages/import/garmin-archive.js");
  assert.ok(source.includes("/api/archive-imports/capabilities"));
  assert.ok(source.includes("flow.canDriveImport"));
  assert.ok(source.includes("flow.canUpload"));
  assert.match(source, /Drive import unavailable/i);
  assert.match(source, /Try import again/i);
  assert.ok(source.includes("/journey#activities"));
});

test("dossier page uses current eligibility and returns to the generated result", () => {
  const source = read("pages/dossiers/index.js");
  assert.ok(source.includes("/api/dossiers/eligibility?"));
  assert.ok(source.includes("flow.currentJobs"));
  assert.ok(source.includes("flow.canGenerate"));
  assert.match(source, /activities match this selection/i);
  assert.match(source, /Open generated dossier/i);
});

test("journey visibly applies filters and paginates activity history", () => {
  const source = read("pages/journey.js");
  assert.match(source, /Applied filters/i);
  assert.ok(source.includes("paginateActivities"));
  assert.match(source, /Previous/i);
  assert.match(source, /Next/i);
});
