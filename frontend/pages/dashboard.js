import { useEffect, useState } from "react";
import axios from "axios";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import styles from "../styles/AthletePages.module.css";

function readableLabel(label) {
  return label.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function readableValue(value) {
  if (value === null || value === undefined || value === "") return "Not available";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number" || typeof value === "string") return String(value);
  if (Array.isArray(value)) return `${value.length} item${value.length === 1 ? "" : "s"}`;
  return "Available";
}

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [authState, setAuthState] = useState("loading");
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState("");
  const [sending, setSending] = useState(false);

  useEffect(() => {
    axios
      .post("/api/metrics/summary", {})
      .then((res) => {
        setMetrics(res.data);
        setAuthState("authenticated");
      })
      .catch(() => {
        setMetrics(null);
        setAuthState("unauthenticated");
      });
  }, []);

  const sendChat = async () => {
    if (!message.trim() || sending) return;
    setSending(true);
    try {
      const res = await axios.post("/api/chat", { message: message.trim() });
      setChat(res.data.response);
      setMessage("");
    } catch (err) {
      setChat("Please sign in again before asking your coach.");
      setAuthState("unauthenticated");
    } finally {
      setSending(false);
    }
  };

  const metricEntries = metrics && typeof metrics === "object"
    ? Object.entries(metrics).slice(0, 8)
    : [];

  return (
    <AuthenticatedShell active="home">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your training</p>
        <h1>Welcome back</h1>
        <p className={styles.lede}>
          Review what your recent training says, find your activity history, and ask for
          coaching that reflects your own journey.
        </p>
      </header>

      {authState === "loading" && (
        <StatusNotice>Loading your latest fitness picture…</StatusNotice>
      )}
      {authState === "unauthenticated" && (
        <StatusNotice tone="warning">
          Your session has ended. <a href="/auth/login?next=%2Fdashboard">Sign in to continue</a>.
        </StatusNotice>
      )}

      <div className={styles.sectionGrid}>
        <section className={styles.wideCard} id="journey">
          <h2>Your journey</h2>
          <p>A quick, readable view of the signals currently available for your training.</p>
          {authState === "authenticated" && metricEntries.length === 0 && (
            <StatusNotice tone="warning">
              No fitness summary is available yet. Connect your source and complete a first sync.
            </StatusNotice>
          )}
          {metricEntries.length > 0 && (
            <div className={styles.metricGrid}>
              {metricEntries.map(([label, value]) => (
                <div className={styles.metric} key={label}>
                  <span>{readableLabel(label)}</span>
                  <strong>{readableValue(value)}</strong>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className={styles.card} id="activities">
          <h2>Activities</h2>
          <p>
            Your connected activity history feeds the fitness picture above. A focused activity
            explorer will add trends and workout details here next.
          </p>
          <a className={styles.textLink} href="/welcome">Review data connection</a>
        </section>

        <section className={styles.card} id="dossiers">
          <h2>Coaching dossiers</h2>
          <p>
            Dossiers turn your accumulated training into a durable coaching narrative. Your
            personal library is the next step in this experience.
          </p>
          <a
            className={styles.textLink}
            href="https://fitness-pals.com/reports/urban-feet-coach-dossier-third-edition-2026-04-05.html"
          >
            View a sample dossier
          </a>
        </section>

        <section className={styles.wideCard} id="coach">
          <h2>Ask your coach</h2>
          <p>Ask a question about the fitness information currently connected to your account.</p>
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
            {chat && <StatusNotice tone={authState === "unauthenticated" ? "warning" : "success"}>{chat}</StatusNotice>}
          </div>
        </section>
      </div>
    </AuthenticatedShell>
  );
}
