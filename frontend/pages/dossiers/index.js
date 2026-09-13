import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useCallback, useEffect, useMemo, useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../../components/AuthenticatedShell";
import { authenticatedJson } from "../../lib/authFetch.mjs";
import styles from "../../styles/Dossiers.module.css";

const ACTIVE_STATES = ["queued", "generating"];
const RECOVERABLE_STATES = ["insufficient_data", "failed"];
const KNOWN_STATES = [
  "queued",
  "generating",
  "completed",
  "superseded",
  "insufficient_data",
  "failed",
];

function safeFilter(value, fallback) {
  return typeof value === "string" && /^[a-zA-Z0-9_-]{1,40}$/.test(value)
    ? value.toLowerCase()
    : fallback;
}

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function stateLabel(state) {
  return String(state || "unknown").replaceAll("_", " ");
}

export default function DossierLibrary() {
  const router = useRouter();
  const [library, setLibrary] = useState(null);
  const [viewState, setViewState] = useState("loading");
  const [actionState, setActionState] = useState("idle");

  const selection = useMemo(
    () => ({
      window: safeFilter(router.query.window, "90d"),
      sport: safeFilter(router.query.sport, "all"),
      goal: safeFilter(router.query.goal, "all"),
    }),
    [router.query.goal, router.query.sport, router.query.window]
  );

  const loadLibrary = useCallback(async () => {
    try {
      const data = await authenticatedJson("/api/dossiers");
      setLibrary(data);
      setViewState("ready");
    } catch (error) {
      setViewState(error.status === 401 ? "unauthenticated" : "error");
    }
  }, []);

  useEffect(() => {
    loadLibrary();
  }, [loadLibrary]);

  const hasActiveJob = (library?.jobs || []).some((job) =>
    ACTIVE_STATES.includes(job.status)
  );

  useEffect(() => {
    if (!hasActiveJob) return undefined;
    const timer = window.setInterval(loadLibrary, 3000);
    return () => window.clearInterval(timer);
  }, [hasActiveJob, loadLibrary]);

  async function generateDossier() {
    setActionState("generating");
    try {
      await authenticatedJson("/api/dossiers", { method: "POST", json: selection });
      await loadLibrary();
      setActionState("idle");
    } catch {
      setActionState("failed");
    }
  }

  async function retry(jobId) {
    setActionState(jobId);
    try {
      await authenticatedJson(`/api/dossiers/jobs/${jobId}/retry`, { method: "POST" });
      await loadLibrary();
      setActionState("idle");
    } catch {
      setActionState("failed");
    }
  }

  return (
    <AuthenticatedShell active="dossiers">
      <Head>
        <title>Coaching dossiers | Fitness Pals</title>
      </Head>

      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>Private coaching history</p>
          <h1>Your coaching dossiers</h1>
          <p>
            Generate and revisit immutable coaching narratives grounded in your
            selected Journey evidence.
          </p>
        </div>
        <button
          type="button"
          onClick={generateDossier}
          disabled={actionState === "generating" || hasActiveJob}
        >
          {actionState === "generating" ? "Queuing…" : "Generate dossier"}
        </button>
      </header>

      <p className={styles.selection}>
        New dossier boundary: {selection.window} · {selection.sport} · {selection.goal}
      </p>

      {viewState === "loading" && (
        <section className={styles.statePanel} role="status">
          Loading your private dossier library…
        </section>
      )}
      {viewState === "unauthenticated" && (
        <StatusNotice tone="warning">
          Your session ended. <a href="/auth/login?next=%2Fdossiers">Sign in again</a>.
        </StatusNotice>
      )}
      {viewState === "error" && (
        <section className={styles.statePanel} role="alert">
          The dossier library is temporarily unavailable.
        </section>
      )}
      {actionState === "failed" && (
        <StatusNotice tone="warning">
          The request did not complete. Your existing dossiers were not changed.
        </StatusNotice>
      )}

      {viewState === "ready" && library && (
        <>
          <section className={styles.card}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Generation queue</p>
                <h2>Current requests</h2>
              </div>
            </div>
            {library.jobs.length === 0 ? (
              <p>No dossier generation is currently pending.</p>
            ) : (
              <ul className={styles.jobList}>
                {library.jobs.map((job) => (
                  <li key={job.id}>
                    <div>
                      <strong>{stateLabel(job.status)}</strong>
                      <span>
                        {job.filters.window} · {job.filters.sport} · {job.filters.goal}
                      </span>
                      <small>Requested {formatDate(job.created_at)}</small>
                    </div>
                    {RECOVERABLE_STATES.includes(job.status) && (
                      <button
                        type="button"
                        onClick={() => retry(job.id)}
                        disabled={actionState === job.id}
                      >
                        Retry
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <span className={styles.srOnly}>{KNOWN_STATES.join(", ")}</span>
          </section>

          <section className={styles.card}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Version history</p>
                <h2>Completed dossiers</h2>
              </div>
              <span>{library.artifacts.length} versions</span>
            </div>
            {library.artifacts.length === 0 ? (
              <p>
                Generate your first dossier after enough canonical activity history
                is available.
              </p>
            ) : (
              <ol className={styles.artifactList}>
                {library.artifacts.map((artifact) => (
                  <li key={artifact.id}>
                    <Link href={`/dossiers/${artifact.id}`}>
                      <div>
                        <strong>{artifact.title}</strong>
                        <span>
                          Version {artifact.version} · {stateLabel(artifact.state)}
                        </span>
                        <small>Data through {formatDate(artifact.data_through)}</small>
                      </div>
                      <span>{artifact.freshness || "unknown"}</span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <section className={styles.sample}>
            <div>
              <p className={styles.eyebrow}>Public sample</p>
              <h2>See the editorial format</h2>
              <p>
                This sample demonstrates presentation quality. It is not generated
                from your account and is not part of your private history.
              </p>
            </div>
            <a href="/coach-dossiers/urban-feet-coach-dossier-fourth-edition-2026-07-31">
              View public sample
            </a>
          </section>
        </>
      )}
    </AuthenticatedShell>
  );
}
