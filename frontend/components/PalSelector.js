import { useEffect, useMemo, useState } from "react";

import { authenticatedJson } from "../lib/authFetch.mjs";
import styles from "../styles/AthletePages.module.css";

const PAL_VISUALS = Object.freeze([
  {
    persona_id: "w16-golden-glow",
    candidate_id: "W16",
    display_name: "Golden Glow",
    visual_key: "W16",
    image: "/pals/w16-golden-glow.webp",
    alt: "Portrait of Golden Glow, Fitness Pal candidate W16.",
    framing: "portrait",
  },
  {
    persona_id: "w18-radiant-wellness",
    candidate_id: "W18",
    display_name: "Radiant Wellness",
    visual_key: "W18",
    image: "/pals/w18-radiant-wellness.webp",
    alt: "Portrait of Radiant Wellness, Fitness Pal candidate W18.",
    framing: "portrait",
  },
  {
    persona_id: "w21-confident-coaching",
    candidate_id: "W21",
    display_name: "Confident Coaching",
    visual_key: "W21",
    image: "/pals/w21-confident-coaching.webp",
    alt: "Portrait of Confident Coaching, Fitness Pal candidate W21.",
    framing: "portrait",
  },
  {
    persona_id: "w24-fresh-momentum",
    candidate_id: "W24",
    display_name: "Fresh Momentum",
    visual_key: "W24",
    image: "/pals/w24-fresh-momentum.webp",
    alt: "Portrait of Fresh Momentum, Fitness Pal candidate W24.",
    framing: "portrait",
  },
  {
    persona_id: "w51-tokyo-strength",
    candidate_id: "W51",
    display_name: "Tokyo Strength",
    visual_key: "W51",
    image: "/pals/w51-tokyo-strength.webp",
    alt: "Portrait of Tokyo Strength, Fitness Pal candidate W51.",
    framing: "upper-torso",
  },
]);

const PAL_BY_ID = Object.freeze(
  Object.fromEntries(PAL_VISUALS.map((pal) => [pal.persona_id, pal]))
);

function normalizeDiscovery(payload) {
  if (!payload || !Array.isArray(payload.personas)) return null;
  const discovered = new Map();
  for (const item of payload.personas) {
    if (!item || typeof item.persona_id !== "string") return null;
    const expected = PAL_BY_ID[item.persona_id];
    if (!expected || discovered.has(item.persona_id)) return null;
    if (
      item.candidate_id !== expected.candidate_id ||
      item.display_name !== expected.display_name ||
      item.visual_key !== expected.visual_key ||
      typeof item.runtime_available !== "boolean"
    ) {
      return null;
    }
    discovered.set(item.persona_id, {
      ...expected,
      runtime_available: item.runtime_available,
    });
  }
  if (discovered.size !== PAL_VISUALS.length) return null;
  return PAL_VISUALS.map((pal) => discovered.get(pal.persona_id));
}

function availabilityCopy(discovery, selected) {
  if (!discovery) return "Checking Pal availability…";
  if (discovery.state !== "ready") return "Pals are in preview today. Coach is ready.";
  if (selected?.runtime_available) return `${selected.display_name} is available to join this session.`;
  return "This Pal is in preview right now. Coach is ready.";
}

