const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.join(__dirname, "..");
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");

function literalHrefs(source) {
  const hrefs = [];
  const patterns = [
    /href\s*=\s*["']([^"']+)["']/g,
    /href\s*:\s*["']([^"']+)["']/g,
  ];
  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) hrefs.push(match[1]);
  }
  return hrefs;
}

function supportedInternalHref(href) {
  if (!href.startsWith("/")) return true;
  const clean = href.split("?")[0].split("#")[0];
  return [
    "/",
    "/today",
    "/dashboard",
    "/coach",
    "/progress",
    "/journey",
    "/training",
    "/settings",
    "/welcome",
    "/privacy",
    "/dossiers",
    "/import/garmin-archive",
    "/activities/",
    "/auth/",
    "/api/",
  ].some((prefix) => clean === prefix || clean.startsWith(prefix));
}

test("Phase 8 defines all seven release journeys from the real product entry points", async () => {
  const contract = await import("../lib/productV2ReleaseContract.mjs");
  assert.deepEqual(
    contract.CRITICAL_JOURNEYS.map((journey) => journey.key),
    [
      "new_athlete",
      "returning_athlete",
      "workout_analysis",
      "training_decision",
      "broken_connection",
      "failed_job",
      "mobile",
    ]
  );
  for (const journey of contract.CRITICAL_JOURNEYS) {
    assert.ok(journey.entry.startsWith("/"));
    assert.ok(journey.checkpoints.length >= 2);
  }
});

test("whole-site athlete action audit rejects unsupported internal links and legacy pseudo-destinations", () => {
  const files = [
    "components/AuthenticatedShell.js",
    "pages/index.js",
    "pages/welcome.js",
    "pages/dashboard.js",
    "pages/coach.js",
    "pages/journey.js",
    "pages/progress.js",
    "pages/training.js",
    "pages/settings.js",
    "pages/import/garmin-archive.js",
    "pages/dossiers/index.js",
    "pages/activities/[id].js",
  ];
  const hrefs = files.flatMap((file) => literalHrefs(read(file)));
  assert.ok(hrefs.length > 20, "expected a meaningful athlete-facing link inventory");
  for (const href of hrefs) {
    assert.ok(supportedInternalHref(href), `unsupported internal href: ${href}`);
  }
  const all = files.map(read).join("\n");
  assert.ok(!all.includes("/dashboard#coach"));
  assert.ok(!all.includes("/journey#activities"));
});

test("changed core flows retain WCAG-oriented landmarks, focus, status, and touch targets", () => {
  const shell = read("components/AuthenticatedShell.js");
  const css = read("styles/AthletePages.module.css");
  const welcome = read("pages/welcome.js");
  const coach = read("pages/coach.js");
  const settings = read("pages/settings.js");

  assert.match(shell, /Skip to content/);
  assert.match(shell, /id="main-content"/);
  assert.match(shell, /aria-label="Primary navigation"/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /min-height:\s*44px/);
  assert.match(css, /@media \(max-width:\s*720px\)/);
  assert.match(welcome, /aria-live="polite"/);
  assert.match(coach, /aria-live="polite"/);
  assert.match(settings, /role="status"/);
  assert.match(settings, /aria-busy=/);
});

test("privacy-safe UX telemetry is allowlisted and wired without URL or athlete payloads", async () => {
  const telemetry = read("lib/uxTelemetry.mjs");
  const shell = read("components/AuthenticatedShell.js");
  const contract = await import("../lib/productV2ReleaseContract.mjs");

  assert.equal(
    contract.validateUxEvent({
      event: "surface_view",
      surface: "today",
      viewport: "mobile",
    }),
    true
  );
  assert.equal(
    contract.validateUxEvent({
      event: "surface_view",
      surface: "today",
      viewport: "mobile",
      query: "How was my run?",
    }),
    false
  );
  assert.match(telemetry, /"\/api\/ux-events"/);
  assert.match(shell, /trackUxEvent/);
  for (const forbidden of ["location.href", "router.asPath,", "activity_id", "message:"]) {
    assert.ok(!telemetry.includes(forbidden), `telemetry must not include ${forbidden}`);
  }
});

test("performance budgets are enforced in the deployable frontend image", async () => {
  const pkg = JSON.parse(read("package.json"));
  const dockerfile = read("Dockerfile");
  const script = read("scripts/check-performance-budgets.js");
  const contract = await import("../lib/productV2ReleaseContract.mjs");

  assert.equal(pkg.scripts["check:performance"], "node scripts/check-performance-budgets.js");
  assert.match(dockerfile, /npm run build && npm run check:performance/);
  assert.ok(contract.PERFORMANCE_BUDGETS.maxRouteJsBytes > 0);
  assert.ok(contract.PERFORMANCE_BUDGETS.maxCriticalJsBytes > contract.PERFORMANCE_BUDGETS.maxRouteJsBytes);
  assert.match(script, /build-manifest\.json/);
  assert.match(script, /process\.exit\(1\)/);
});

test("production smoke emits the Phase 8 deployed acceptance report", () => {
  const smoke = read("../scripts/smoke_production.py");
  for (const journey of [
    "new_athlete",
    "returning_athlete",
    "workout_analysis",
    "training_decision",
    "broken_connection",
    "failed_job",
    "mobile",
  ]) {
    assert.ok(smoke.includes(journey), `missing production acceptance journey ${journey}`);
  }
  assert.match(smoke, /Phase 8 acceptance report/);
});
