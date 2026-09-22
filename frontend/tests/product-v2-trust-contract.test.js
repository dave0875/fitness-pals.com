const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relativePath) => fs.readFileSync(path.join(root, relativePath), "utf8");

test("Settings is a complete athlete-facing trust center", () => {
  const settings = read("pages/settings.js");

  for (const section of ["profile", "goals", "connections", "coaching", "data-privacy", "account"]) {
    assert.ok(settings.includes(`id="${section}"`), `expected Settings section ${section}`);
  }
  assert.ok(settings.includes("/api/onboarding/status"));
  assert.ok(settings.includes("/api/athlete-home"));
  assert.ok(settings.includes("/api/archive-imports/capabilities"));
  assert.ok(settings.includes("connectionTrustState"));
  assert.ok(settings.includes("freshnessSignals"));
  assert.ok(settings.includes('href="/privacy"'));
  assert.ok(settings.includes('href="/auth/logout"'));
  assert.ok(settings.includes('href="/welcome?edit=intent"'));

  for (const forbidden of [
    "RUNTRAINER_INFLUX_URL",
    "RUNTRAINER_INFLUX_TOKEN",
    "token_encrypted",
    "GARMIN_CLIENT_SECRET",
    "MCP URL",
  ]) {
    assert.equal(settings.includes(forbidden), false, `must not expose ${forbidden}`);
  }
});

test("connection trust states distinguish recovery scenarios without inventing data", async () => {
  const { connectionTrustState } = await import("../lib/trustStates.mjs");

  const history = { state: "ready", freshness: { state: "fresh", signals: {} } };
  const empty = { state: "empty", freshness: { state: "empty", signals: {} } };

  assert.equal(
    connectionTrustState(
      {
        garmin_connected: false,
        latest_activities: [{ id: "a" }],
        activation: { state: "authorization_expired" },
        first_sync: { state: "authorization_required" },
      },
      history,
      null
    ).state,
    "authorization_expired"
  );

  assert.equal(
    connectionTrustState(
      {
        garmin_connected: true,
        latest_activities: [],
        activation: { state: "importing" },
        first_sync: { state: "queued" },
      },
      empty,
      null
    ).state,
    "updating"
  );

  const partial = connectionTrustState(
    {
      garmin_connected: true,
      latest_activities: [{ id: "a" }],
      activation: { state: "usable_partial" },
      first_sync: { state: "running" },
    },
    { state: "ready", freshness: { state: "partial", signals: {} } },
    { latest_job: { status: "running" } }
  );
  assert.equal(partial.state, "partial");
  assert.equal(partial.updating, true);

  assert.equal(
    connectionTrustState(
      {
        garmin_connected: false,
        latest_activities: [{ id: "a" }],
        activation: { state: "fully_usable" },
        first_sync: { state: "completed" },
      },
      history,
      null
    ).state,
    "archive_only"
  );

  assert.equal(
    connectionTrustState(
      {
        garmin_connected: true,
        latest_activities: [{ id: "a" }],
        activation: { state: "import_failed" },
        first_sync: { state: "failed", failure_category: "upstream" },
      },
      history,
      { latest_job: { status: "failed" } }
    ).state,
    "failed"
  );

  assert.equal(
    connectionTrustState(
      {
        garmin_connected: true,
        latest_activities: [{ id: "a" }],
        activation: { state: "unsupported_capability" },
        first_sync: { state: "completed" },
      },
      history,
      null
    ).state,
    "unavailable"
  );

  assert.equal(
    connectionTrustState(
      {
        garmin_connected: false,
        latest_activities: [],
        activation: { state: "not_connected" },
        first_sync: { state: "not_started" },
      },
      empty,
      null
    ).state,
    "empty"
  );
});

test("fresh activity never masks stale sleep in the trust center", async () => {
  const { freshnessSignals } = await import("../lib/trustStates.mjs");
  const signals = freshnessSignals({
    freshness: {
      state: "partial",
      signals: {
        activities: { state: "fresh", data_through: "2026-09-22T12:00:00+00:00" },
        sleep: { state: "stale", data_through: "2026-09-17T23:59:59+00:00" },
        intensity: { state: "unknown", data_through: null },
      },
    },
  });

  assert.deepEqual(
    signals.map((item) => [item.key, item.state]),
    [
      ["activities", "fresh"],
      ["sleep", "stale"],
      ["intensity", "unknown"],
    ]
  );
});

test("archive recovery returns to Connections and explains duplicate-safe canonical history", () => {
  const archive = read("pages/import/garmin-archive.js");
  assert.ok(archive.includes('href="/settings#connections"'));
  assert.match(archive, /matching activities/i);
  assert.match(archive, /second visible workout/i);
  assert.match(archive, /saved training history is unchanged/i);
});

test("production smoke protects Settings and trust-state APIs without provider mutation", () => {
  const smoke = read("../scripts/smoke_production.py");
  assert.ok(smoke.includes('name="Settings page route"'));
  assert.ok(smoke.includes("/settings"));
  assert.ok(smoke.includes("/api/athlete-home"));
  assert.ok(smoke.includes("/api/archive-imports/capabilities"));
  assert.ok(smoke.includes('"freshness"'));
  assert.ok(smoke.includes('"drive"'));
  assert.ok(smoke.includes('"upload"'));
});
