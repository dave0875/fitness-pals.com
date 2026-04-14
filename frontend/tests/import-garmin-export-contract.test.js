const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const pagePath = path.join(__dirname, "..", "pages", "import", "garmin-export.js");

test("garmin export import page exists and is authentication-aware", () => {
  assert.ok(fs.existsSync(pagePath), "expected frontend/pages/import/garmin-export.js to exist");
  const source = fs.readFileSync(pagePath, "utf8");

  assert.match(
    source,
    /\/api\/auth\/session/,
    "expected import page to probe the current authenticated session"
  );
  assert.match(
    source,
    /\/auth\/login\?next=%2Fimport%2Fgarmin-export|\/auth\/login\?next=\/import\/garmin-export/,
    "expected import page to route anonymous users through sign-in first"
  );
});

test("garmin export import page uses the async signed-upload flow for large archives", () => {
  const source = fs.readFileSync(pagePath, "utf8");

  assert.match(
    source,
    /\/api\/dossiers\/import\/garmin-export\/start/,
    "expected import page to request a signed upload plan from the backend first"
  );
  assert.match(
    source,
    /complete_url|\/complete/,
    "expected import page to mark the upload complete after storing the archive"
  );
  assert.match(
    source,
    /status_url|setInterval|\/api\/dossiers\/import\/garmin-export\/\$\{/,
    "expected import page to poll async job status until the dossier is ready"
  );
  assert.match(
    source,
    /Garmin Export|zip/i,
    "expected import page to describe the Garmin export zip flow"
  );
});
