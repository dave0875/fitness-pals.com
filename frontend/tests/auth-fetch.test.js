const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const helperPromise = import("../lib/authFetch.mjs");
const response = (status, body = {}) => ({
  status,
  ok: status >= 200 && status < 300,
  json: async () => body,
});

test("concurrent 401 responses share one refresh and retry each request once", async () => {
  const { authenticatedFetch } = await helperPromise;
  let releaseRefresh;
  const refreshGate = new Promise((resolve) => { releaseRefresh = resolve; });
  let refreshCalls = 0;
  const attempts = new Map();
  const fakeFetch = async (input) => {
    if (input === "/auth/refresh") {
      refreshCalls += 1;
      await refreshGate;
      return response(204);
    }
    const count = (attempts.get(input) || 0) + 1;
    attempts.set(input, count);
    return response(count === 1 ? 401 : 200);
  };

  const first = authenticatedFetch("/api/one", {}, fakeFetch);
  const second = authenticatedFetch("/api/two", {}, fakeFetch);
  await new Promise((resolve) => setImmediate(resolve));
  assert.equal(refreshCalls, 1);
  releaseRefresh();

  assert.equal((await first).status, 200);
  assert.equal((await second).status, 200);
  assert.deepEqual(Object.fromEntries(attempts), { "/api/one": 2, "/api/two": 2 });
});

test("failed refresh returns the original 401 without retry loops", async () => {
  const { authenticatedFetch } = await helperPromise;
  const calls = [];
  const fakeFetch = async (input) => {
    calls.push(input);
    return response(input === "/auth/refresh" ? 401 : 401);
  };

  const result = await authenticatedFetch("/api/protected", {}, fakeFetch);

  assert.equal(result.status, 401);
  assert.deepEqual(calls, ["/api/protected", "/auth/refresh"]);
});

test("the refresh endpoint never recursively refreshes, including with a query", async () => {
  const { authenticatedFetch } = await helperPromise;
  const calls = [];
  const fakeFetch = async (input) => {
    calls.push(input);
    return response(401);
  };

  assert.equal((await authenticatedFetch("/auth/refresh?source=test", {}, fakeFetch)).status, 401);
  assert.deepEqual(calls, ["/auth/refresh?source=test"]);
});

test("authenticated JSON serializes bodies and surfaces response status", async () => {
  const { authenticatedJson } = await helperPromise;
  let observed;
  const fakeFetch = async (input, init) => {
    observed = { input, init };
    return response(200, { accepted: true });
  };

  assert.deepEqual(
    await authenticatedJson("/api/write", { method: "POST", json: { value: 7 } }, fakeFetch),
    { accepted: true }
  );
  assert.equal(observed.init.body, JSON.stringify({ value: 7 }));
  assert.equal(observed.init.headers["Content-Type"], "application/json");

  await assert.rejects(
    authenticatedJson("/api/fail", {}, async () => response(403)),
    (error) => error.status === 403
  );
});

test("all protected first-party browser requests use the shared refresh boundary", () => {
  const root = path.join(__dirname, "..");
  const protectedFiles = [
    "components/AuthenticatedShell.js",
    "pages/index.js",
    "pages/welcome.js",
    "pages/import/garmin-archive.js",
    "pages/dashboard.js",
    "pages/journey.js",
    "pages/activities/[id].js",
    "pages/dossiers/index.js",
    "pages/dossiers/[id].js",
  ];
  for (const relativePath of protectedFiles) {
    const source = fs.readFileSync(path.join(root, relativePath), "utf8");
    assert.match(source, /authenticated(?:Fetch|Json)/, relativePath);
  }
  for (const relativePath of protectedFiles.slice(4)) {
    const source = fs.readFileSync(path.join(root, relativePath), "utf8");
    assert.ok(!source.includes('from "axios"'), relativePath);
  }

  const archiveSource = fs.readFileSync(
    path.join(root, "pages/import/garmin-archive.js"),
    "utf8"
  );
  assert.ok(archiveSource.includes("fetch(start.upload.url"));
  assert.ok(!archiveSource.includes("authenticatedFetch(start.upload.url"));
});
