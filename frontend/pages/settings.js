import { useState } from "react";
import axios from "axios";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import styles from "../styles/AthletePages.module.css";

const fields = [
  { key: "url", label: "Server address", type: "url", autoComplete: "url" },
  { key: "org", label: "Organization", type: "text", autoComplete: "off" },
  { key: "bucket", label: "Fitness data bucket", type: "text", autoComplete: "off" },
  { key: "token", label: "Access token", type: "password", autoComplete: "off" },
];

export default function Settings() {
  const [form, setForm] = useState({ url: "", org: "", bucket: "", token: "" });
  const [status, setStatus] = useState("");
  const [tone, setTone] = useState("neutral");

  const connect = async () => {
    setStatus("Saving your connection…");
    setTone("neutral");
    try {
      await axios.post("/api/datasource/influx/connect", form);
      setStatus("Connection saved.");
      setTone("success");
    } catch (err) {
      setStatus("We could not save this connection. Check your session and the values above.");
      setTone("error");
    }
  };

  const verify = async () => {
    setStatus("Checking your connection…");
    setTone("neutral");
    try {
      await axios.get("/api/datasource/influx/verify");
      setStatus("Connection verified.");
      setTone("success");
    } catch (err) {
      setStatus("We could not verify this connection.");
      setTone("error");
    }
  };

  return (
    <AuthenticatedShell active="settings">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your account</p>
        <h1>Settings</h1>
        <p className={styles.lede}>
          Manage how your fitness information reaches Fitness Pals. Account, privacy, and
          connection controls will continue to move into this one place.
        </p>
      </header>

      <div className={styles.sectionGrid}>
        <section className={styles.card}>
          <h2>Fitness connection</h2>
          <p>
            The guided connection flow is the easiest way to connect or refresh your activity data.
          </p>
          <a className={styles.textLink} href="/welcome">Open guided setup</a>
        </section>

        <section className={styles.card}>
          <h2>Session</h2>
          <p>Sign out when you are finished, especially on a shared device.</p>
          <a className={styles.textLink} href="/auth/logout">Sign out</a>
        </section>

        <section className={styles.wideCard}>
          <h2>Advanced data source</h2>
          <p>
            Keep these legacy connection controls available for existing self-hosted data sources.
          </p>
          <details className={styles.details}>
            <summary>Configure an advanced connection</summary>
            <div className={styles.form}>
              {fields.map((field) => (
                <label key={field.key} htmlFor={`datasource-${field.key}`}>
                  {field.label}
                  <input
                    id={`datasource-${field.key}`}
                    type={field.type}
                    autoComplete={field.autoComplete}
                    value={form[field.key]}
                    onChange={(event) => setForm({ ...form, [field.key]: event.target.value })}
                  />
                </label>
              ))}
              <div className={styles.buttonRow}>
                <button className={styles.primaryButton} type="button" onClick={connect}>
                  Save connection
                </button>
                <button className={styles.secondaryButton} type="button" onClick={verify}>
                  Test connection
                </button>
              </div>
            </div>
          </details>
          {status && (
            <div className={styles.statusRow}>
              <StatusNotice tone={tone}>{status}</StatusNotice>
            </div>
          )}
        </section>
      </div>
    </AuthenticatedShell>
  );
}
