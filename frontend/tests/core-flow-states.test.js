const assert = require("node:assert/strict");
const test = require("node:test");

test("connected and archive-only athletes see actions that can finish", async () => {
  const { connectionState } = await import("../lib/coreFlowStates.mjs");
  assert.equal(connectionState({ garmin_connected: true, first_sync: { state: "completed" } }).action, "refresh");
  assert.equal(connectionState({ garmin_connected: false, first_sync: { state: "completed" }, latest_activities: [{}] }).action, "connect");
  assert.equal(connectionState({ garmin_connected: true, first_sync: { state: "queued" } }).action, "wait");
  assert.equal(connectionState({ garmin_connected: true, first_sync: { state: "failed" } }).action, "retry");
});

test("archive controls distinguish unavailable, pending, failed, and complete", async () => {
  const { archiveState } = await import("../lib/coreFlowStates.mjs");
  const unavailable = archiveState({ drive: { available: false, reason: "No folder assigned" }, upload: { available: true } });
  assert.equal(unavailable.canDriveImport, false);
  assert.equal(unavailable.driveReason, "No folder assigned");
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "queued" }).canDriveImport, false);
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "failed" }).canDriveImport, true);
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "completed" }).resultHref, "/journey#activities");
});

test("journey pagination keeps a long filtered history finishable", async () => {
  const { paginateActivities } = await import("../lib/coreFlowStates.mjs");
  const activities = Array.from({ length: 106 }, (_, index) => ({ id: index + 1 }));
  const first = paginateActivities(activities, 1, 25);
  const last = paginateActivities(activities, 5, 25);
  assert.equal(first.items.length, 25);
  assert.equal(first.totalPages, 5);
  assert.equal(first.from, 1);
  assert.equal(first.to, 25);
  assert.equal(last.items.length, 6);
  assert.equal(last.from, 101);
  assert.equal(last.to, 106);
});

test("a pre-backfill insufficient dossier job cannot override current eligibility", async () => {
  const { dossierState } = await import("../lib/coreFlowStates.mjs");
  const filters = { window: "90d", sport: "all", goal: "all" };
  const oldJob = { id: "old", status: "insufficient_data", filters, activity_count: 0 };
  const ready = dossierState({ eligible: true, activity_count: 106, filters }, [oldJob]);
  assert.equal(ready.canGenerate, true);
  assert.equal(ready.currentJobs.length, 0);
  assert.equal(ready.historicalJobs.length, 1);
  const empty = dossierState({ eligible: false, activity_count: 0, filters }, [oldJob]);
  assert.equal(empty.canGenerate, false);
  assert.equal(empty.currentJobs.length, 1);
});
