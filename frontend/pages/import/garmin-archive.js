import { useCallback, useEffect, useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../../components/AuthenticatedShell";
import { authenticatedFetch } from "../../lib/authFetch.mjs";
import { archiveState } from "../../lib/coreFlowStates.mjs";
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

  useEffect(() => {
    if (!flow.pending || !job?.status_url) return undefined;
    const timer = window.setInterval(async () => {
      try {
        const response = await authenticatedFetch(job.status_url);
        const payload = await response.json();
        if (!response.ok) throw new Error(payload.detail || "Archive status could not be checked.");
        setJob(payload);
      } catch (error) {
        setMessage(error.message || "Archive status could not be checked.");
      }
    }, 3000);
    return () => window.clearInterval(timer);
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
        <p className={styles.eyebrow}>Historical data</p>
        <h1>Import Garmin archive</h1>
        <p className={styles.lede}>
          Authorize read-only access to the same Google account you use for Fitness Pals, or upload
          a Garmin export. Imports run in the background and resume here when you return.
        </p>
      </header>

      {loading && <StatusNotice>Checking archive availability…</StatusNotice>}
      {message && <StatusNotice tone={job?.status === "failed" ? "warning" : "neutral"}>{message}</StatusNotice>}
      {flow.pending && (
        <StatusNotice>Import in progress: {String(job.status).replaceAll("_", " ")}.</StatusNotice>
      )}
      {job?.status === "failed" && (
        <StatusNotice tone="warning">
          Import failed: {job.error?.message || "The archive could not be processed."} Try import again below.
        </StatusNotice>
      )}
      {job?.status === "completed" && (
        <StatusNotice tone="success">
          Import complete: {job.activities || 0} activities processed.{" "}
          <a href="/journey#activities">Review imported activities</a>.
        </StatusNotice>
      )}

      <div className={styles.sectionGrid}>
        <section className={styles.card}>
          <h2>Google Drive source of truth</h2>
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
    </AuthenticatedShell>
  );
}
