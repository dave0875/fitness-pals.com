import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

import {
  electricFormCueDecision,
  electricFormSoundController,
  playElectricFormSemanticCue,
  readElectricFormSoundPreferences,
  setElectricFormReducedSensory,
  setElectricFormSoundEnabled,
  setElectricFormSoundMuted,
} from "./lib/electricFormAudio.mjs";

const root = path.dirname(new URL(import.meta.url).pathname);

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

function fakeAudioContext(counter) {
  return class FakeAudioContext {
    constructor() {
      counter.count += 1;
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
  };
}

test("Sonic Body contract remains silent by default and declares sensory persistence", () => {
  const contract = JSON.parse(
    fs.readFileSync(path.join(root, "config", "electric-form.json"), "utf8")
  );
  assert.equal(contract.sound.defaultEnabled, false);
  assert.equal(contract.sound.autoplay, false);
  assert.equal(contract.sound.userInitiatedPlaybackRequired, true);
  assert.equal(contract.sound.reducedSensorySuppressesCues, true);
  assert.deepEqual(contract.sound.persistedPreferences, ["enabled", "muted", "reducedSensory"]);
  assert.equal(contract.sound.semanticCues["amanda-listen"], "focus");
});

test("Sonic Body preferences are persisted and initialization is silent", () => {
  const storage = memoryStorage();
  const counter = { count: 0 };
  const AudioContextCtor = fakeAudioContext(counter);

  assert.deepEqual(readElectricFormSoundPreferences(storage), {
    enabled: false,
    muted: false,
    reducedSensory: false,
  });
  assert.equal(counter.count, 0);

  assert.equal(setElectricFormSoundEnabled(true, storage), true);
  assert.equal(setElectricFormSoundMuted(true, storage), true);
  assert.equal(setElectricFormReducedSensory(true, storage), true);
  assert.deepEqual(readElectricFormSoundPreferences(storage), {
    enabled: true,
    muted: true,
    reducedSensory: true,
  });
  assert.equal(counter.count, 0, "preference hydration/writes must never construct audio");

  assert.equal(
    playElectricFormSemanticCue("action-confirmed", {
      storage,
      AudioContextCtor,
      userInitiated: false,
    }),
    false
  );
  assert.equal(counter.count, 0, "non-user-initiated paths must remain silent");
});

test("central cue policy blocks disabled, muted, reduced-sensory, and autoplay paths", () => {
  const storage = memoryStorage();
  assert.deepEqual(electricFormCueDecision("confirm", { storage, userInitiated: true }), {
    allowed: false,
    reason: "disabled",
  });

  setElectricFormSoundEnabled(true, storage);
  assert.deepEqual(electricFormCueDecision("confirm", { storage, userInitiated: false }), {
    allowed: false,
    reason: "not-user-initiated",
  });

  setElectricFormSoundMuted(true, storage);
  assert.equal(electricFormCueDecision("confirm", { storage, userInitiated: true }).reason, "muted");

  setElectricFormSoundMuted(false, storage);
  setElectricFormReducedSensory(true, storage);
  assert.equal(
    electricFormCueDecision("confirm", { storage, userInitiated: true }).reason,
    "reduced-sensory"
  );

  setElectricFormReducedSensory(false, storage);
  assert.equal(electricFormCueDecision("confirm", { storage, userInitiated: true }).allowed, true);
  assert.equal(typeof electricFormSoundController.play, "function");
});

test("Amanda semantic cues remain gesture-gated", () => {
  const storage = memoryStorage();
  const counter = { count: 0 };
  const AudioContextCtor = fakeAudioContext(counter);
  setElectricFormSoundEnabled(true, storage);

  assert.equal(
    playElectricFormSemanticCue("amanda-listen", { storage, AudioContextCtor }),
    false
  );
  assert.equal(counter.count, 0);
  assert.equal(
    playElectricFormSemanticCue("amanda-listen", {
      storage,
      AudioContextCtor,
      userInitiated: true,
    }),
    true
  );
  assert.equal(counter.count, 1);
});

test("Sonic Body UI exposes visible controls and no effect-driven playback", () => {
  const control = fs.readFileSync(path.join(root, "components", "ElectricFormSoundControl.js"), "utf8");
  const amanda = fs.readFileSync(path.join(root, "components", "AmandaPresence.js"), "utf8");
  const shell = fs.readFileSync(path.join(root, "components", "AuthenticatedShell.js"), "utf8");

  assert.match(control, /Enable sound cues/);
  assert.match(control, /Mute cues/);
  assert.match(control, /Reduced sensory mode/);
  assert.match(control, /never autoplay/i);
  assert.match(shell, /ElectricFormSoundControl/);
  assert.match(amanda, /amanda-listen/);
  assert.match(amanda, /amanda-speak/);
  assert.match(amanda, /amanda-stop/);

  for (const source of [control, amanda, shell]) {
    const effectRegions = source.match(/useEffect\([\s\S]*?\n\s*\},\s*\[[^\]]*\]\);/g) || [];
    for (const effect of effectRegions) {
      assert.doesNotMatch(effect, /\.play\(|playElectricForm/, "effects must not trigger sound");
    }
  }
});
