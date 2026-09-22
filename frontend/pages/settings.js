import { useEffect, useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import { authenticatedFetch } from "../lib/authFetch.mjs";
import { connectionState } from "../lib/coreFlowStates.mjs";
import {
  connectionTrustState,
  freshnessSignals,
  trustTone,
} from "../lib/trustStates.mjs";
import styles from "../styles/AthletePages.module.css";

function formatSignalTime(value) {
  if (!value) return "No current reading";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(parsed);
}

function stateLabel(value) {
  return String(value || "unknown").replaceAll("_", " ");
}

export default function Settings() {
  const [status, setStatus] = useState(null);
  const [home, setHome] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState("");

  async function loadStatus() {
    setState("loading");
    try {
      const [statusResponse, homeResponse, capabilitiesResponse] = await Promise.all([
        authenticatedFetch("/api/onboarding/status"),
        authenticatedFetch("/api/athlete-home"),
        authenticatedFetch("/api/archive-imports/capabilities"),
      ]);
      if (!statusResponse.ok) throw new Error("Connection status is unavailable.");
      if (!homeResponse.ok) throw new Error("Data freshness is unavailable.");

      const nextStatus = await statusResponse.json();
      const nextHome = await homeResponse.json();
      const nextCapabilities = capabilitiesResponse.ok
        ? await capabilitiesResponse.json()
        : null;

      setStatus(nextStatus);
      setHome(nextHome);
      setCapabilities(nextCapabilities);
      setState("ready");
      if (!capabilitiesResponse.ok) {
        setMessage("Archive options could not be checked. Your saved training history is still available.");
      }
    } catch (error) {
      setState("error");
      setMessage(error.message || "Settings could not be loaded.");
    }
  }

  useEffect(() => {
    loadStatus();
  }, []);

  const connection = connectionState(status);
  const trust = connectionTrustState(status, home, capabilities);
  const signals = freshnessSignals(home);
  const latestArchiveJob = capabilities?.latest_job || null;

  async function refresh() {
    setState("working");
    setMessage("Queueing a training-data refresh…");
    try {
      const response = await authenticatedFetch("/api/onboarding/first-sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: status?.selected_goal || "consistency" }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Refresh could not be queued.");
      await loadStatus();
      setState("ready");
      setMessage("Refresh is in progress. Existing training history remains available while it runs.");
    } catch (error) {
      setState("ready");
      setMessage(error.message || "Refresh could not be queued. Try again.");
    }
  }

  function renderConnectionAction() {
    if (connection.action === "wait") {
      return (
        <p role="status">
          An update is already running. You can keep using your saved training while it finishes.
        </p>
      );
    }
    if (connection.href && connection.enabled) {
      return (
        <a className={styles.textLink} href={connection.href}>
          {connection.label}
        </a>
      );
    }
    if (connection.enabled) {
      return (
        <button
          className={styles.primaryButton}
          type="button"
          onClick={refresh}
          disabled={state === "working"}
        >
          {connection.label}
        </button>
      );
    }
    return <p role="status">{connection.label}</p>;
  }

  return (
    <AuthenticatedShell active="settings">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your account</p>
        <h1>Settings</h1>
        <p className={styles.lede}>
          Manage your goal, understand the training data Fitness Pals can trust, and recover cleanly
          when a connection or import needs attention.
        </p>
      </header>

      <nav className={styles.buttonRow} aria-label="Settings sections">
        <a className={styles.textLink} href="#profile">Profile</a>
        <a className={styles.textLink} href="#goals">Goals</a>
        <a className={styles.textLink} href="#connections">Connections</a>
        <a className={styles.textLink} href="#coaching">Coaching</a>
        <a className={styles.textLink} href="#data-privacy">Data &amp; privacy</a>
        <a className={styles.textLink} href="#account">Account</a>
      </nav>

      {message && (
        <StatusNotice tone={state === "error" ? "warning" : "neutral"}>
          {message}
        </StatusNotice>
      )}

      {state === "loading" && (
        <div className={styles.statePanel} role="status">
          <strong>Checking your account and training data</strong>
          <p>Reading your saved goal, connection state, archive options, and canonical freshness.</p>
        </div>
      )}

      {state === "error" && (
        <div className={styles.statePanel}>
          <strong>Settings could not be loaded</strong>
          <p>Your saved training history has not been changed.</p>
          <button className={styles.secondaryButton} type="button" onClick={loadStatus}>
            Try again
          </button>
        </div>
      )}

      {state !== "loading" && state !== "error" && (
        <div className={styles.sectionGrid}>
          <section id="profile" className={styles.card} tabIndex="-1">
            <p className={styles.eyebrow}>Profile</p>
            <h2>Your athlete account</h2>
            <p>
              Your signed-in identity is managed by the authentication provider. Fitness Pals keeps
              connection credentials and operator configuration out of this athlete-facing surface.
            </p>
          </section>

          <section id="goals" className={styles.card} tabIndex="-1">
            <p className={styles.eyebrow}>Goals</p>
            <h2>{status?.intent?.label || "Training intent"}</h2>
            <p>
              {status?.intent?.phase_label
                ? `Current phase: ${status.intent.phase_label}.`
                : "Set the goal and training phase that Today and Coach should work from."}
              {status?.intent?.target_date ? ` Target date: ${status.intent.target_date}.` : ""}
            </p>
            <a className={styles.textLink} href="/welcome?edit=intent">
              Review training intent
            </a>
          </section>

          <section id="connections" className={styles.wideCard} tabIndex="-1" aria-busy={state === "working"}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Connections</p>
                <h2>Training data trust</h2>
              </div>
              <span className={styles.statusBadge}>{trust.label}</span>
            </div>

            <StatusNotice tone={trustTone(trust.state)}>
              <strong>{trust.label}.</strong> {trust.detail}
            </StatusNotice>

            {status?.activation?.message && <p>{status.activation.message}</p>}

            <div className={styles.signalGrid} aria-label="Data freshness by signal">
              {signals.map((signal) => (
                <div className={styles.signalCard} key={signal.key}>
                  <span>{signal.label}</span>
                  <strong>{stateLabel(signal.state)}</strong>
                  <p>{formatSignalTime(signal.dataThrough)}</p>
                </div>
              ))}
            </div>

            {home?.freshness?.state === "partial" && (
              <p role="status">
                Fitness Pals treats this as partial data. A fresh activity does not make stale or
                unknown sleep and intensity signals current.
              </p>
            )}

            {trust.historyAvailable && (
              <p>
                Saved canonical training history remains part of your Fitness Pals account even when
                a source stops updating. A disconnected or expired source stops future updates; it
                does not silently erase activities that were already imported.
              </p>
            )}

            {latestArchiveJob && (
              <p>
                Latest archive job: <strong>{stateLabel(latestArchiveJob.status)}</strong>.
                {latestArchiveJob.status === "completed"
                  ? " The resulting activities are available in Training."
                  : trust.updating
                    ? " Progress is persisted, so you can leave this page safely."
                    : ""}
              </p>
            )}

            <div className={styles.buttonRow}>
              {renderConnectionAction()}
              <a className={styles.textLink} href="/training">
                Review saved training
              </a>
              <a className={styles.textLink} href="/import/garmin-archive">
                Historical import &amp; recovery
              </a>
            </div>

            <details className={styles.details}>
              <summary>How duplicate imports and provenance are handled</summary>
              <p>
                Imported workouts are reconciled into account-owned canonical history while source
                provenance is retained. Matching activities are not intentionally presented as a
                second visible workout just because the same source data is imported again.
              </p>
            </details>
          </section>

          <section id="coaching" className={styles.card} tabIndex="-1">
            <p className={styles.eyebrow}>Coaching</p>
            <h2>Same goal, same evidence</h2>
            <p>
              Coach uses the saved athlete goal and canonical training evidence surfaced elsewhere
              in Fitness Pals. Missing or stale signals remain uncertainty rather than becoming zero.
            </p>
            <a className={styles.textLink} href="/coach?from=%2Fsettings">
              Continue with Coach
            </a>
          </section>

          <section id="data-privacy" className={styles.card} tabIndex="-1">
            <p className={styles.eyebrow}>Data &amp; privacy</p>
            <h2>Know what is retained</h2>
            <p>
              Canonical training history and provenance are account-owned product records. This
              Settings build does not advertise a self-service export, deletion, or disconnect
              control that the backend cannot actually complete.
            </p>
            <a className={styles.textLink} href="/privacy">
              Read the Privacy Policy
            </a>
          </section>

          <section id="account" className={styles.card} tabIndex="-1">
            <p className={styles.eyebrow}>Account</p>
            <h2>Session</h2>
            <p>Sign out when you are finished, especially on a shared device.</p>
            <a className={styles.textLink} href="/auth/logout">
              Sign out
            </a>
          </section>
        </div>
      )}
    </AuthenticatedShell>
  );
}
