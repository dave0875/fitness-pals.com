const assert = require("node:assert/strict");
const test = require("node:test");

test("connection actions follow the truthful Phase 2 activation contract", async () => {
  const { connectionState } = await import("../lib/coreFlowStates.mjs");
  assert.equal(connectionState({ activation: { state: "fully_usable", action: { kind: "refresh", label: "Refresh training data", href: "/settings", enabled: true } } }).action, "refresh");
  assert.equal(connectionState({ activation: { state: "importing", action: { kind: "wait", label: "Import in progress", href: "/training", enabled: false } } }).action, "wait");
  assert.equal(connectionState({ activation: { state: "authorization_expired", action: { kind: "reconnect", label: "Reconnect training source", href: "/settings", enabled: true } } }).action, "reconnect");
  const unsupported = connectionState({ activation: { state: "unsupported_capability", action: { kind: "archive", label: "Use archive import", href: "/import/garmin-archive", enabled: true } } });
  assert.equal(unsupported.action, "archive");
  assert.equal(unsupported.href, "/import/garmin-archive");
  assert.equal(unsupported.enabled, true);
});

test("archive controls distinguish unavailable, pending, failed, and complete", async () => {
  const { archiveState } = await import("../lib/coreFlowStates.mjs");
  const unavailable = archiveState({ drive: { available: false, reason: "No folder assigned" }, upload: { available: true } });
  assert.equal(unavailable.canDriveImport, false);
  assert.equal(unavailable.driveReason, "No folder assigned");
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "queued" }).canDriveImport, false);
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "processing" }).canDriveImport, false);
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "failed" }).canDriveImport, true);
  assert.equal(archiveState({ drive: { available: true }, upload: { available: true } }, { status: "completed" }).resultHref, "/training");
});

test("archive progress turns durable checkpoints into visible progress", async () => {
  const { archiveProgress } = await import("../lib/coreFlowStates.mjs");

  const queued = archiveProgress({ status: "queued" });
  assert.equal(queued.percent, null);
  assert.match(queued.label, /queued/i);

  const processing = archiveProgress({
    status: "processing",
    objects_total: 222,
    objects_processed: 57,
    objects_imported: 40,
    objects_skipped: 17,
    objects_failed: 0,
    activities: 106,
  });
  assert.equal(processing.processed, 57);
  assert.equal(processing.total, 222);
  assert.equal(processing.percent, 26);
  assert.match(processing.label, /57 of 222/i);
  assert.match(processing.detail, /106 activities/i);

  const completed = archiveProgress({
    status: "completed",
    objects_total: 222,
    objects_processed: 222,
    activities: 3522,
  });
  assert.equal(completed.percent, 100);
  assert.match(completed.label, /complete/i);
});

test("archive page polls uncached durable status and renders progress", () => {
  const fs = require("node:fs");
  const path = require("node:path");
  const source = fs.readFileSync(
    path.join(__dirname, "..", "pages", "import", "garmin-archive.js"),
    "utf8",
  );

  assert.ok(source.includes('cache: "no-store"'));
  assert.ok(source.includes('"visibilitychange"'));
  assert.ok(source.includes("<progress"));
  assert.ok(source.includes("archiveProgress(job)"));
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
