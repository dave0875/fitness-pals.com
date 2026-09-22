import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/router";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import { authenticatedJson } from "../lib/authFetch.mjs";
import styles from "../styles/AthletePages.module.css";

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatDistance(meters) {
  if (meters === null || meters === undefined) return "Distance unknown";
  return `${(meters / 1609.344).toFixed(1)} mi`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "Duration unknown";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function Signal({ label, value, detail }) {
  return (
    <div className={styles.signalCard}>
      <span>{label}</span>
      <strong>{value ?? "Unknown"}</strong>
      {detail && <p>{detail}</p>}
    </div>
  );
}

export default function Dashboard() {
  const router = useRouter();
  const [home, setHome] = useState(null);
  const [todayPlan, setTodayPlan] = useState(null);
  const [viewState, setViewState] = useState("loading");
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState("");
  const [sending, setSending] = useState(false);
  const [planBusy, setPlanBusy] = useState(false);
  const [planNotice, setPlanNotice] = useState("");
  const [editingPlan, setEditingPlan] = useState(false);
  const [goalDraft, setGoalDraft] = useState({
    goal_type: "consistency",
    phase: "maintenance",
    target_date: "",
  });
  const [adjustment, setAdjustment] = useState(null);
  const [feedback, setFeedback] = useState({ perceived_effort: "as_expected", note: "" });

  const loadHome = useCallback(() => {
    setViewState("loading");
    Promise.all([
      authenticatedJson("/api/athlete-home"),
      authenticatedJson("/api/today-plan"),
    ]).then(([homeData, planData]) => {
        setHome(homeData);
        setTodayPlan(planData);
        if (planData.goal) {
          setGoalDraft({
            goal_type: planData.goal.type,
            phase: planData.goal.phase,
            target_date: planData.goal.target_date || "",
          });
        }
        setViewState("ready");
      })
      .catch((error) => {
        setHome(null);
        setViewState(error.status === 401 ? "unauthenticated" : "error");
      });
  }, []);

  useEffect(() => {
    loadHome();
  }, [loadHome]);

  useEffect(() => {
    if (router.isReady && typeof router.query.prompt === "string") {
      setMessage(router.query.prompt);
    }
  }, [router.isReady, router.query.prompt]);

  const sendChat = async () => {
    if (!message.trim() || sending) return;
    setSending(true);
    try {
      const data = await authenticatedJson("/api/chat", {
        method: "POST",
        json: { message: message.trim() },
      });
      setChat(data.response);
      setMessage("");
    } catch (error) {
      if (error.status === 401) {
        setViewState("unauthenticated");
        setChat("Please sign in again before asking your coach.");
      } else {
        setChat("Your coach could not answer just now. Your fitness home is still available.");
      }
    } finally {
      setSending(false);
    }
  };

  const saveGoal = async () => {
    setPlanBusy(true);
    setPlanNotice("");
    try {
      const data = await authenticatedJson("/api/today-plan/goal", {
        method: "PUT",
        json: { ...goalDraft, target_date: goalDraft.target_date || null },
      });
      setTodayPlan(data);
      setEditingPlan(false);
      setPlanNotice("Goal saved. Your next decision is ready.");
    } catch (_error) {
      setPlanNotice("Your goal could not be saved just now.");
    } finally {
      setPlanBusy(false);
    }
  };

  const updatePlan = async (request) => {
    if (!todayPlan?.plan) return;
    setPlanBusy(true);
    setPlanNotice("");
    try {
      const data = await authenticatedJson(`/api/today-plan/${todayPlan.plan.id}`, {
        method: "PATCH",
        json: request,
      });
      setTodayPlan(data);
      setEditingPlan(false);
      setPlanNotice(`Plan ${data.state}.`);
    } catch (_error) {
      setPlanNotice("That plan update could not be saved just now.");
    } finally {
      setPlanBusy(false);
    }
  };

  const acceptPlan = () => updatePlan({ action: "accept", payload: {} });
  const skipPlan = () => updatePlan({ action: "skip", payload: { note: "Skipped by athlete" } });
  const adjustPlan = () => updatePlan({
    action: "adjust",
    payload: {
      scheduled_for: adjustment.scheduled_for,
      duration_minutes: adjustment.duration_min && adjustment.duration_max ? {
        min: Number(adjustment.duration_min),
        max: Number(adjustment.duration_max),
      } : null,
      distance_miles: adjustment.distance_min && adjustment.distance_max ? {
        min: Number(adjustment.distance_min),
        max: Number(adjustment.distance_max),
      } : null,
      effort_range: adjustment.effort_range,
    },
  });
  const completePlan = () => updatePlan({ action: "complete", payload: feedback });

  const startAdjustment = () => {
    const plan = todayPlan.plan;
    setAdjustment({
      scheduled_for: plan.scheduled_for,
      duration_min: plan.duration_minutes?.min ?? "",
      duration_max: plan.duration_minutes?.max ?? "",
      distance_min: plan.distance_miles?.min ?? "",
      distance_max: plan.distance_miles?.max ?? "",
      effort_range: plan.effort_range,
    });
    setEditingPlan(true);
  };

  const requestNextPlan = async () => {
    setPlanBusy(true);
    setPlanNotice("");
    try {
      const data = await authenticatedJson("/api/today-plan/next", { method: "POST" });
      setTodayPlan(data);
      setPlanNotice("Your next decision is ready.");
    } catch (_error) {
      setPlanNotice("The next decision could not be created just now.");
    } finally {
      setPlanBusy(false);
    }
  };

  const recovery = home?.recovery;
  const readiness = home?.readiness;
  const displayedGoal = todayPlan?.goal || home?.goal;
  return (
    <AuthenticatedShell active="today">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your training</p>
        <h1>Your athlete home</h1>
        <p className={styles.lede}>
          See what changed, understand where you are now, and leave with one useful next step.
        </p>
        {displayedGoal && (
          <p className={styles.goalPill}>
            Current focus: {displayedGoal.label}
            {displayedGoal.phase_label ? ` · ${displayedGoal.phase_label}` : ""}
            {displayedGoal.target_date ? ` · ${formatDate(displayedGoal.target_date)}` : ""}
          </p>
        )}
      </header>

      {viewState === "loading" && (
        <div className={styles.statePanel} role="status">
          <strong>Loading your athlete home</strong>
          <p>Bringing your recent training and recovery into focus…</p>
        </div>
      )}

      {viewState === "unauthenticated" && (
        <StatusNotice tone="warning">
          Your session has ended.{" "}
          <a href="/auth/login?next=%2Ftoday">Sign in to continue</a>.
        </StatusNotice>
      )}

      {viewState === "error" && (
        <div className={styles.statePanel} role="alert">
          <strong>We could not load your athlete home</strong>
          <p>Your saved fitness data has not been changed.</p>
          <button className={styles.secondaryButton} type="button" onClick={loadHome}>
            Try again
          </button>
        </div>
      )}

      {viewState === "ready" && home && (
        <>
          <div className={styles.freshnessRow}>
            {home.freshness.state === "partial" && (
              <StatusNotice tone="warning">Some signals are missing or stale</StatusNotice>
            )}
            {home.freshness.state === "stale" && (
              <StatusNotice tone="warning">Your data needs a refresh</StatusNotice>
            )}
            {home.data_through && (
              <p className={styles.dataThrough}>Data through {formatDate(home.data_through)}</p>
            )}
          </div>

          {home.state === "empty" && (
            <div className={styles.statePanel}>
              <strong>No training history yet</strong>
              <p>Connect your fitness source and complete the guided first sync.</p>
              <a className={styles.primaryButton} href="/welcome">Start guided setup</a>
            </div>
          )}

          <div className={styles.sectionGrid}>
            <section className={styles.wideCard} id="journey">
              <p className={styles.questionLabel}>What happened</p>
              <h2>{home.trend.label}</h2>
              <p className={styles.featureValue}>
                {home.trend.state === "unknown"
                  ? "Training trend unknown"
                  : `${home.trend.current_miles.toFixed(1)} miles this week`}
              </p>
              <p>{home.trend.explanation}</p>
            </section>

            <section className={styles.card}>
              <p className={styles.questionLabel}>Where you are now</p>
              <h2>{readiness.label}</h2>
              <p className={styles.featureValue}>
                {readiness.score === null ? "Unknown" : `${readiness.score}/100`}
              </p>
              <p>{readiness.explanation}</p>
              <p>Training consistency: {home.training_consistency.score === null ? "Unknown" : `${home.training_consistency.score}/100`}. {home.training_consistency.explanation}</p>
              <p>Workout data: {home.freshness.signals.activities.state}. Sleep data: {home.freshness.signals.sleep.state}. Intensity: {home.freshness.signals.intensity.state}.</p>
              <div className={styles.signalGrid}>
                <Signal
                  label="Sleep"
                  value={recovery.sleep_hours === null ? "Unknown" : `${recovery.sleep_hours} hours`}
                />
                <Signal label="Sleep score" value={recovery.sleep_score} />
                <Signal label="Overnight HRV" value={recovery.overnight_hrv} />
              </div>
            </section>

            <section className={styles.card}>
              <p className={styles.questionLabel}>What to do next</p>
              <h2>{home.coaching.insight}</h2>
              <p>{home.coaching.explanation}</p>
              <a className={styles.primaryButton} href={home.coaching.next_action.href}>
                {home.coaching.next_action.label}
              </a>
            </section>

            <section className={styles.wideCard} id="todays-run">
              <p className={styles.questionLabel}>One decision at a time</p>
              <h2>Today&apos;s run</h2>
              <p>
                A coaching suggestion grounded in your account&apos;s valid run history. It is not a medical readiness score.
              </p>

              {todayPlan?.state === "goal_required" && (
                <div className={styles.statePanel}>
                  <strong>Choose the goal this session should serve</strong>
                  <p>No goal is assumed from a past race or activity title.</p>
                </div>
              )}

              {(todayPlan?.state === "goal_required" || todayPlan?.goal) && (
                <details className={styles.details} open={todayPlan?.state === "goal_required"}>
                  <summary>{todayPlan?.goal ? "Change goal or phase" : "Set goal and phase"}</summary>
                  <div className={styles.form}>
                    <label>
                      Goal
                      <select
                        value={goalDraft.goal_type}
                        onChange={(event) => setGoalDraft({ ...goalDraft, goal_type: event.target.value })}
                      >
                        <option value="consistency">Consistency</option>
                        <option value="marathon">Marathon</option>
                        <option value="half">Half marathon</option>
                        <option value="recovery">Recovery</option>
                      </select>
                    </label>
                    <label>
                      Phase
                      <select
                        value={goalDraft.phase}
                        onChange={(event) => setGoalDraft({ ...goalDraft, phase: event.target.value })}
                      >
                        <option value="build">Training / build</option>
                        <option value="maintenance">Maintenance</option>
                        <option value="recovery">Post-race / recovery</option>
                      </select>
                    </label>
                    <label>
                      Race or target date (optional)
                      <input
                        type="date"
                        value={goalDraft.target_date}
                        onChange={(event) => setGoalDraft({ ...goalDraft, target_date: event.target.value })}
                      />
                    </label>
                    <button className={styles.primaryButton} type="button" onClick={saveGoal} disabled={planBusy}>
                      {planBusy ? "Saving…" : "Save goal and show my run"}
                    </button>
                  </div>
                </details>
              )}

              {todayPlan?.state === "history_required" && (
                <StatusNotice tone="warning">
                  A valid run with a known duration or distance is needed before suggesting a range.
                </StatusNotice>
              )}

              {todayPlan?.plan && (
                <div className={styles.planLayout}>
                  <div className={styles.planSummary}>
                    <span className={styles.statusBadge}>{todayPlan.plan.status.replaceAll("_", " ")}</span>
                    <h3>{todayPlan.plan.session_purpose}</h3>
                    <dl className={styles.planFacts}>
                      <div>
                        <dt>Session purpose</dt>
                        <dd>{todayPlan.plan.session_purpose}</dd>
                      </div>
                      <div>
                        <dt>When</dt>
                        <dd>{formatDate(todayPlan.plan.scheduled_for)}</dd>
                      </div>
                      <div>
                        <dt>Time or distance</dt>
                        <dd>
                          {todayPlan.plan.duration_minutes
                            ? `${todayPlan.plan.duration_minutes.min}–${todayPlan.plan.duration_minutes.max} min`
                            : "Time unknown"}
                          {todayPlan.plan.distance_miles
                            ? ` or ${todayPlan.plan.distance_miles.min}–${todayPlan.plan.distance_miles.max} mi`
                            : ""}
                        </dd>
                      </div>
                      <div>
                        <dt>Effort</dt>
                        <dd>{todayPlan.plan.effort_range}</dd>
                      </div>
                    </dl>
                  </div>

                  <div>
                    <h3>Why this session</h3>
                    <ul className={styles.evidenceList}>
                      {todayPlan.plan.evidence.map((item) => <li key={item.activity_id}>{item.summary}</li>)}
                      {todayPlan.plan.rationale.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                    <h3>What is uncertain</h3>
                    <ul className={styles.evidenceList}>
                      {todayPlan.plan.uncertainty.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>

                  {editingPlan && adjustment && (
                    <div className={styles.form}>
                      <label>When<input type="date" value={adjustment.scheduled_for} onChange={(event) => setAdjustment({ ...adjustment, scheduled_for: event.target.value })} /></label>
                      <div className={styles.rangeRow}>
                        <label>Minimum minutes<input type="number" min="5" value={adjustment.duration_min} onChange={(event) => setAdjustment({ ...adjustment, duration_min: event.target.value })} /></label>
                        <label>Maximum minutes<input type="number" min="5" value={adjustment.duration_max} onChange={(event) => setAdjustment({ ...adjustment, duration_max: event.target.value })} /></label>
                      </div>
                      <div className={styles.rangeRow}>
                        <label>Minimum miles<input type="number" min="0.5" step="0.5" value={adjustment.distance_min} onChange={(event) => setAdjustment({ ...adjustment, distance_min: event.target.value })} /></label>
                        <label>Maximum miles<input type="number" min="0.5" step="0.5" value={adjustment.distance_max} onChange={(event) => setAdjustment({ ...adjustment, distance_max: event.target.value })} /></label>
                      </div>
                      <label>Effort guidance<input value={adjustment.effort_range} onChange={(event) => setAdjustment({ ...adjustment, effort_range: event.target.value })} /></label>
                      <div className={styles.buttonRow}>
                        <button className={styles.primaryButton} type="button" onClick={adjustPlan} disabled={planBusy}>Save adjustment</button>
                        <button className={styles.secondaryButton} type="button" onClick={() => setEditingPlan(false)}>Cancel</button>
                      </div>
                    </div>
                  )}

                  {todayPlan.plan.status === "accepted" && (
                    <div className={styles.form}>
                      <h3>Report completion</h3>
                      <label>
                        How did the effort feel?
                        <select value={feedback.perceived_effort} onChange={(event) => setFeedback({ ...feedback, perceived_effort: event.target.value })}>
                          <option value="easier">Easier than expected</option>
                          <option value="as_expected">As expected</option>
                          <option value="harder">Harder than expected</option>
                        </select>
                      </label>
                      <label>Optional note<textarea value={feedback.note} onChange={(event) => setFeedback({ ...feedback, note: event.target.value })} /></label>
                      <button className={styles.primaryButton} type="button" onClick={completePlan} disabled={planBusy}>Mark complete</button>
                    </div>
                  )}

                  {todayPlan.next_decision_available ? (
                    <button className={styles.primaryButton} type="button" onClick={requestNextPlan} disabled={planBusy}>
                      Plan the next session
                    </button>
                  ) : !editingPlan && (
                    <div className={styles.buttonRow}>
                      {todayPlan.plan.status !== "accepted" && (
                        <button className={styles.primaryButton} type="button" onClick={acceptPlan} disabled={planBusy}>Accept</button>
                      )}
                      <button className={styles.secondaryButton} type="button" onClick={startAdjustment} disabled={planBusy}>Adjust</button>
                      <button className={styles.secondaryButton} type="button" onClick={skipPlan} disabled={planBusy}>Skip</button>
                    </div>
                  )}
                </div>
              )}
              {planNotice && <StatusNotice tone="neutral">{planNotice}</StatusNotice>}
            </section>

            <section className={styles.wideCard} id="activities">
              <div className={styles.sectionHeading}>
                <div>
                  <p className={styles.questionLabel}>Your recent record</p>
                  <h2>Latest activities</h2>
                </div>
                <a className={styles.textLink} href="/settings">Review connection</a>
              </div>
              {home.recent_activities.length === 0 ? (
                <p>No activities are available yet.</p>
              ) : (
                <ol className={styles.activityList}>
                  {home.recent_activities.map((activity) => (
                    <li key={activity.id}>
                      <div>
                        <strong>{activity.title}</strong>
                        <span>{formatDate(activity.start_time)}</span>
                      </div>
                      <span>
                        {formatDistance(activity.distance_m)} · {formatDuration(activity.duration_seconds)}
                      </span>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section className={styles.card} id="dossiers">
              <p className={styles.questionLabel}>A durable coaching narrative</p>
              <h2>Coaching dossier library</h2>
              <p>Your private dossier library keeps each generated version available.</p>
              <h3>{home.dossier.title}</h3>
              <p>{home.dossier.summary}</p>
              {home.dossier.state !== "not_generated" && (
                <StatusNotice tone={home.dossier.state === "completed" ? "success" : "neutral"}>
                  {home.dossier.state.replaceAll("_", " ")}
                  {home.dossier.version ? ` · Version ${home.dossier.version}` : ""}
                  {home.dossier.data_through
                    ? ` · Data through ${formatDate(home.dossier.data_through)}`
                    : ""}
                </StatusNotice>
              )}
              <a className={styles.textLink} href={home.dossier.action.href}>
                {home.dossier.action.label}
              </a>
            </section>

            <section className={styles.card} id="coach">
              <p className={styles.questionLabel}>Personal guidance</p>
              <h2>Ask your coach</h2>
              <p>Ask about the fitness information connected to your account.</p>
              <div className={styles.chatForm}>
                <label htmlFor="coach-message">What would you like help with?</label>
                <textarea
                  id="coach-message"
                  value={message}
                  onChange={(event) => setMessage(event.target.value)}
                  placeholder="How should I approach this week’s training?"
                />
                <button
                  className={styles.primaryButton}
                  type="button"
                  onClick={sendChat}
                  disabled={!message.trim() || sending}
                >
                  {sending ? "Asking…" : "Ask coach"}
                </button>
                {chat && (
                  <StatusNotice tone={viewState === "unauthenticated" ? "warning" : "success"}>
                    {chat}
                  </StatusNotice>
                )}
              </div>
            </section>
          </div>
        </>
      )}
    </AuthenticatedShell>
  );
}
