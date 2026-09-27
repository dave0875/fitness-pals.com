import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.dirname(new URL(import.meta.url).pathname);
const journey = fs.readFileSync(path.join(root, "pages", "journey.js"), "utf8");
const activity = fs.readFileSync(path.join(root, "pages", "activities", "[id].js"), "utf8");
const dossierIndex = fs.readFileSync(path.join(root, "pages", "dossiers", "index.js"), "utf8");
const dossierDetail = fs.readFileSync(path.join(root, "pages", "dossiers", "[id].js"), "utf8");
const journeyCss = fs.readFileSync(path.join(root, "styles", "Journey.module.css"), "utf8");
const dossierCss = fs.readFileSync(path.join(root, "styles", "Dossiers.module.css"), "utf8");

test("Kinetic Athlete preserves canonical Progress and activity contracts", () => {
  assert.match(journey, /authenticatedJson\(`\$\{JOURNEY_API\}\?\$\{params\.toString\(\)\}`\)/);
  assert.match(journey, /journey\.comparison\.changes/);
  assert.match(journey, /journey\.freshness/);
  assert.match(journey, /journey\.dossier_handoff\.href/);
  assert.match(activity, /\/api\/journey\/activities\//);
  assert.match(activity, /activity\.provenance/);
  assert.match(activity, /comparison\.distance_percent_vs_median/);
  assert.match(journey, /not a readiness score or forecast/);
});

test("Kinetic Athlete visualizes only already-present canonical weekly distance", () => {
  assert.match(journey, /trajectoryWeeks = \(journey\?\.weekly_summaries \|\| \[\]\)\.slice\(-8\)/);
  assert.match(journey, /Number\(week\.distance_m\) \|\| 0/);
  assert.match(journey, /formatDistance\(week\.distance_m\)/);
  assert.match(journey, /They are not a readiness score or forecast/);
  assert.match(journeyCss, /\.trajectoryFill/);
  assert.match(journeyCss, /@keyframes kineticFill/);
});

test("Kinetic Athlete makes Progress, activity detail, and Dossiers explicit Electric Form surfaces", () => {
  assert.match(journey, /styles\.electricKinetic/);
  assert.match(activity, /styles\.electricKinetic/);
  assert.match(activity, /styles\.activityHero/);
  assert.match(dossierIndex, /styles\.electricDossier/);
  assert.match(dossierDetail, /styles\.electricDossier/);
  assert.match(dossierIndex, /styles\.dossierHero/);
  assert.match(dossierDetail, /styles\.dossierHero/);
});

test("Kinetic Athlete preserves dossier truth, privacy, and lifecycle contracts", () => {
  assert.match(dossierIndex, /authenticatedJson\("\/api\/dossiers"/);
  for (const state of ["queued", "generating", "completed", "superseded", "insufficient_data", "failed"]) {
    assert.match(dossierIndex, new RegExp(state));
  }
  assert.match(dossierDetail, /Material gaps/);
  assert.match(dossierDetail, /Evidence/);
  assert.match(dossierDetail, /Inference/);
  assert.match(dossierDetail, /Uncertainty/);
  assert.match(dossierDetail, /Private by default/);
  assert.match(dossierDetail, /\/export/);
});

test("Kinetic Athlete retains accessible motion boundaries", () => {
  assert.match(journeyCss, /min-height: 44px/);
  assert.match(journeyCss, /prefers-reduced-motion: reduce/);
  assert.match(journeyCss, /\.trajectoryFill[\s\S]*animation: none/);
  assert.match(dossierCss, /prefers-reduced-motion: reduce/);
  assert.match(dossierCss, /animation: none/);
});
