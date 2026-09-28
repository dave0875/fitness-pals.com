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

test("Human Heat repair declares magnetic service without weakening adult-only boundaries", () => {
  assert.equal(media.version, "human-heat-v1.1");
  assert.equal(media.contractMarker, "human-heat-v1");
  assert.equal(media.artDirection.marker, "magnetic-service-v2");
  assert.deepEqual(
    media.representation.required,
    ["adult woman athlete", "adult man athlete"]
  );
  assert.equal(media.representation.minorsAllowed, false);
  assert.equal(media.representation.sensualEditorialFramingAllowed, true);
  assert.equal(media.representation.explicitSexualFramingAllowed, false);
  assert.equal(media.representation.objectifyingFramingAllowed, false);
  assert.equal(media.representation.serviceOrientationRequired, true);
  assert.equal(media.playback.autoplayAudio, false);
  assert.equal(media.playback.autoplayVideo, false);
  assert.ok(media.artDirection.relationshipCues.includes("attentive service"));

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

test("landing entry makes the customer the emotional center of Human Heat", () => {
  assert.match(index, /Your ambition\./);
  assert.match(index, /Our full attention\./);
  assert.match(index, /Guidance that stays centered on you/);
  assert.match(component, /data-art-direction={media\.artDirection\.marker}/);
  assert.match(component, /YOU HAVE OUR ATTENTION/);
  assert.match(component, /Built to notice\. Ready to guide\./);
  assert.match(component, /FORM \/ AMBITION \/ ATTENTION/);
  assert.match(styles, /Human Heat manual repair: Magnetic Service/);
  assert.match(styles, /#debc74/);
});

test("landing entry keeps responsive, truthful, non-autoplay product boundaries", () => {
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
  assert.match(component, /ILLUSTRATIVE READINESS/);
  assert.match(component, /not your athlete data/);
  assert.doesNotMatch(component, /<video|<audio|autoPlay/i);
});

test("Human Heat preserves auth, Amanda, privacy, reduced motion, and myChat boundary", () => {
  assert.match(index, /DEFAULT_AUTH_NEXT = "\/today"/);
  assert.match(index, /\/auth\/login\?next=/);
  assert.match(index, /Amanda · coach online/);
  assert.match(index, /href="\/privacy"/);
  assert.match(index, /Voice never autoplays/);
  assert.doesNotMatch(component + index, /myChat|biometric|SpeechRecognition|speechSynthesis/);
  assert.match(styles, /prefers-reduced-motion:reduce/);
});

test("performance tooling still budgets the public route and Human Heat transfer envelope", () => {
  assert.match(performance, /HUMAN_HEAT/);
  assert.match(performance, /maxVitalPresenceMediaTotalBytes/);
  assert.match(performance, /const routes = \["\/", "\/today"/);
  assert.ok(
    media.assets.reduce((sum, asset) => sum + asset.maxBytes, 0) <= 1572864
  );
});

test("Human Heat repair adds no client-side media dependency", () => {
  assert.deepEqual(
    Object.keys(pkg.dependencies).sort(),
    ["axios", "next", "react", "react-dom"]
  );
});
