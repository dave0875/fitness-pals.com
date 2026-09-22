import { useEffect, useState } from "react";
import { useRouter } from "next/router";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import { authenticatedJson } from "../lib/authFetch.mjs";
import styles from "../styles/AthletePages.module.css";

function safeSourcePath(value) {
  if (
    typeof value !== "string" ||
    !value.startsWith("/") ||
    value.startsWith("//") ||
    value.includes("\\") ||
    /%5c/i.test(value)
  ) return null;
  if (value.startsWith("/coach")) return null;
  return value;
}

function sourceLabel(value) {
  if (!value) return null;
  if (value.startsWith("/activities/")) return "an activity";
  if (value.startsWith("/training")) return "Training";
  if (value.startsWith("/progress") || value.startsWith("/journey")) return "Progress";
  if (value.startsWith("/settings") || value.startsWith("/import/")) return "your data connection";
  if (value.startsWith("/dossiers")) return "a saved analysis";
  return "Today";
}

export default function Coach() {
  const router = useRouter();
  const [message, setMessage] = useState("");
  const [response, setResponse] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");

  const from = safeSourcePath(router.query.from);
  const label = sourceLabel(from);

  useEffect(() => {
    if (!router.isReady) return;
    if (typeof router.query.prompt === "string") setMessage(router.query.prompt);
  }, [router.isReady, router.query.prompt]);

  async function send(event) {
    event.preventDefault();
    const question = message.trim();
    if (!question || sending) return;
    setSending(true);
    setError("");
    try {
      const data = await authenticatedJson("/api/chat", {
        method: "POST",
        json: { message: question },
      });
      setResponse(data.response);
      setMessage("");
    } catch (requestError) {
      setError(
        requestError.status === 401
          ? "Your session ended. Sign in again and your Coach page will still be here."
          : "Coach could not answer just now. Your question is still available above; try again."
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <AuthenticatedShell active="coach">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your coach</p>
        <h1>Ask about your training</h1>
        <p className={styles.lede}>
          Ask naturally. Fitness Pals grounds the answer in the training and recovery data
          currently available to your account.
        </p>
      </header>

      {from && (
        <StatusNotice tone="neutral">
          Talking about: <strong>{label}</strong>.{" "}
          <a href={from}>Return to what you were viewing</a>.
        </StatusNotice>
      )}

      <section className={styles.wideCard}>
        <h2>What do you want to understand?</h2>
        <p>
          Try “How did my last long run help my goal?”, “What should I do today?”, or
          “What changed in my training recently?”
        </p>
        <form className={styles.chatForm} onSubmit={send}>
          <label htmlFor="coach-question">Your question</label>
          <textarea
            id="coach-question"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Ask Coach…"
          />
          <button className={styles.primaryButton} type="submit" disabled={sending || !message.trim()}>
            {sending ? "Thinking…" : "Ask Coach"}
          </button>
        </form>
      </section>

      {error && <StatusNotice tone="warning">{error}</StatusNotice>}

      {response && (
        <section className={styles.wideCard} aria-live="polite">
          <p className={styles.eyebrow}>Coach</p>
          <h2>Here is what I see</h2>
          <p>{response}</p>
        </section>
      )}
    </AuthenticatedShell>
  );
}
