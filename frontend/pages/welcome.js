import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/router";

import { authenticatedFetch } from "../lib/authFetch.mjs";
import styles from "../styles/AthletePages.module.css";

const GOAL_OPTIONS = [
  ["race", "Race preparation"],
  ["consistency", "Consistency"],
  ["aerobic_fitness", "Aerobic fitness"],
  ["recovery", "Recovery"],
  ["healthy_activity", "Healthy activity"],
  ["other", "Another goal"],
  ["not_sure", "I’m not sure"],
];

const EMPTY_INTENT = {
  goal: "not_sure",
  phase: "maintenance",
  target_date: "",
  target_distance: "",
  target_performance: "",
  custom_goal: "",
};

function intentFromStatus(intent) {
  if (!intent) return EMPTY_INTENT;
  return {
    goal: intent.goal_type || "not_sure",
    phase: intent.phase || "maintenance",
    target_date: intent.target_date || "",
    target_distance: intent.target_distance || "",
    target_performance: intent.target_performance || "",
    custom_goal: intent.custom_goal || "",
  };
}

function GoalHandshake({ draft, onChange, onSave, saving }) {
  return (
    <section className={styles.wideCard} aria-labelledby="activation-intent-heading">
      <p className={styles.eyebrow}>Your direction</p>
      <h2 id="activation-intent-heading">What would make Fitness Pals useful right now?</h2>
      <p>
        Pick one direction. Details are optional and can be changed later, so this should take
        seconds rather than feel like a questionnaire.
      </p>
      <div className={styles.sectionGrid} role="group" aria-label="Training goal">
        {GOAL_OPTIONS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            className={draft.goal === value ? styles.primaryButton : styles.secondaryButton}
            aria-pressed={draft.goal === value}
            onClick={() => onChange({ ...draft, goal: value })}
          >
            {label}
          </button>
        ))}
      </div>

      <details className={styles.details}>
        <summary>Add optional details</summary>
        <div className={styles.form}>
          <label>
            Current training phase
            <select
              value={draft.phase}
              onChange={(event) => onChange({ ...draft, phase: event.target.value })}
            >
              <option value="build">Training / build</option>
              <option value="maintenance">Maintenance</option>
              <option value="recovery">Post-race / recovery</option>
            </select>
          </label>
          <label>
            Target date
            <input
              type="date"
              value={draft.target_date}
              onChange={(event) => onChange({ ...draft, target_date: event.target.value })}
            />
          </label>
          <label>
            Target distance
            <input
              value={draft.target_distance}
              placeholder="For example: 10K, marathon, 50 miles"
              onChange={(event) => onChange({ ...draft, target_distance: event.target.value })}
            />
          </label>
          <label>
            Target performance
            <input
              value={draft.target_performance}
              placeholder="For example: 3:15, finish comfortably, run the whole way"
              onChange={(event) => onChange({ ...draft, target_performance: event.target.value })}
            />
          </label>
          {draft.goal === "other" && (
            <label>
              Another goal
              <textarea
                value={draft.custom_goal}
                placeholder="Tell Coach what you want to work toward."
                onChange={(event) => onChange({ ...draft, custom_goal: event.target.value })}
              />
            </label>
          )}
        </div>
      </details>

      <div className={styles.buttonRow}>
        <button className={styles.primaryButton} type="button" onClick={onSave} disabled={saving}>
          {saving ? "Saving…" : "Save and continue"}
        </button>
      </div>
    </section>
  );
}

