import { useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../../components/AuthenticatedShell";
import { authenticatedFetch } from "../../lib/authFetch.mjs";
import styles from "../../styles/AthletePages.module.css";


const POLL_INTERVAL_MS = 3000;

export default function GarminArchiveImport() {
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function poll(statusUrl) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const response = await authenticatedFetch(statusUrl);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Archive status failed.");
      if (payload.status === "completed") return payload;
      if (payload.status === "failed") {
        throw new Error(payload.error?.message || "Archive import failed.");
      }
      await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
    }
    throw new Error("The import is still running. You can return to this page later.");
  }

  async function runDriveImport() {
    setBusy(true);
    setMessage("Queueing your configured Google Drive archive…");
    try {
      const response = await authenticatedFetch("/api/archive-imports/google-drive", {
        method: "POST",
        credentials: "same-origin",
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Drive archive is not configured.");
      const result = await poll(payload.status_url);
      setMessage(
        `Import complete: ${result.activities || 0} activities from ${result.objects_imported || 0} new objects; ${result.objects_skipped || 0} unchanged objects skipped.`
      );
    } catch (error) {
      setMessage(error.message || "Drive archive import failed.");
    } finally {
      setBusy(false);
    }
  }

  async function runUpload(event) {
    event.preventDefault();
    if (!selectedFile) return setMessage("Choose a Garmin export zip first.");
    setBusy(true);
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
      const result = await poll(start.status_url);
      setMessage(`Import complete: ${result.activities || 0} activities processed.`);
    } catch (error) {
      setMessage(error.message || "Archive import failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthenticatedShell active="settings">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Historical data</p>
        <h1>Import Garmin archive</h1>
        <p className={styles.lede}>
          The Drive source is assigned to your athlete account on the server. Each file is
          checkpointed with its Drive version and provenance, so retries skip unchanged history.
        </p>
      </header>

      {message && <StatusNotice>{message}</StatusNotice>}

      <div className={styles.sectionGrid}>
        <section className={styles.card}>
          <h2>Google Drive source of truth</h2>
          <p>Queue the private Garmin folder configured for your signed-in athlete account.</p>
          <button type="button" onClick={runDriveImport} disabled={busy}>
            {busy ? "Import running…" : "Import from Google Drive"}
          </button>
        </section>

        <section className={styles.card}>
          <h2>Garmin export zip</h2>
          <form onSubmit={runUpload}>
            <input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => setSelectedFile(event.target.files?.[0] || null)}
            />
            <button type="submit" disabled={busy}>Upload and import</button>
          </form>
        </section>
      </div>
    </AuthenticatedShell>
  );
}
