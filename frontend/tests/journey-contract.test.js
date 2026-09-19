const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relativePath) =>
  fs.readFileSync(path.join(root, relativePath), "utf8");

test("authenticated navigation exposes real Journey and Activities routes", () => {
  const shell = read("components/AuthenticatedShell.js");

  assert.ok(shell.includes('href: "/journey"'));
  assert.ok(shell.includes('href: "/journey#activities"'));
  assert.ok(!shell.includes('href: "/dashboard#journey"'));
  assert.ok(!shell.includes('href: "/dashboard#activities"'));
});

test("journey page preserves filters and renders reconciled time summaries", () => {
  const source = read("pages/journey.js");

  assert.ok(source.includes('"/api/journey"'));
  assert.ok(source.includes("router.replace"));
  assert.ok(source.includes('name="window"'));
  assert.ok(source.includes('name="sport"'));
  assert.ok(source.includes('name="goal"'));
  assert.ok(source.includes("available_goals"));
  assert.ok(source.includes("intensity_distribution"));
  assert.ok(source.includes("dossier_handoff.href"));
  assert.match(source, /Weekly timeline/i);
  assert.match(source, /Monthly summary/i);
  assert.match(source, /Data through/i);
  assert.ok(source.includes("/activities/"));
  assert.ok(source.includes("<AuthenticatedShell active=\"journey\">"));
});

test("activity detail is athlete-facing and provenance-safe", () => {
  const source = read("pages/activities/[id].js");

  assert.ok(source.includes("/api/journey/activities/"));
  assert.ok(source.includes("router.query.id"));
  assert.ok(source.includes("router.query.goal"));
  assert.match(source, /Data provenance/i);
  assert.match(source, /Back to journey/i);
  assert.ok(!source.includes("raw_payload"));
  assert.ok(!source.includes("metadata_json"));
  assert.ok(source.includes("<AuthenticatedShell active=\"activities\">"));
  assert.ok(source.includes("formatDate(activity.start_time)"));
  assert.ok(!source.includes("activity.started_at"));
});

test("journey layouts retain usable mobile controls", () => {
  const styles = read("styles/Journey.module.css");

  assert.match(styles, /@media\s*\(max-width:\s*720px\)/);
  assert.ok(styles.includes("min-height: 44px"));
  assert.ok(styles.includes(":focus-visible"));
});


test("dossier handoff carries Journey filters into the private library", () => {
  const journey = read("pages/journey.js");

  assert.ok(journey.includes("journey.dossier_handoff.href"));
  assert.match(journey, /Carry this window into your dossier/i);
  assert.ok(journey.includes('name="window"'));
  assert.ok(journey.includes('name="sport"'));
  assert.ok(journey.includes('name="goal"'));
});
