import styles from "../styles/AthletePages.module.css";

function stateLabel(value) {
  return typeof value === "string" && value ? value.replaceAll("_", " ") : "unknown";
}

function firstSummary(items) {
  if (!Array.isArray(items)) return null;
  const item = items.find((candidate) => candidate && typeof candidate.summary === "string");
  return item?.summary || null;
}

function firstConflict(items) {
  if (!Array.isArray(items)) return null;
  const item = items.find((candidate) => candidate && typeof candidate.resolution === "string");
  return item?.resolution || null;
}

export default function AthleteOrbitStory({ decision, surface = "Athlete" }) {
  const isCanonical = decision?.version === "athlete_orbit_v1";
  const goal = isCanonical ? decision?.evidence?.goal || {} : {};
  const primary = goal?.primary_event || null;
  const action = isCanonical ? decision?.action || {} : {};
  const freshness = isCanonical ? decision?.freshness || {} : {};
  const rationale = isCanonical ? firstSummary(decision?.rationale) : null;
  const uncertainty = isCanonical
    ? firstSummary(decision?.uncertainty) || firstConflict(decision?.conflicts)
    : null;
  const provenance = isCanonical ? decision?.provenance || {} : {};

  return (
    <section
      className={styles.orbitStory}
      data-contract="athlete-orbit-story-v1"
      aria-label={`${surface} Athlete Orbit story`}
    >
      <div className={styles.orbitStoryHeader}>
        <div>
          <p className={styles.eyebrow}>Athlete Orbit</p>
          <h2>One athlete story</h2>
        </div>
        <span className={styles.statusBadge}>
          {isCanonical ? stateLabel(decision.state) : "loading"}
        </span>
      </div>

      {!isCanonical ? (
        <p className={styles.orbitStoryLoading}>
          Loading the canonical goal, next action, and evidence freshness…
        </p>
      ) : (
        <>
          <div className={styles.orbitStoryGrid}>
            <article>
              <span>Goal context</span>
              <strong>{primary?.label || goal?.goal_type || "Goal unavailable"}</strong>
              <small>
                {goal?.phase ? `Phase: ${stateLabel(goal.phase)}` : "Phase unavailable"}
                {Number.isInteger(primary?.days_to_event)
                  ? ` · ${primary.days_to_event} days to primary event`
                  : ""}
              </small>
            </article>
            <article>
              <span>Next action</span>
              <strong>{action?.label || "Action unavailable"}</strong>
              <small>
                {action?.priority ? `Priority: ${stateLabel(action.priority)}` : "Priority unknown"}
              </small>
            </article>
            <article>
              <span>Evidence freshness</span>
              <strong>
                Training {stateLabel(freshness?.training)} · Recovery {stateLabel(freshness?.recovery)}
              </strong>
              <small>Combined state: {stateLabel(freshness?.state)}</small>
            </article>
          </div>

          <div className={styles.orbitStoryEvidence}>
            <p><strong>Why:</strong>{" "}{rationale || "Canonical evidence is available, but no rationale was emitted."}</p>
            {uncertainty && <p><strong>Uncertainty or conflict:</strong> {uncertainty}</p>}
            <p>
              <strong>Trace:</strong> canonical Goal Graph + recovery + whole-training evidence.{" "}
              {provenance?.caveat || "Unknown evidence remains unknown."}
            </p>
          </div>

          <div className={styles.buttonRow}>
            {action?.href && <a className={styles.primaryButton} href={action.href}>{action.label}</a>}
            <a className={styles.textLink} href="/progress">Inspect canonical evidence</a>
          </div>
        </>
      )}
    </section>
  );
}
