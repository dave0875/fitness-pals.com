import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const root = path.dirname(new URL(import.meta.url).pathname);
const read = (relative) => fs.readFileSync(path.join(root, relative), "utf8");
const contract = JSON.parse(read("config/electric-form.json"));
const shell = read("components/AuthenticatedShell.js");
const shellCss = read("styles/AuthenticatedShell.module.css");
const athleteCss = read("styles/AthletePages.module.css");
const privacy = read("pages/privacy.js");
const pkg = JSON.parse(read("package.json"));

test("Final Cut makes Electric Form the authenticated product default", () => {
  assert.equal(contract.finalCut.authenticatedShellDefault, "electric");
  assert.equal(contract.finalCut.legacyAuthenticatedFallbackAllowed, false);
  assert.deepEqual(contract.finalCut.preservesPhases, [0, 1, 2, 3, 4, 5]);
  assert.match(shell, /variant = "electric"/);
  assert.match(shell, /data-electric-form="final-cut"/);
  assert.match(shellCss, /color-scheme:\s*dark/);
  assert.match(shellCss, /--ef-color-surface:\s*#111712/);
  assert.match(shellCss, /--ef-color-primary:\s*var\(--ef-color-electric\)/);
});

test("secondary authenticated surfaces cannot opt back into the legacy shell", () => {
  const protectedSurfaces = [
    "pages/settings.js",
    "pages/training.js",
    "pages/journey.js",
    "pages/import/garmin-archive.js",
    "pages/activities/[id].js",
    "pages/dossiers/index.js",
    "pages/dossiers/[id].js",
  ];
  for (const file of protectedSurfaces) {
    const source = read(file);
    assert.match(source, /AuthenticatedShell/);
    assert.doesNotMatch(source, /variant="standard"/);
  }
});

test("Final Cut removes bright legacy control islands and retains interaction boundaries", () => {
  assert.doesNotMatch(athleteCss, /background:\s*white;/);
  assert.match(athleteCss, /background:\s*var\(--ef-color-surface\)/);
  assert.match(shellCss, /:where\(a, button, input, select, textarea, summary\):focus-visible/);
  assert.match(shellCss, /@media \(max-width:\s*520px\)/);
  assert.match(shellCss, /min-height:\s*44px/);
  assert.match(shellCss, /@media \(prefers-reduced-motion:\s*reduce\)/);
});

test("public privacy remains standalone and joins the Electric Form visual family without semantic edits", () => {
  assert.equal(contract.finalCut.publicLegalVisualFamily, "electric-form");
  assert.doesNotMatch(privacy, /AuthenticatedShell|authenticatedFetch|authenticatedJson/);
  assert.match(privacy, /radial-gradient\(circle at 72% -12%/);
  assert.match(privacy, /var\(--ef-color-electric\)/);
  assert.match(privacy, /david\.barker@fitness-pals\.com/);
  assert.match(privacy, /Garmin archive import is separate from Garmin's official developer APIs/);
});

test("Final Cut preserves Amanda and Sonic Body safety contracts", () => {
  const amanda = read("components/AmandaPresence.js");
  const sound = read("lib/electricFormAudio.mjs");
  assert.equal(contract.amanda.autoplayVoice, false);
  assert.equal(contract.sound.defaultEnabled, false);
  assert.equal(contract.sound.autoplay, false);
  assert.equal(contract.sound.userInitiatedPlaybackRequired, true);
  assert.equal(contract.sound.reducedSensorySuppressesCues, true);
  assert.match(amanda, /amanda-listen/);
  assert.match(amanda, /amanda-speak/);
  assert.match(amanda, /Voice never autoplays/);
  assert.match(sound, /not-user-initiated/);
  assert.match(sound, /reduced-sensory/);
});

test("Final Cut adds no runtime dependency or media escape hatch", () => {
  assert.deepEqual(
    Object.keys(pkg.dependencies).sort(),
    ["axios", "next", "react", "react-dom"]
  );
  const performance = read("scripts/check-performance-budgets.js");
  for (const route of ["/today", "/coach", "/progress", "/training", "/settings", "/welcome"]) {
    assert.ok(performance.includes(`"${route}"`));
  }
  assert.match(performance, /maxElectricFormMediaTotalBytes/);
});
