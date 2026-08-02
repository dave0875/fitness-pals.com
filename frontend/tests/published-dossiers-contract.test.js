const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const indexSource = fs.readFileSync(
  path.join(__dirname, "..", "pages", "coach-dossiers", "index.js"),
  "utf8"
);
const dynamicPagePath = path.join(__dirname, "..", "pages", "coach-dossiers", "[slug].js");

test("coach dossiers index merges static sample dossiers with public imported dossiers", () => {
  assert.match(
    indexSource,
    /\/api\/dossiers\/public/,
    "expected coach dossiers index to fetch public imported dossiers from the backend"
  );
});

test("dynamic coach dossier route exists for imported athlete dossiers", () => {
  assert.ok(
    fs.existsSync(dynamicPagePath),
    "expected frontend/pages/coach-dossiers/[slug].js to exist"
  );
  const dynamicSource = fs.readFileSync(dynamicPagePath, "utf8");

  assert.match(
    dynamicSource,
    /\/api\/dossiers\/public\//,
    "expected dynamic coach dossier page to load dossier HTML from the backend"
  );
});
