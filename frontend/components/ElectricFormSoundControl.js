import { useEffect, useId, useState } from "react";

import { electricFormSoundController } from "../lib/electricFormAudio.mjs";
import styles from "../styles/ElectricFormSoundControl.module.css";

const PREFERENCE_EVENT = "fitness-pals:electric-form-preferences";
const DEFAULT_PREFERENCES = {
  enabled: false,
  muted: false,
  reducedSensory: false,
};

function statusLabel(preferences) {
  if (!preferences.enabled) return "Off";
  if (preferences.reducedSensory) return "Reduced sensory";
  if (preferences.muted) return "Muted";
  return "On";
}

export default function ElectricFormSoundControl({ compact = false }) {
  const descriptionId = useId();
  const [preferences, setPreferences] = useState(DEFAULT_PREFERENCES);

  useEffect(() => {
    const syncPreferences = () => {
      setPreferences(electricFormSoundController.readPreferences());
    };
    syncPreferences();
    window.addEventListener("storage", syncPreferences);
    window.addEventListener(PREFERENCE_EVENT, syncPreferences);
    return () => {
      window.removeEventListener("storage", syncPreferences);
      window.removeEventListener(PREFERENCE_EVENT, syncPreferences);
    };
  }, []);

  function savePreferences(next, semanticCue = null) {
    if (!electricFormSoundController.setPreferences(next)) return;
    setPreferences(next);
    window.dispatchEvent(new CustomEvent(PREFERENCE_EVENT));
    if (semanticCue) {
      electricFormSoundController.play(semanticCue, { userInitiated: true });
    }
  }

  function setEnabled(enabled) {
    const next = { ...preferences, enabled };
    savePreferences(next, enabled ? "control-enabled" : null);
  }

  function setMuted(muted) {
    const next = { ...preferences, muted };
    savePreferences(next, !muted && next.enabled && !next.reducedSensory ? "control-unmuted" : null);
  }

  function setReducedSensory(reducedSensory) {
    const next = { ...preferences, reducedSensory };
    savePreferences(
      next,
      !reducedSensory && next.enabled && !next.muted ? "control-unmuted" : null
    );
  }

  const controls = (
    <fieldset className={styles.fieldset} aria-describedby={descriptionId}>
      <legend>Sound &amp; sensory</legend>
      <p id={descriptionId} className={styles.description}>
        Interface cues are silent by default and never autoplay. Every cue reinforces a visible action.
      </p>
      <label className={styles.option}>
        <input
          type="checkbox"
          checked={preferences.enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        <span>
          <strong>Enable sound cues</strong>
          <small>Allow brief Electric Form interaction tones after your own actions.</small>
        </span>
      </label>
      <label className={styles.option}>
        <input
          type="checkbox"
          checked={preferences.muted}
          onChange={(event) => setMuted(event.target.checked)}
        />
        <span>
          <strong>Mute cues</strong>
          <small>Keep your opt-in saved while silencing interface tones.</small>
        </span>
      </label>
      <label className={styles.option}>
        <input
          type="checkbox"
          checked={preferences.reducedSensory}
          onChange={(event) => setReducedSensory(event.target.checked)}
        />
        <span>
          <strong>Reduced sensory mode</strong>
          <small>Suppress interface tones. Amanda voice remains explicit and button initiated.</small>
        </span>
      </label>
      <p className={styles.status} role="status" aria-live="polite">
        Sound cues: <strong>{statusLabel(preferences)}</strong>
      </p>
    </fieldset>
  );

  if (!compact) return <div className={styles.control}>{controls}</div>;

  return (
    <details className={styles.control + " " + styles.compact}>
      <summary aria-label={"Sound and sensory settings. Sound cues " + statusLabel(preferences) + "."}>
        <span aria-hidden="true">◉</span>
        Sound
      </summary>
      <div className={styles.panel}>{controls}</div>
    </details>
  );
}
