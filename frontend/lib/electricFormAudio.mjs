export const ELECTRIC_FORM_SOUND_STORAGE_KEY = "fitness-pals:electric-form:sound";
export const ELECTRIC_FORM_SOUND_MUTED_STORAGE_KEY = "fitness-pals:electric-form:muted";
export const ELECTRIC_FORM_REDUCED_SENSORY_STORAGE_KEY = "fitness-pals:electric-form:reduced-sensory";

export const ELECTRIC_FORM_SOUND_CUES = Object.freeze({
  focus: Object.freeze({ startHz: 330, endHz: 390, durationMs: 45, gain: 0.016, wave: "triangle" }),
  confirm: Object.freeze({ startHz: 480, endHz: 560, durationMs: 72, gain: 0.021, wave: "triangle" }),
  progress: Object.freeze({ startHz: 390, endHz: 475, durationMs: 62, gain: 0.018, wave: "sine" }),
  celebrate: Object.freeze({ startHz: 560, endHz: 700, durationMs: 96, gain: 0.022, wave: "triangle" }),
});

export const ELECTRIC_FORM_SEMANTIC_CUES = Object.freeze({
  "control-enabled": "confirm",
  "control-unmuted": "focus",
  navigation: "focus",
  "action-confirmed": "confirm",
  "progress-advanced": "progress",
  "milestone-earned": "celebrate",
  "amanda-listen": "focus",
  "amanda-speak": "progress",
  "amanda-stop": "confirm",
});

const DEFAULT_PREFERENCES = Object.freeze({
  enabled: false,
  muted: false,
  reducedSensory: false,
});

function defaultStorage() {
  try {
    return globalThis?.localStorage ?? null;
  } catch (_error) {
    return null;
  }
}

function readFlag(storage, key, enabledValue) {
  try {
    return storage?.getItem(key) === enabledValue;
  } catch (_error) {
    return false;
  }
}

export function readElectricFormSoundPreferences(storage = defaultStorage()) {
  return {
    enabled: readFlag(storage, ELECTRIC_FORM_SOUND_STORAGE_KEY, "enabled"),
    muted: readFlag(storage, ELECTRIC_FORM_SOUND_MUTED_STORAGE_KEY, "muted"),
    reducedSensory: readFlag(
      storage,
      ELECTRIC_FORM_REDUCED_SENSORY_STORAGE_KEY,
      "reduced"
    ),
  };
}

export function setElectricFormSoundPreferences(
  preferences,
  storage = defaultStorage()
) {
  if (!storage) return false;
  const next = { ...DEFAULT_PREFERENCES, ...preferences };
  try {
    storage.setItem(
      ELECTRIC_FORM_SOUND_STORAGE_KEY,
      next.enabled ? "enabled" : "disabled"
    );
    storage.setItem(
      ELECTRIC_FORM_SOUND_MUTED_STORAGE_KEY,
      next.muted ? "muted" : "unmuted"
    );
    storage.setItem(
      ELECTRIC_FORM_REDUCED_SENSORY_STORAGE_KEY,
      next.reducedSensory ? "reduced" : "standard"
    );
    return true;
  } catch (_error) {
    return false;
  }
}

export function isElectricFormSoundEnabled(storage = defaultStorage()) {
  return readElectricFormSoundPreferences(storage).enabled;
}

export function setElectricFormSoundEnabled(enabled, storage = defaultStorage()) {
  return setElectricFormSoundPreferences(
    { ...readElectricFormSoundPreferences(storage), enabled: Boolean(enabled) },
    storage
  );
}

export function setElectricFormSoundMuted(muted, storage = defaultStorage()) {
  return setElectricFormSoundPreferences(
    { ...readElectricFormSoundPreferences(storage), muted: Boolean(muted) },
    storage
  );
}

export function setElectricFormReducedSensory(reducedSensory, storage = defaultStorage()) {
  return setElectricFormSoundPreferences(
    {
      ...readElectricFormSoundPreferences(storage),
      reducedSensory: Boolean(reducedSensory),
    },
    storage
  );
}

export function electricFormCueDecision(
  cueName,
  { userInitiated = false, storage = defaultStorage() } = {}
) {
  if (!ELECTRIC_FORM_SOUND_CUES[cueName]) return { allowed: false, reason: "unknown-cue" };
  if (!userInitiated) return { allowed: false, reason: "not-user-initiated" };

  const preferences = readElectricFormSoundPreferences(storage);
  if (!preferences.enabled) return { allowed: false, reason: "disabled" };
  if (preferences.muted) return { allowed: false, reason: "muted" };
  if (preferences.reducedSensory) return { allowed: false, reason: "reduced-sensory" };
  return { allowed: true, reason: "allowed" };
}

function setParam(param, value, atTime) {
  if (typeof param?.setValueAtTime === "function") {
    param.setValueAtTime(value, atTime);
  } else if (param) {
    param.value = value;
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
  const decision = electricFormCueDecision(cueName, { userInitiated, storage });
  if (!decision.allowed || !AudioContextCtor) return false;

  const cue = ELECTRIC_FORM_SOUND_CUES[cueName];
  const context = new AudioContextCtor();
  const oscillator = context.createOscillator();
  const gain = context.createGain();
  const now = context.currentTime || 0;
  const end = now + cue.durationMs / 1000;

  oscillator.type = cue.wave;
  setParam(oscillator.frequency, cue.startHz, now);
  if (typeof oscillator.frequency?.exponentialRampToValueAtTime === "function") {
    oscillator.frequency.exponentialRampToValueAtTime(cue.endHz, end);
  }

  if (typeof gain.gain?.setValueAtTime === "function") {
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime?.(cue.gain, now + Math.min(0.012, cue.durationMs / 3000));
    gain.gain.exponentialRampToValueAtTime?.(0.0001, end);
  } else if (gain.gain) {
    gain.gain.value = cue.gain;
  }

  oscillator.connect(gain);
  gain.connect(context.destination);
  oscillator.start();
  oscillator.stop(end);
  oscillator.addEventListener?.("ended", () => context.close?.(), { once: true });
  return true;
}

export function playElectricFormSemanticCue(semanticName, options = {}) {
  const cueName = ELECTRIC_FORM_SEMANTIC_CUES[semanticName];
  if (!cueName) return false;
  return playElectricFormCue(cueName, options);
}

export const electricFormSoundController = Object.freeze({
  readPreferences: readElectricFormSoundPreferences,
  setPreferences: setElectricFormSoundPreferences,
  setEnabled: setElectricFormSoundEnabled,
  setMuted: setElectricFormSoundMuted,
  setReducedSensory: setElectricFormReducedSensory,
  cueDecision: electricFormCueDecision,
  playCue: playElectricFormCue,
  play: playElectricFormSemanticCue,
});
