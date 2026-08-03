import { useCallback, useEffect, useState } from "react";
import axios from "axios";
import { useRouter } from "next/router";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
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
  const [viewState, setViewState] = useState("loading");
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState("");
  const [sending, setSending] = useState(false);

  const loadHome = useCallback(() => {
    setViewState("loading");
    axios.get("/api/athlete-home").then((res) => {
        setHome(res.data);
        setViewState("ready");
      })
      .catch((error) => {
        setHome(null);
        setViewState(error.response?.status === 401 ? "unauthenticated" : "error");
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
      const res = await axios.post("/api/chat", { message: message.trim() });
      setChat(res.data.response);
      setMessage("");
    } catch (error) {
      if (error.response?.status === 401) {
        setViewState("unauthenticated");
        setChat("Please sign in again before asking your coach.");
      } else {
        setChat("Your coach could not answer just now. Your fitness home is still available.");
      }
    } finally {
      setSending(false);
    }
  };

  const recovery = home?.recovery;
  const readiness = home?.readiness;
  return (
    <AuthenticatedShell active="home">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your training</p>
        <h1>Your athlete home</h1>
        <p className={styles.lede}>
          See what changed, understand where you are now, and leave with one useful next step.
        </p>
        {home?.goal && <p className={styles.goalPill}>Current focus: {home.goal.label}</p>}
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
          <a href="/auth/login?next=%2Fdashboard">Sign in to continue</a>.
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
              <StatusNotice tone="warning">Some signals are still unknown</StatusNotice>
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

            <section className={styles.wideCard} id="activities">
              <div className={styles.sectionHeading}>
                <div>
                  <p className={styles.questionLabel}>Your recent record</p>
                  <h2>Latest activities</h2>
                </div>
                <a className={styles.textLink} href="/welcome">Review connection</a>
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
