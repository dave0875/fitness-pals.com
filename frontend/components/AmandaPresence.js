import { useEffect, useRef, useState } from "react";

import { electricFormSoundController } from "../lib/electricFormAudio.mjs";
import styles from "../styles/AthletePages.module.css";

const STATE_LABELS = {
  ambient: "Ready",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
  unavailable: "Voice unavailable",
};

function browserCapabilities() {
  if (typeof window === "undefined") {
    return { recognition: false, speech: false };
  }
  return {
    recognition: Boolean(window.SpeechRecognition || window.webkitSpeechRecognition),
    speech: Boolean(window.speechSynthesis && window.SpeechSynthesisUtterance),
  };
}

export default function AmandaPresence({ busy = false, latestAnswer = "", onTranscript }) {
  const recognitionRef = useRef(null);
  const [voiceState, setVoiceState] = useState("ambient");
  const [lastTranscript, setLastTranscript] = useState("");
  const [hydrated, setHydrated] = useState(false);
  const [capabilities, setCapabilities] = useState({ recognition: false, speech: false });

  useEffect(() => {
    setCapabilities(browserCapabilities());
    setHydrated(true);
    return () => {
      try {
        recognitionRef.current?.abort?.();
      } catch (_error) {
        // Browser speech engines can throw while they are already ending.
      }
      window.speechSynthesis?.cancel?.();
    };
  }, []);

  const displayedState =
    hydrated && !capabilities.recognition && !capabilities.speech
      ? "unavailable"
      : busy && voiceState !== "listening" && voiceState !== "speaking"
        ? "thinking"
        : voiceState;

  function stopVoice() {
    electricFormSoundController.play("amanda-stop", { userInitiated: true });
    try {
      recognitionRef.current?.abort?.();
    } catch (_error) {
      // Treat a browser engine that is already stopped as stopped.
    }
    window.speechSynthesis?.cancel?.();
    recognitionRef.current = null;
    setVoiceState("ambient");
  }

  function startListening() {
    if (!capabilities.recognition) {
      setVoiceState("unavailable");
      return;
    }

    // Listening is always a user gesture. Starting it also barges into local speech.
    electricFormSoundController.play("amanda-listen", { userInitiated: true });
    window.speechSynthesis?.cancel?.();
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const recognition = new Recognition();
    recognitionRef.current = recognition;
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";

    recognition.onstart = () => setVoiceState("listening");
    recognition.onresult = (event) => {
      const results = Array.from(event.results || []);
      const transcript = results
        .map((result) => result?.[0]?.transcript || "")
        .join(" ")
        .trim();
      if (transcript) setLastTranscript(transcript);

      const finalizedTranscript = results
        .slice(event.resultIndex || 0)
        .filter((result) => result?.isFinal)
        .map((result) => result?.[0]?.transcript || "")
        .join(" ")
        .trim();
      if (finalizedTranscript) onTranscript?.(finalizedTranscript);
    };
    recognition.onerror = () => setVoiceState("unavailable");
    recognition.onend = () => {
      recognitionRef.current = null;
      setVoiceState("ambient");
    };

    try {
      recognition.start();
    } catch (_error) {
      recognitionRef.current = null;
      setVoiceState("unavailable");
    }
  }

  function speakLatest() {
    if (!capabilities.speech || !latestAnswer) {
      if (!capabilities.speech) setVoiceState("unavailable");
      return;
    }

    // Speech is never automatic. This path is reachable only from the athlete's button.
    electricFormSoundController.play("amanda-speak", { userInitiated: true });
    window.speechSynthesis.cancel();
    const utterance = new window.SpeechSynthesisUtterance(latestAnswer);
    utterance.lang = "en-US";
    utterance.rate = 1;
    utterance.onstart = () => setVoiceState("speaking");
    utterance.onend = () => setVoiceState("ambient");
    utterance.onerror = () => setVoiceState("unavailable");
    window.speechSynthesis.speak(utterance);
  }

  const voiceActive = displayedState === "listening" || displayedState === "speaking";

  return (
    <aside
      className={styles.amandaStage}
      data-amanda-state={displayedState}
      aria-label="Amanda voice controls"
    >
      <div className={styles.amandaPortrait} aria-hidden="true">
        <span className={styles.amandaPortraitGlow} />
        <span className={styles.amandaPortraitMark}>A</span>
      </div>

      <div className={styles.amandaStageCopy}>
        <div className={styles.amandaStageHeading}>
          <div>
            <p className={styles.eyebrow}>Amanda · coach presence</p>
            <h2>Talk, type, or move between both.</h2>
          </div>
          <span className={styles.amandaState} role="status" aria-live="polite">
            <i aria-hidden="true" />
            {STATE_LABELS[displayedState]}
          </span>
        </div>

        <p className={styles.amandaVoiceNote}>
          Voice never autoplays. The microphone starts only when you press Listen.
          Browser speech support varies by device; the text composer always remains available.
        </p>

        <div className={styles.amandaVoiceControls}>
          <button
            className={styles.primaryButton}
            type="button"
            onClick={startListening}
            disabled={!hydrated || !capabilities.recognition || displayedState === "listening"}
          >
            {displayedState === "listening" ? "Listening…" : "Listen"}
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={speakLatest}
            disabled={!hydrated || !capabilities.speech || !latestAnswer || displayedState === "speaking"}
          >
            {displayedState === "speaking" ? "Speaking…" : "Read latest reply"}
          </button>
          <button
            className={styles.secondaryButton}
            type="button"
            onClick={stopVoice}
            disabled={!voiceActive}
          >
            Stop voice
          </button>
        </div>

        <div className={styles.amandaTranscript} aria-live="polite">
          <span>Voice transcript</span>
          <p>{lastTranscript || "Recognized speech will appear here and in your question draft."}</p>
        </div>
      </div>
    </aside>
  );
}