function FirstValue({ status }) {
  const activation = status?.activation;
  const activities = status?.latest_activities || [];
  const preview = status?.training_volume_preview;
  const insight = status?.coach_insight;
  const next = status?.next_action;

  return (
    <div className={styles.sectionGrid}>
      <section className={styles.wideCard}>
        <p className={styles.eyebrow}>First useful signal</p>
        <h2>{insight?.title || "Your training picture is starting to take shape"}</h2>
        <p>
          {insight?.explanation ||
            "Fitness Pals has usable activity history now. More history can improve the picture without blocking you here."}
        </p>
        {preview && <p className={styles.featureValue}>{preview.summary}</p>}
        {activation?.state === "usable_partial" && (
          <p role="status">
            More history is still importing. This view uses only the training data already available.
          </p>
        )}
        <div className={styles.buttonRow}>
          <a className={styles.primaryButton} href={activation?.coach_handoff?.href || "/coach?from=%2Fwelcome"}>
            Continue with Coach
          </a>
          <a className={styles.secondaryButton} href="/today">Open Today</a>
        </div>
      </section>

      <section className={styles.card}>
        <h2>Recent training</h2>
        {activities.length ? (
          <ul className={styles.evidenceList}>
            {activities.map((activity) => (
              <li key={activity.id}>
                {(activity.sport || "Activity").replaceAll("_", " ")} ·{" "}
                {new Date(activity.start_time).toLocaleDateString()}
              </li>
            ))}
          </ul>
        ) : (
          <p>Recent activities will appear as usable history arrives.</p>
        )}
      </section>

      <section className={styles.card}>
        <h2>Next action</h2>
        <p>{next?.description || "Ask Coach what the available evidence can support right now."}</p>
        <a className={styles.textLink} href={next?.href || activation?.coach_handoff?.href || "/coach"}>
          {next?.label || "Ask Coach"}
        </a>
      </section>
    </div>
  );
}