export default function PalSelector({ session = null, onSessionChange, onNotice }) {
  const [discovery, setDiscovery] = useState(null);
  const [personas, setPersonas] = useState(null);
  const [selectedId, setSelectedId] = useState(PAL_VISUALS[0].persona_id);
  const [busy, setBusy] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    let active = true;
    authenticatedJson("/api/pals/v1/personas")
      .then((payload) => {
        if (!active) return;
        const normalized = normalizeDiscovery(payload);
        if (!normalized) {
          setDiscovery(null);
          setPersonas(null);
          setLoadError("Pal availability could not be verified. Coach remains active.");
          onSessionChange?.(null);
          return;
        }
        setDiscovery(payload);
        setPersonas(normalized);
        setLoadError("");
        if (!normalized.some((pal) => pal.persona_id === selectedId)) {
          setSelectedId(normalized[0].persona_id);
        }
      })
      .catch(() => {
        if (!active) return;
        setDiscovery(null);
        setPersonas(null);
        setLoadError("Pal availability could not be checked. Coach remains active.");
        onSessionChange?.(null);
      });
    return () => {
      active = false;
    };
  }, [onSessionChange, selectedId]);

  const selected = useMemo(
    () => (personas || PAL_VISUALS).find((pal) => pal.persona_id === selectedId) || PAL_VISUALS[0],
    [personas, selectedId]
  );
  const activePal =
    session?.mode === "pal" &&
    session.active_persona_id &&
    PAL_BY_ID[session.active_persona_id]
      ? PAL_BY_ID[session.active_persona_id]
      : null;

  async function activateSelected() {
    if (!selected?.runtime_available || busy) return;
    setBusy(true);
    setLoadError("");
    try {
      const data = await authenticatedJson("/api/pals/v1/sessions", {
        method: "POST",
        json: { persona_id: selected.persona_id },
      });
      if (
        data?.mode === "pal" &&
        data.active_persona_id === selected.persona_id &&
        data.speaker === selected.display_name &&
        typeof data.session_token === "string" &&
        data.session_token.length >= 32
      ) {
        onSessionChange?.(data);
        onNotice?.(`${selected.display_name} is active for this session.`);
        return;
      }
      onSessionChange?.(null);
      onNotice?.(`${selected.display_name} is not live right now. Coach remains active.`);
    } catch (_error) {
      onSessionChange?.(null);
      setLoadError("That Pal could not be activated. Coach remains active.");
    } finally {
      setBusy(false);
    }
  }

  function useCoach() {
    onSessionChange?.(null);
    onNotice?.("Coach is active.");
  }

  const visiblePersonas = personas || PAL_VISUALS;
  const selectorState = loadError
    ? "unverified"
    : activePal
      ? "active"
      : discovery?.state === "ready"
        ? "ready"
        : "preview";

  return (
    <section
      className={styles.palSelector}
      data-contract="embodied-pal-selection-v1"
      data-pal-state={selectorState}
      aria-labelledby="pal-selector-title"
    >
      <div className={styles.palSelectorHeader}>
        <div>
          <p className={styles.eyebrow}>Choose your presence</p>
          <h2 id="pal-selector-title">Meet your Fitness Pals</h2>
          <p>
            Preview the five approved Pals. A portrait selection is only a preview until
            you explicitly choose an available Pal and the server confirms that exact identity.
          </p>
        </div>
        <span className={styles.palStatePill} role="status" aria-live="polite">
          {activePal ? `${activePal.display_name} active` : availabilityCopy(discovery, selected)}
        </span>
      </div>

      <div className={styles.palRail} role="group" aria-label="Fitness Pal previews">
        {visiblePersonas.map((pal) => {
          const isSelected = pal.persona_id === selectedId;
          const isActive = activePal?.persona_id === pal.persona_id;
          return (
            <button
              key={pal.persona_id}
              className={`${styles.palCard} ${isSelected ? styles.palCardSelected : ""}`}
              type="button"
              aria-pressed={isSelected}
              aria-label={`Preview ${pal.display_name}, ${pal.runtime_available ? "available" : "preview only"}`}
              data-active={isActive ? "true" : "false"}
              onClick={() => setSelectedId(pal.persona_id)}
            >
              <span className={styles.palPortrait}>
                <img src={pal.image} alt="" width="200" height="250" loading="lazy" />
              </span>
              <span className={styles.palCardMeta}>
                <small>{pal.candidate_id}</small>
                <strong>{pal.display_name}</strong>
                <span className={styles.palAvailability}>
                  {isActive ? "Active" : pal.runtime_available ? "Available" : "Preview only"}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <div className={styles.palStage} data-framing={selected.framing}>
        <div className={styles.palPreviewWrap}>
          <img
            className={styles.palPreviewImage}
            src={selected.image}
            alt={selected.alt}
            width="200"
            height="250"
          />
        </div>
        <div className={styles.palStageCopy}>
          <p className={styles.eyebrow}>{selected.candidate_id} · approved Pal</p>
          <h3>{selected.display_name}</h3>
          <p>
            {selected.runtime_available
              ? "Available to join after you choose this Pal."
              : "You can preview this Pal now. The live Pal runtime is not available, so Coach remains your active conversation."}
          </p>
          {loadError && <p className={styles.palWarning} role="status">{loadError}</p>}
          <div className={styles.palActionRow}>
            <button
              className={styles.primaryButton}
              type="button"
              onClick={activateSelected}
              disabled={!selected.runtime_available || busy}
            >
              {busy
                ? "Connecting…"
                : selected.runtime_available
                  ? `Choose ${selected.display_name}`
                  : "Unavailable right now"}
            </button>
            <button className={styles.secondaryButton} type="button" onClick={useCoach}>
              Use Coach
            </button>
          </div>
          <small className={styles.palBoundaryNote}>
            Selecting a portrait never starts audio or a microphone. A Pal is active only after
            the authenticated Fitness-Pals adapter confirms it.
          </small>
        </div>
      </div>
    </section>
  );
}

export { PAL_VISUALS, normalizeDiscovery };
