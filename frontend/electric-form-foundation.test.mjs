import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  isElectricFormSoundEnabled,
  playElectricFormCue,
  setElectricFormSoundEnabled,
} from "./lib/electricFormAudio.mjs";

const root = path.dirname(new URL(import.meta.url).pathname);
const contract = JSON.parse(
  fs.readFileSync(path.join(root, "config", "electric-form.json"), "utf8")
);

function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
  };
}

test("Electric Form sound is opt-in and user initiated", () => {
  const storage = memoryStorage();
  let contexts = 0;

  class FakeAudioContext {
    constructor() {
      contexts += 1;
      this.currentTime = 0;
      this.destination = {};
    }
    createOscillator() {
      return {
        type: "",
        frequency: { value: 0 },
        connect() {},
        start() {},
        stop() {},
        addEventListener() {},
      };
    }
    createGain() {
      return { gain: { value: 0 }, connect() {} };
    }
  }

  assert.equal(contract.sound.defaultEnabled, false);
  assert.equal(contract.sound.autoplay, false);
  assert.equal(contract.sound.userInitiatedPlaybackRequired, true);
  assert.equal(isElectricFormSoundEnabled(storage), false);
  assert.equal(
    playElectricFormCue("confirm", {
      userInitiated: true,
      storage,
      AudioContextCtor: FakeAudioContext,
    }),
    false
  );
  assert.equal(contexts, 0);

  assert.equal(setElectricFormSoundEnabled(true, storage), true);
  assert.equal(isElectricFormSoundEnabled(storage), true);
  assert.equal(
    playElectricFormCue("confirm", {
      userInitiated: false,
      storage,
      AudioContextCtor: FakeAudioContext,
    }),
    false
  );
  assert.equal(contexts, 0);

  assert.equal(
    playElectricFormCue("confirm", {
      userInitiated: true,
      storage,
      AudioContextCtor: FakeAudioContext,
    }),
    true
  );
  assert.equal(contexts, 1);
});

test("Electric Form tokens and reduced-motion contract are globally installed", () => {
  const css = fs.readFileSync(path.join(root, "styles", "electric-form.css"), "utf8");
  const app = fs.readFileSync(path.join(root, "pages", "_app.js"), "utf8");
  const shell = fs.readFileSync(path.join(root, "styles", "AuthenticatedShell.module.css"), "utf8");
  const athlete = fs.readFileSync(path.join(root, "styles", "AthletePages.module.css"), "utf8");

  assert.match(app, /electric-form\.css/);
  assert.match(css, /--ef-color-electric:/);
  assert.match(css, /--ef-motion-base:/);
  assert.match(css, /prefers-reduced-motion:\s*reduce/);
  assert.match(shell, /var\(--ef-color-primary\)/);
  assert.match(athlete, /var\(--ef-color-primary\)/);
});

test("Electric Form contract protects Amanda, media, and accessibility boundaries", () => {
  assert.equal(contract.motion.reducedMotion, "required");
  assert.deepEqual(contract.motion.compositorProperties, ["transform", "opacity"]);
  assert.equal(contract.amanda.neverBlocking, true);
  assert.equal(contract.amanda.autoplayVoice, false);
  assert.deepEqual(contract.imagery.representation, ["women", "men", "mixed-athlete scenes"]);
  assert.equal(contract.accessibility.minimumInteractiveTargetPx, 44);
  assert.equal(contract.accessibility.soundRequiresNonAudioEquivalent, true);
  assert.ok(contract.budgets.maxHeroImageBytes > 0);
  assert.ok(contract.budgets.maxSoundCueBytes > 0);
});


test("Electric Form media directory stays inside contract budgets", () => {
  const assetRoot = path.join(root, "public", "electric-form");
  if (!fs.existsSync(assetRoot)) return;

  const files = [];
  const visit = (directory) => {
    for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
      const filePath = path.join(directory, entry.name);
      if (entry.isDirectory()) visit(filePath);
      else files.push(filePath);
    }
  };
  visit(assetRoot);

  let totalBytes = 0;
  for (const file of files) {
    const bytes = fs.statSync(file).size;
    totalBytes += bytes;
    if (/\.(mp3|wav|ogg|m4a|aac)$/i.test(file)) {
      assert.ok(bytes <= contract.budgets.maxSoundCueBytes, `${file} exceeds sound budget`);
    }
    if (/\.(avif|webp|png|jpe?g)$/i.test(file)) {
      const limit = /hero/i.test(path.basename(file))
        ? contract.budgets.maxHeroImageBytes
        : contract.budgets.maxSupportingImageBytes;
      assert.ok(bytes <= limit, `${file} exceeds image budget`);
    }
  }

  assert.ok(
    totalBytes <= contract.budgets.maxElectricFormMediaTotalBytes,
    "Electric Form media exceeds total budget"
  );
});
