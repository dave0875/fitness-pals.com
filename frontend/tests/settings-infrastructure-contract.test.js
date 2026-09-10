const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const settingsSource = fs.readFileSync(
  path.join(__dirname, "..", "pages", "settings.js"),
  "utf8",
);

test("athlete settings do not expose Influx infrastructure controls", () => {
  for (const forbidden of [
    "/api/datasource/influx",
    "Server address",
    "Organization",
    "Fitness data bucket",
    "Access token",
    "Advanced data source",
  ]) {
    assert.ok(!settingsSource.includes(forbidden), `unexpected athlete control: ${forbidden}`);
  }
});
