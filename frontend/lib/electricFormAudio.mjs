export const ELECTRIC_FORM_SOUND_STORAGE_KEY = "fitness-pals:electric-form:sound";

export const ELECTRIC_FORM_SOUND_CUES = Object.freeze({
  focus: Object.freeze({ frequencyHz: 330, durationMs: 45, gain: 0.018 }),
  confirm: Object.freeze({ frequencyHz: 520, durationMs: 70, gain: 0.024 }),
  progress: Object.freeze({ frequencyHz: 410, durationMs: 55, gain: 0.02 }),
  celebrate: Object.freeze({ frequencyHz: 660, durationMs: 95, gain: 0.025 }),
});

function defaultStorage() {
  try {
    return globalThis?.localStorage ?? null;
  } catch (_error) {
    return null;
  }
}

export function isElectricFormSoundEnabled(storage = defaultStorage()) {
  try {
    return storage?.getItem(ELECTRIC_FORM_SOUND_STORAGE_KEY) === "enabled";
  } catch (_error) {
    return false;
  }
}

export function setElectricFormSoundEnabled(enabled, storage = defaultStorage()) {
  if (!storage) return false;
  try {
    storage.setItem(
      ELECTRIC_FORM_SOUND_STORAGE_KEY,
      enabled ? "enabled" : "disabled"
    );
    return true;
  } catch (_error) {
    return false;
  }
}

export function playElectricFormCue(
  cueName,
  {
    userInitiated = false,
    storage = defaultStorage(),
    AudioContextCtor = globalThis?.AudioContext ?? globalThis?.webkitAudioContext,
  } = {}
) {
  const cue = ELECTRIC_FORM_SOUND_CUES[cueName];
  if (!cue || !userInitiated || !isElectricFormSoundEnabled(storage) || !AudioContextCtor) {
    return false;
  }

  const context = new AudioContextCtor();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  oscillator.type = "sine";
  oscillator.frequency.value = cue.frequencyHz;
  gain.gain.value = cue.gain;
  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start();
  oscillator.stop(context.currentTime + cue.durationMs / 1000);
  oscillator.addEventListener?.("ended", () => context.close?.(), { once: true });
  return true;
}