export default function Welcome() {
  const router = useRouter();
  const [viewState, setViewState] = useState("loading");
  const [statusPayload, setStatusPayload] = useState(null);
  const [draft, setDraft] = useState(EMPTY_INTENT);
  const [saving, setSaving] = useState(false);
  const [working, setWorking] = useState(false);
  const [notice, setNotice] = useState("");

  const activation = statusPayload?.activation;
  const editingIntent = router.isReady && router.query.edit === "intent";
  const showingFirstValue = router.isReady && router.query.first === "1";

  const loadStatus = useCallback(async () => {
    try {
      const sessionResponse = await authenticatedFetch("/api/auth/session", {
        credentials: "include",
      });
      if (!sessionResponse.ok) {
        setViewState("unauthenticated");
        return;
      }

      const response = await authenticatedFetch("/api/onboarding/status", {
        credentials: "include",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error("Activation status is unavailable.");

      setStatusPayload(payload);
      setDraft(intentFromStatus(payload.intent));
      const activation = payload.activation;
      if (
        activation?.requires_activation === false &&
        router.query.edit !== "intent" &&
        router.query.first !== "1"
      ) {
        router.replace(activation.resume_href || "/today");
        return;
      }
      setViewState("ready");
    } catch (_error) {
      setViewState("error");
    }
  }, [router]);

  useEffect(() => {
    if (!router.isReady) return undefined;
    loadStatus();
    return undefined;
  }, [router.isReady, loadStatus]);

  useEffect(() => {
    if (!["importing", "usable_partial"].includes(activation?.state)) return undefined;
    const timer = window.setInterval(loadStatus, 4000);
    return () => window.clearInterval(timer);
  }, [activation?.state, loadStatus]);

  async function saveIntent() {
    setSaving(true);
    setNotice("");
    try {
      const response = await authenticatedFetch("/api/onboarding/goal", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          goal: draft.goal,
          phase: draft.phase,
          target_date: draft.target_date || null,
          target_distance: draft.target_distance || null,
          target_performance: draft.target_performance || null,
          custom_goal: draft.custom_goal || null,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Training intent could not be saved.");
      setNotice("Saved. Coach and Today can use this direction now.");
      await loadStatus();
    } catch (error) {
      setNotice(error.message || "Training intent could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function queueFirstSync() {
    setWorking(true);
    setNotice("Import starting. You can keep using Fitness Pals while it runs.");
    try {
      const response = await authenticatedFetch("/api/onboarding/first-sync", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: draft.goal }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Training import could not start.");
      await loadStatus();
    } catch (error) {
      setNotice(error.message || "Training import could not start.");
    } finally {
      setWorking(false);
    }
  }

  const sourceAction = useMemo(() => activation?.action || null, [activation]);

  if (viewState === "unauthenticated") {
    return (
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "3rem 1.25rem" }}>
        <header className={styles.pageHeader}>
          <p className={styles.eyebrow}>Fitness Pals</p>
          <h1>Start with your training, not setup.</h1>
          <p className={styles.lede}>Sign in and Fitness Pals will continue from what it already knows.</p>
        </header>
        <section className={styles.card}>
          <a className={styles.primaryButton} href="/auth/login?next=/welcome">Continue with Gmail</a>
        </section>
      </main>
    );
  }

  if (viewState === "loading") {
    return (
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "3rem 1.25rem" }}>
        <div className={styles.statePanel} role="status" aria-live="polite">
          <strong>Finding the useful starting point…</strong>
          <p>Checking the training and intent already saved to your account.</p>
        </div>
      </main>
    );
  }

  if (viewState === "error") {
    return (
      <main style={{ maxWidth: 900, margin: "0 auto", padding: "3rem 1.25rem" }}>
        <div className={styles.statePanel} role="alert">
          <strong>Fitness Pals could not load your activation state.</strong>
          <p>Your saved data has not been changed.</p>
          <button className={styles.secondaryButton} type="button" onClick={loadStatus}>Try again</button>
        </div>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "3rem 1.25rem 4rem" }}>
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>{editingIntent ? "Training intent" : "Activation"}</p>
        <h1>{editingIntent ? "Refine what you are training for." : "Get to useful coaching quickly."}</h1>
        <p className={styles.lede}>
          {activation?.message ||
            "Tell Fitness Pals what matters, add training history when needed, and start using what is already known."}
        </p>
      </header>

      {notice && <div className={styles.statePanel} role="status" aria-live="polite"><p>{notice}</p></div>}

      <GoalHandshake draft={draft} onChange={setDraft} onSave={saveIntent} saving={saving} />

      {editingIntent && (
        <div className={styles.buttonRow} style={{ marginTop: "1rem" }}>
          <a className={styles.secondaryButton} href="/today">Back to Today</a>
        </div>
      )}

      {!editingIntent && activation?.usable_now && (showingFirstValue || activation?.state === "usable_partial") && (
        <FirstValue status={statusPayload} />
      )}

      {!editingIntent && !activation?.usable_now && (
        <div className={styles.sectionGrid}>
          <section className={styles.wideCard} aria-live="polite">
            <p className={styles.eyebrow}>Training history</p>
            <h2>
              {activation?.state === "importing"
                ? "Your training is loading"
                : "Add enough training history for personalized guidance"}
            </h2>
            <p>{activation?.message}</p>

            {sourceAction?.kind === "sync" ? (
              <button
                className={styles.primaryButton}
                type="button"
                onClick={queueFirstSync}
                disabled={working || sourceAction.enabled === false}
              >
                {working ? "Starting…" : sourceAction.label}
              </button>
            ) : sourceAction?.enabled !== false && sourceAction?.href ? (
              <a className={styles.primaryButton} href={sourceAction.href}>
                {sourceAction.label}
              </a>
            ) : (
              <p role="status">Import in progress. No action is required.</p>
            )}

            <div className={styles.buttonRow} style={{ marginTop: "1rem" }}>
              <a
                className={styles.textLink}
                href={activation?.coach_handoff?.href || "/coach?from=%2Fwelcome"}
              >
                Continue with Coach
              </a>
              <a className={styles.textLink} href="/training">Explore Training</a>
            </div>
            {activation?.state === "importing" && (
              <p>
                You do not need to wait here while the import finishes. Coach can use your saved
                intent now and will be explicit about the training evidence that has not arrived yet.
              </p>
            )}
          </section>
        </div>
      )}

      {!editingIntent && activation?.usable_now && !showingFirstValue && activation?.state !== "usable_partial" && (
        <FirstValue status={statusPayload} />
      )}
    </main>
  );
}
