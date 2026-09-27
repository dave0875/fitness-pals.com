import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = path.resolve(process.cwd());
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const media = JSON.parse(read("config/human-heat-media.json"));
const index = read("pages/index.js");
const component = read("components/HumanHeatMedia.js");
const styles = read("styles/ElectricEntry.module.css");
const performance = read("scripts/check-performance-budgets.js");
const pkg = JSON.parse(read("package.json"));

test("Human Heat ships a bounded adult woman + adult man media contract", () => {
  assert.equal(media.version, "human-heat-v1");
  assert.equal(media.contractMarker, "human-heat-v1");
  assert.deepEqual(
    media.representation.required,
    ["adult woman athlete", "adult man athlete"]
  );
  assert.equal(media.representation.minorsAllowed, false);
  assert.equal(media.representation.sexualizedFramingAllowed, false);
  assert.equal(media.playback.autoplayAudio, false);
  assert.equal(media.playback.autoplayVideo, false);

  const roles = new Set(media.assets.map((asset) => asset.role));
  assert.ok(roles.has("adult woman athlete"));
  assert.ok(roles.has("adult man athlete"));

  for (const asset of media.assets) {
    assert.equal(asset.license, "Unsplash License");
    assert.match(asset.alt, /^Adult (woman|man) /);
    assert.ok(asset.maxBytes > 0);
    for (const name of ["desktop", "mobile"]) {
      const variant = asset.variants[name];
      const url = new URL(variant.src);
      assert.equal(url.origin, media.remoteOrigin);
      assert.equal(variant.format, "webp");
      assert.equal(url.searchParams.get("fm"), "webp");
      assert.equal(Number(url.searchParams.get("w")), variant.width);
      assert.equal(Number(url.searchParams.get("h")), variant.height);
      assert.ok(Number(url.searchParams.get("q")) <= asset.maxQuality);
    }
  }
});

test("landing entry replaces the abstract SVG with responsive Human Heat media", () => {
  assert.match(index, /import HumanHeatMedia/);
  assert.match(index, /<HumanHeatMedia \/>/);
  assert.doesNotMatch(index, /electric-entry-athletes\.svg/);
  assert.match(component, /data-contract={media\.contractMarker}/);
  assert.match(component, /<picture>/);
  assert.match(component, /media="\(max-width: 560px\)"/);
  assert.match(component, /srcSet={mobile\.src}/);
  assert.match(component, /alt={asset\.alt}/);
  assert.match(component, /width={desktop\.width}/);
  assert.match(component, /height={desktop\.height}/);
  assert.match(component, /loading={eager \? "eager" : "lazy"}/);
  assert.doesNotMatch(component, /<video|<audio|autoPlay/i);
});

test("Human Heat preserves auth, Amanda, privacy, truth, and reduced-motion boundaries", () => {
  assert.match(index, /DEFAULT_AUTH_NEXT = "\/today"/);
  assert.match(index, /\/auth\/login\?next=/);
  assert.match(index, /Amanda · coach online/);
  assert.match(index, /href="\/privacy"/);
  assert.match(component, /ILLUSTRATIVE READINESS/);
  assert.match(component, /not your athlete data/);
  assert.doesNotMatch(component + index, /myChat|biometric|SpeechRecognition|speechSynthesis/);
  assert.match(styles, /prefers-reduced-motion:reduce/);
});

test("performance tooling budgets the public route and Human Heat transfer envelope", () => {
  assert.match(performance, /HUMAN_HEAT/);
  assert.match(performance, /maxVitalPresenceMediaTotalBytes/);
  assert.match(performance, /const routes = \["\/", "\/today"/);
  assert.ok(
    media.assets.reduce((sum, asset) => sum + asset.maxBytes, 0) <= 1572864
  );
});

test("Human Heat does not add a client-side media dependency", () => {
  assert.deepEqual(
    Object.keys(pkg.dependencies).sort(),
    ["axios", "next", "react", "react-dom"]
  );
});
