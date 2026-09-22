import { useEffect, useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import { authenticatedFetch } from "../lib/authFetch.mjs";
import { connectionState } from "../lib/coreFlowStates.mjs";
import styles from "../styles/AthletePages.module.css";

export default function Settings() {
  const [status, setStatus] = useState(null);
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState("");

  async function loadStatus() {
    try {
      const response = await authenticatedFetch("/api/onboarding/status");
      if (!response.ok) throw new Error("Connection status is unavailable.");
      setStatus(await response.json());
      setState("ready");
    } catch (error) {
      setState("error");
      setMessage(error.message);
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const connection = connectionState(status);
  const archiveOnly = Boolean(status?.latest_activities?.length) && !status?.garmin_connected;

  async function refresh() {
    setState("working");
    setMessage("Queueing a Garmin refresh…");
    try {
      const response = await authenticatedFetch("/api/onboarding/first-sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: status?.selected_goal || "consistency" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Refresh could not be queued.");
      setStatus((current) => ({
        ...current,
        first_sync: { ...current.first_sync, state: payload.state },
      }));
      setState("ready");
      setMessage("Refresh in progress. You can review existing activities while it finishes.");
    } catch (error) {
      setState("ready");
      setMessage(error.message || "Refresh could not be queued. Try again.");
    }
  }

  return (
    <AuthenticatedShell active="settings">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your account</p>
        <h1>Settings</h1>
        <p className={styles.lede}>Manage your fitness connection, archive history, and session.</p>
      </header>

      {message && <StatusNotice tone={state === "error" ? "warning" : "neutral"}>{message}</StatusNotice>}

      <div className={styles.sectionGrid}>
        <section className={styles.card} aria-busy={state === "loading" || state === "working"}>
          <h2>Fitness connection</h2>
          {state === "loading" && <p>Checking Garmin connection…</p>}
          {state === "error" && (
            <>
              <p>Connection status could not be loaded.</p>
              <button className={styles.secondaryButton} type="button" onClick={loadStatus}>
                Try again
              </button>
            </>
          )}
          {state !== "loading" && state !== "error" && (
            <>
              <p>
                {status?.garmin_connected
                  ? "Connection is active. Refreshes add new canonical activities without duplicating history."
                  : archiveOnly
                    ? "Archive history is available. Connect Garmin to refresh it automatically."
                    : "Garmin is not connected. Connect it to import and refresh activity data."}
              </p>
              {connection.action === "wait" && <p role="status">Refresh in progress.</p>}
              {connection.action === "connect" ? (
                <a className={styles.textLink} href="/api/providers/garmin/login?next=/settings">
                  {connection.label}
                </a>
              ) : connection.action === "wait" ? (
                <a className={styles.textLink} href="/training">Review existing activities</a>
              ) : (
                <button
                  className={styles.primaryButton}
                  type="button"
                  onClick={refresh}
                  disabled={state === "working"}
                >
                  {connection.action === "retry" ? "Retry refresh" : connection.label}
                </button>
              )}
            </>
          )}
        </section>

        <section className={styles.card}>
          <h2>Historical Garmin archive</h2>
          <p>Check available archive sources, import progress, and completed activity history.</p>
          <a className={styles.textLink} href="/import/garmin-archive">Check archive options</a>
        </section>

        <section className={styles.card}>
          <h2>Session</h2>
          <p>Sign out when you are finished, especially on a shared device.</p>
          <a className={styles.textLink} href="/auth/logout">Sign out</a>
        </section>
      </div>
    </AuthenticatedShell>
  );
}
