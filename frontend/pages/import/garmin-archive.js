import { useCallback, useEffect, useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../../components/AuthenticatedShell";
import { authenticatedFetch } from "../../lib/authFetch.mjs";
import { archiveProgress, archiveState } from "../../lib/coreFlowStates.mjs";
import styles from "../../styles/AthletePages.module.css";


export default function GarminArchiveImport() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState("");
  const [capabilities, setCapabilities] = useState(null);
  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);

  const loadCapabilities = useCallback(async () => {
    try {
      const response = await authenticatedFetch("/api/archive-imports/capabilities");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Archive options could not be checked.");
      setCapabilities(payload);
      setJob(payload.latest_job || null);
      setMessage("");
    } catch (error) {
      setMessage(error.message || "Archive options could not be checked.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadCapabilities();
  }, [loadCapabilities]);

  const flow = archiveState(capabilities, job);
  const progress = archiveProgress(job);

  useEffect(() => {
    const statusUrl = job?.status_url;
    if (!flow.pending || !statusUrl) return undefined;

    let active = true;
    const refreshStatus = async () => {
      try {
        const response = await authenticatedFetch(statusUrl, {
          cache: "no-store",
          headers: { "Cache-Control": "no-cache" },
        });
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Archive status could not be checked.");
        if (!active) return;
        setJob(payload);
        setMessage("");
      } catch (error) {
        if (active) setMessage(error.message || "Archive status could not be checked.");
      }
    };

    refreshStatus();
    const timer = window.setInterval(refreshStatus, 3000);
    const refreshWhenVisible = () => {
      if (document.visibilityState === "visible") refreshStatus();
    };
    document.addEventListener("visibilitychange", refreshWhenVisible);

    return () => {
      active = false;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshWhenVisible);
    };
  }, [flow.pending, job?.status_url]);

  async function runDriveImport() {
    setMessage("Searching your Google Drive for Garmin archive data…");
    try {
      const response = await authenticatedFetch("/api/archive-imports/google-drive", {
        method: "POST",
        credentials: "same-origin",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Drive archive is not configured.");
      setJob(payload);
      setMessage("Archive import queued. Progress will update here.");
    } catch (error) {
      setMessage(error.message || "Drive archive import failed.");
    }
  }

  async function runUpload(event) {
    event.preventDefault();
    if (!selectedFile) return setMessage("Choose a Garmin export zip first.");
    setMessage("Preparing archive upload…");
    try {
      const startResponse = await authenticatedFetch("/api/archive-imports/uploads/start", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          filename: selectedFile.name,
          content_type: selectedFile.type || "application/zip",
          size_bytes: selectedFile.size,
        }),
      });
      const start = await startResponse.json();
      if (!startResponse.ok) throw new Error(start.detail || "Archive upload could not start.");
      const uploadResponse = await fetch(start.upload.url, {
        method: start.upload.method,
        headers: start.upload.headers,
        body: selectedFile,
      });
      if (!uploadResponse.ok) throw new Error("Archive upload failed.");
      const completeResponse = await authenticatedFetch(start.complete_url, {
        method: "POST",
        credentials: "same-origin",
      });
      const complete = await completeResponse.json();
      if (!completeResponse.ok) throw new Error(complete.detail || "Archive could not be queued.");
      setJob({ ...complete, status_url: start.status_url });
      setMessage("Archive uploaded and queued. Progress will update here.");
    } catch (error) {
      setMessage(error.message || "Archive import failed.");
    }
  }

  return (
    <AuthenticatedShell active="settings">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Connections · Historical data</p>
        <h1>Import Garmin archive</h1>
        <p className={styles.lede}>
          Use a supported archive path when live updates are unavailable or when you need older
          history. Imports persist in the background, and matching activities are reconciled with
          canonical history instead of being presented as a second visible workout.
        </p>
        <a className={styles.textLink} href="/settings#connections">
          Back to Connections
        </a>
      </header>

      {loading && <StatusNotice>Checking archive availability…</StatusNotice>}
      {message && <StatusNotice tone={job?.status === "failed" ? "warning" : "neutral"}>{message}</StatusNotice>}
      {flow.pending && (
        <StatusNotice>
          <strong>{progress.label}.</strong> {progress.detail} You can leave this page safely.{" "}
          <a href="/coach?from=%2Fimport%2Fgarmin-archive&prompt=Help%20me%20use%20my%20saved%20goal%20while%20my%20training%20history%20finishes%20importing.">
            Continue with Coach
          </a>.
          {progress.total > 0 && (
            <div>
              <progress
                aria-label="Garmin archive import progress"
                max={progress.total}
                value={progress.processed}
              >
                {progress.percent}%
              </progress>
              <span> {progress.percent}%</span>
            </div>
          )}
        </StatusNotice>
      )}
      {job?.status === "failed" && (
        <StatusNotice tone="warning">
          The latest import did not finish. Your saved training history is unchanged, and you can try again below.
        </StatusNotice>
      )}
      {job?.status === "completed" && (
        <StatusNotice tone="success">
          Import complete: {job.activities || 0} activities processed. Matching activities are
          reconciled rather than intentionally shown twice.{" "}
          <a href="/training">Review imported activities</a> or{" "}
          <a href="/settings#connections">return to Connections</a>.
        </StatusNotice>
      )}

      <div className={styles.sectionGrid}>
        <section className={styles.card}>
          <h2>Garmin files in Google Drive</h2>
          {loading ? (
            <p>Checking Google Drive authorization…</p>
          ) : capabilities?.drive?.connected ? (
            <>
              <p>
                Connected to {capabilities.drive.account_email}. Fitness Pals can read Drive files
                but cannot edit or delete them.
              </p>
              {flow.canDriveImport && (
                <button className={styles.primaryButton} type="button" onClick={runDriveImport}>
                  {job?.status === "failed" ? "Try import again" : "Search Drive for Garmin data"}
                </button>
              )}
            </>
          ) : capabilities?.drive?.authorization_available ? (
            <>
              <p>
                Connect your Google Drive with read-only access. Google will ask you to confirm
                the account and permission before Fitness Pals searches for Garmin exports.
              </p>
              <a className={styles.textLink} href={capabilities.drive.authorization_url}>
                Authorize Google Drive
              </a>
            </>
          ) : capabilities?.drive?.legacy_source_available ? (
            <>
              <p>Your private Garmin folder is ready to import.</p>
              {flow.canDriveImport && (
                <button className={styles.primaryButton} type="button" onClick={runDriveImport}>
                  {job?.status === "failed" ? "Try import again" : "Import from Google Drive"}
                </button>
              )}
            </>
          ) : (
            <>
              <strong>Drive import unavailable</strong>
              <p>{flow.driveReason}</p>
            </>
          )}
        </section>

        <section className={styles.card}>
          <h2>Garmin export zip</h2>
          {loading ? (
            <p>Checking upload availability…</p>
          ) : capabilities?.upload?.available ? (
            <form className={styles.form} onSubmit={runUpload}>
              <input
                type="file"
                accept=".zip,application/zip"
                disabled={!flow.canUpload}
                onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
              />
              {flow.canUpload && (
                <button className={styles.primaryButton} type="submit">Upload and import</button>
              )}
            </form>
          ) : (
            <p>{flow.uploadReason}</p>
          )}
        </section>
      </div>

      <section className={styles.wideCard}>
        <h2>What happens to existing history?</h2>
        <p>
          Archive imports add or reconcile account-owned canonical training records. A failed import
          does not erase existing history, and retrying the same source is designed to reconcile
          matching activities rather than create a second visible workout.
        </p>
      </section>
    </AuthenticatedShell>
  );
}
