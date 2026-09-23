import { useCallback, useEffect, useMemo, useState } from "react";
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

function safeCoachPrompt(value) {
  if (typeof value !== "string") return "";
  return value.replace(/[\r\n]+/g, " ").trim().slice(0, 500);
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

function contextFromQuery(query) {
  const from = safeSourcePath(query.from);
  if (!from && typeof query.activity !== "string") return null;
  const search = from && from.includes("?") ? from.split("?").slice(1).join("?") : "";
  const params = new URLSearchParams(search);
  const activity = typeof query.activity === "string" ? query.activity : null;
  const label = safeCoachPrompt(query.label) || sourceLabel(from);
  return {
    source_route: from,
    activity_id: activity,
    window: params.get("window"),
    sport: params.get("sport"),
    goal: params.get("goal"),
    label,
  };
}

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function evidenceLabel(kind) {
  if (kind === "measured") return "Measured fact";
  if (kind === "derived") return "Derived metric";
  if (kind === "estimate") return "Estimate / model output";
  return "Evidence";
}

export default function Coach() {
  const router = useRouter();
  const [threads, setThreads] = useState([]);
  const [threadId, setThreadId] = useState(null);
  const [thread, setThread] = useState(null);
  const [context, setContext] = useState(null);
  const [snapshot, setSnapshot] = useState({ home: null, plan: null, intelligence: null });
  const [preferenceDraft, setPreferenceDraft] = useState("");
  const [preferenceBusy, setPreferenceBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [actionBusy, setActionBusy] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const queryContext = useMemo(
    () => (router.isReady ? contextFromQuery(router.query) : null),
    [
      router.isReady,
      router.query.activity,
      router.query.from,
      router.query.goal,
      router.query.label,
      router.query.sport,
      router.query.window,
    ]
  );

  const loadThreads = useCallback(async () => {
    const data = await authenticatedJson("/api/chat/threads");
    setThreads(data.threads || []);
  }, []);

  const loadThread = useCallback(async (id) => {
    const data = await authenticatedJson("/api/chat/threads/" + id);
    setThread(data);
    setContext(data.context || null);
    return data;
  }, []);

  useEffect(() => {
    if (!router.isReady) return;
    const requestedThread =
      typeof router.query.thread === "string" ? router.query.thread : null;
    setThreadId(requestedThread);
    setError("");
    setNotice("");
    if (requestedThread) {
      loadThread(requestedThread).catch((requestError) => {
        setThread(null);
        setError(
          requestError.status === 404
            ? "That Coach conversation is unavailable for this account."
            : "Coach could not load that conversation."
        );
      });
    } else {
      setThread(null);
      setContext(queryContext);
      if (typeof router.query.prompt === "string") {
        setMessage(safeCoachPrompt(router.query.prompt));
      }
    }
  }, [
    loadThread,
    queryContext,
    router.isReady,
    router.query.prompt,
    router.query.thread,
  ]);

  useEffect(() => {
    Promise.all([
      loadThreads(),
      authenticatedJson("/api/athlete-home"),
      authenticatedJson("/api/today-plan"),
      authenticatedJson("/api/intelligence"),
    ])
      .then(([, home, plan, intelligence]) => {
        setSnapshot({ home, plan, intelligence });
        setPreferenceDraft((intelligence.preferences || []).join("\n"));
      })
      .catch(() =>
        setError(
          "Some Coach context could not be refreshed. Your saved conversations are unchanged."
        )
      );
  }, [loadThreads]);

  async function send(event) {
    event.preventDefault();
    const question = message.trim();
    if (!question || sending) return;
    setSending(true);
    setError("");
    setNotice("");
    try {
      const data = await authenticatedJson("/api/chat", {
        method: "POST",
        json: {
          message: question,
          thread_id: threadId,
          context: threadId ? null : context,
        },
      });
      setThreadId(data.thread.id);
      setThread(data.thread);
      setContext(data.thread.context || null);
      setMessage("");
      await loadThreads();
      if (data.turn.status === "failed") {
        setNotice(
          "Coach could not answer this turn. The question is saved and ready to retry."
        );
      }
      if (router.query.thread !== data.thread.id) {
        await router.replace(
          { pathname: "/coach", query: { thread: data.thread.id } },
          undefined,
          { shallow: true }
        );
      }
    } catch (requestError) {
      setError(
        requestError.status === 401
          ? "Your session ended. Sign in again to return to this Coach conversation."
          : "Coach could not save that question. It remains in the composer so you can try again."
      );
    } finally {
      setSending(false);
    }
  }

  async function retryTurn(turnId) {
    if (!threadId || sending) return;
    setSending(true);
    setError("");
    try {
      const data = await authenticatedJson("/api/chat", {
        method: "POST",
        json: { thread_id: threadId, retry_turn_id: turnId },
      });
      setThread(data.thread);
      await loadThreads();
      setNotice(
        data.turn.status === "failed"
          ? "Coach is still unavailable. The saved question can be retried again."
          : "Coach answered the saved question."
      );
    } catch (_requestError) {
      setError("That saved turn could not be retried just now.");
    } finally {
      setSending(false);
    }
  }

  async function removeContext() {
    if (!threadId) {
      setContext(null);
      return;
    }
    try {
      const data = await authenticatedJson(
        "/api/chat/threads/" + threadId + "/context",
        { method: "PATCH" }
      );
      setThread(data);
      setContext(null);
      setNotice("Conversation context removed.");
    } catch (_requestError) {
      setError("Coach could not remove that context just now.");
    }
  }

  async function savePreferences(event) {
    event.preventDefault();
    if (preferenceBusy) return;
    const preferences = preferenceDraft
      .split("\n")
      .map((item) => item.trim())
      .filter(Boolean)
      .slice(0, 8);
    setPreferenceBusy(true);
    setError("");
    try {
      const intelligence = await authenticatedJson("/api/intelligence/preferences", {
        method: "PATCH",
        json: { preferences },
      });
      setSnapshot((current) => ({ ...current, intelligence }));
      setPreferenceDraft((intelligence.preferences || []).join("\n"));
      setNotice(
        preferences.length
          ? "Coach preferences saved deliberately."
          : "Saved Coach preferences cleared."
      );
    } catch (_requestError) {
      setError("Coach preferences could not be saved just now.");
    } finally {
      setPreferenceBusy(false);
    }
  }

  async function clearPreferences() {
    if (preferenceBusy) return;
    setPreferenceBusy(true);
    setError("");
    try {
      const intelligence = await authenticatedJson("/api/intelligence/preferences", {
        method: "PATCH",
        json: { preferences: [] },
      });
      setSnapshot((current) => ({ ...current, intelligence }));
      setPreferenceDraft("");
      setNotice("Saved Coach preferences cleared.");
    } catch (_requestError) {
      setError("Coach preferences could not be cleared just now.");
    } finally {
      setPreferenceBusy(false);
    }
  }

  async function runAction(action) {
    if (action.kind !== "mutation" || actionBusy) return;
    if (action.confirm && !window.confirm(action.confirm)) return;
    setActionBusy(action.id);
    setError("");
    try {
      await authenticatedJson(action.href, {
        method: action.method || "PATCH",
        json: action.payload || {},
      });
      if (threadId) await loadThread(threadId);
      const plan = await authenticatedJson("/api/today-plan");
      setSnapshot((current) => ({ ...current, plan }));
      setNotice("Your saved training decision was updated everywhere.");
    } catch (_requestError) {
      setError("That training decision could not be saved just now.");
    } finally {
      setActionBusy("");
    }
  }

  function startNewThread() {
    setThreadId(null);
    setThread(null);
    setContext(null);
    setMessage("");
    setError("");
    setNotice("");
    router.push("/coach");
  }

  const home = snapshot.home;
  const intelligence = snapshot.intelligence;
  const association = intelligence?.associations?.[0];
  const generatedView = intelligence?.views?.[0];
  const currentGoal = thread?.goal || snapshot.plan?.goal || home?.goal;
  const currentPlan = thread?.plan || snapshot.plan?.plan;
  const recentActivity = home?.recent_activities?.[0];
  const suggested = [
    currentPlan
      ? "Why is this the right session for my current goal?"
      : "What should I focus on next?",
    recentActivity
      ? "What does my latest activity say about my progress?"
      : "What changed in my training recently?",
    "What evidence matters most for my current goal?",
    "What if I changed this week's mileage? Treat it as a hypothetical.",
  ];

  return (
    <AuthenticatedShell active="coach">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your coach</p>
        <h1>Ask about your training</h1>
        <p className={styles.lede}>
          Keep follow-ups, evidence, and saved training actions together, even when you
          leave to inspect the underlying data and come back.
        </p>
      </header>

      {intelligence && (
        <section className={styles.card} aria-label="Athlete intelligence">
          <div className={styles.sectionHeading}>
            <div>
              <p className={styles.eyebrow}>Athlete intelligence</p>
              <h2>What changed?</h2>
            </div>
            <a className={styles.textLink} href={intelligence.briefing?.href || "/progress"}>
              Inspect the evidence
            </a>
          </div>

          <p><strong>{intelligence.briefing?.headline}</strong></p>
          {(intelligence.briefing?.details || []).map((detail) => (
            <p key={detail}>{detail}</p>
          ))}

          <div className={styles.coachSnapshot} aria-label="Athlete-to-self comparison">
            <article>
              <span>Athlete-to-self</span>
              <strong>{intelligence.athlete_to_self?.current?.miles ?? "Unknown"} mi</strong>
              <small>Latest 7 days</small>
            </article>
            <article>
              <span>Previous baseline</span>
              <strong>{intelligence.athlete_to_self?.previous?.miles ?? "Unknown"} mi</strong>
              <small>Preceding 7 days</small>
            </article>
            <article>
              <span>Goal trajectory</span>
              <strong>
                {intelligence.trajectory?.days_to_target === null ||
                intelligence.trajectory?.days_to_target === undefined
                  ? "No target date"
                  : intelligence.trajectory.days_to_target + " days"}
              </strong>
              <small>Inputs, not a readiness score or prediction</small>
            </article>
          </div>

          <details className={styles.details}>
            <summary>N-of-1 associations and Coach-generated view</summary>
            <div className={styles.coachEvidenceGrid}>
              <div className={styles.coachEvidenceCard}>
                <span>N-of-1 association</span>
                <strong>{association?.title || "Association unavailable"}</strong>
                <p>
                  {association?.state === "available"
                    ? association.direction +
                      " " +
                      association.strength +
                      " association across " +
                      association.sample_size +
                      " paired observations."
                    : "Not enough paired evidence yet. Sample size: " +
                      (association?.sample_size ?? 0) +
                      "."}
                </p>
                <p>{association?.caveat}</p>
                {association?.href && <a href={association.href}>Inspect source window</a>}
              </div>
              <div className={styles.coachEvidenceCard}>
                <span>Coach-generated view</span>
                <strong>{generatedView?.title || "Training view unavailable"}</strong>
                {generatedView?.points?.length ? (
                  <ol>
                    {generatedView.points.map((point) => (
                      <li key={point.week_start}>
                        {formatDate(point.week_start)}:{" "}
                        {point.miles === null ? "distance unknown" : point.miles + " mi"},{" "}
                        {point.active_days} active days
                      </li>
                    ))}
                  </ol>
                ) : (
                  <p>No bounded weekly view is available yet.</p>
                )}
                <p>{generatedView?.note}</p>
              </div>
            </div>
          </details>

          <StatusNotice tone="neutral">
            Hypothetical questions are labeled as projections, not observed facts. Missing or stale
            signals stay explicit, and athlete-to-self associations do not establish causation.
          </StatusNotice>

          <form className={styles.chatForm} onSubmit={savePreferences}>
            <label htmlFor="coach-preferences">
              Coaching preferences you deliberately want Coach to remember
            </label>
            <textarea
              id="coach-preferences"
              value={preferenceDraft}
              onChange={(event) => setPreferenceDraft(event.target.value)}
              placeholder={"One preference per line, for example:\nPrefer time-based easy runs"}
            />
            <div className={styles.buttonRow}>
              <button
                className={styles.secondaryButton}
                type="submit"
                disabled={preferenceBusy}
              >
                {preferenceBusy ? "Saving…" : "Save preferences"}
              </button>
              <button
                className={styles.secondaryButton}
                type="button"
                onClick={clearPreferences}
                disabled={preferenceBusy || !(intelligence.preferences || []).length}
              >
                Clear saved preferences
              </button>
            </div>
          </form>
        </section>
      )}

      <div className={styles.coachWorkspace}>
        <aside className={styles.threadSidebar} aria-label="Coach conversations">
          <div className={styles.sectionHeading}>
            <h2>Conversations</h2>
            <button
              className={styles.compactButton}
              type="button"
              onClick={startNewThread}
            >
              New
            </button>
          </div>
          {threads.length ? (
            <nav className={styles.threadList} aria-label="Saved Coach conversations">
              {threads.map((item) => (
                <a
                  key={item.id}
                  href={"/coach?thread=" + item.id}
                  aria-current={item.id === threadId ? "page" : undefined}
                >
                  <strong>{item.title}</strong>
                  <span>
                    {item.context_label ||
                      item.turn_count +
                        " turn" +
                        (item.turn_count === 1 ? "" : "s")}
                  </span>
                </a>
              ))}
            </nav>
          ) : (
            <p className={styles.muted}>
              Your first question will start a durable conversation.
            </p>
          )}
        </aside>

        <div className={styles.coachMain}>
          <section
            className={styles.coachSnapshot}
            aria-label="Current coaching context"
          >
            <div>
              <span>Current focus</span>
              <strong>{currentGoal?.label || "No goal selected yet"}</strong>
              <small>
                {currentGoal?.phase_label || "Ask Coach or set a goal in Today"}
              </small>
            </div>
            <div>
              <span>Current decision</span>
              <strong>
                {currentPlan?.session_purpose || "No session decision yet"}
              </strong>
              <small>
                {currentPlan?.status
                  ? currentPlan.status.replaceAll("_", " ")
                  : "Open Today to plan"}
              </small>
            </div>
            <div>
              <span>Latest record</span>
              <strong>{recentActivity?.title || "No recent activity"}</strong>
              <small>
                {home?.data_through
                  ? "Data through " + formatDate(home.data_through)
                  : "Freshness unknown"}
              </small>
            </div>
          </section>

          {context && (
            <div className={styles.contextChip} role="status">
              <span>
                Talking about:{" "}
                <strong>
                  {context.label ||
                    sourceLabel(context.source_route) ||
                    "selected training context"}
                </strong>
              </span>
              {context.source_route && (
                <a href={context.source_route}>View evidence</a>
              )}
              <button
                type="button"
                onClick={removeContext}
                aria-label="Remove Coach context"
              >
                Remove
              </button>
            </div>
          )}

          {thread?.freshness?.state && (
            <StatusNotice
              tone={thread.freshness.state === "stale" ? "warning" : "neutral"}
            >
              Coaching context: {thread.freshness.state}
              {thread.freshness.data_through
                ? " · data through " + formatDate(thread.freshness.data_through)
                : ""}
            </StatusNotice>
          )}

          {error && <StatusNotice tone="warning">{error}</StatusNotice>}
          {notice && <StatusNotice tone="neutral">{notice}</StatusNotice>}

          <section
            className={styles.messagePanel}
            aria-label="Coach conversation"
            aria-live="polite"
          >
            {thread?.turns?.length ? (
              <ol className={styles.messageList}>
                {thread.turns.map((turn) => (
                  <li key={turn.id}>
                    <article className={styles.athleteMessage}>
                      <span>You</span>
                      <p>{turn.question}</p>
                    </article>
                    {turn.status === "failed" ? (
                      <article className={styles.failedMessage} role="status">
                        <strong>
                          Coach could not answer this saved question.
                        </strong>
                        <p>No answer was treated as successful or lost.</p>
                        <button
                          className={styles.secondaryButton}
                          type="button"
                          onClick={() => retryTurn(turn.id)}
                          disabled={sending}
                        >
                          Retry this question
                        </button>
                      </article>
                    ) : (
                      <article className={styles.coachMessage}>
                        <span className={styles.interpretationBadge}>
                          Coaching interpretation
                        </span>
                        <p>{turn.answer}</p>
                        {turn.evidence?.length ? (
                          <details className={styles.details}>
                            <summary>Evidence and limits</summary>
                            <div className={styles.coachEvidenceGrid}>
                              {turn.evidence.map((item, index) => (
                                <div
                                  className={styles.coachEvidenceCard}
                                  key={
                                    turn.id +
                                    "-" +
                                    item.kind +
                                    "-" +
                                    index
                                  }
                                >
                                  <span>
                                    {item.label || evidenceLabel(item.kind)}
                                  </span>
                                  <strong>{item.title}</strong>
                                  <p>{item.summary}</p>
                                  {item.href && (
                                    <a href={item.href}>
                                      Open supporting evidence
                                    </a>
                                  )}
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : null}
                      </article>
                    )}
                  </li>
                ))}
              </ol>
            ) : (
              <div className={styles.emptyConversation}>
                <h2>Start with what you want to understand</h2>
                <p>
                  Coach already has your saved goal, current decision, and
                  available canonical training context.
                </p>
              </div>
            )}
          </section>

          {thread?.actions?.length ? (
            <section
              className={styles.coachActions}
              aria-label="Saved training actions"
            >
              <strong>Act on the same saved plan</strong>
              <div className={styles.buttonRow}>
                {thread.actions.map((action) =>
                  action.kind === "mutation" ? (
                    <button
                      className={styles.secondaryButton}
                      key={action.id}
                      type="button"
                      onClick={() => runAction(action)}
                      disabled={Boolean(actionBusy)}
                    >
                      {actionBusy === action.id ? "Saving…" : action.label}
                    </button>
                  ) : (
                    <a
                      className={styles.textLink}
                      key={action.id}
                      href={action.href}
                    >
                      {action.label}
                    </a>
                  )
                )}
              </div>
            </section>
          ) : null}

          <section className={styles.composerCard}>
            <div
              className={styles.suggestionRow}
              aria-label="Suggested Coach questions"
            >
              {suggested.map((question) => (
                <button
                  key={question}
                  type="button"
                  onClick={() => setMessage(question)}
                >
                  {question}
                </button>
              ))}
            </div>
            <form className={styles.chatForm} onSubmit={send}>
              <label htmlFor="coach-question">Your question</label>
              <textarea
                id="coach-question"
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                placeholder="Ask a follow-up or start a new question…"
              />
              <button
                className={styles.primaryButton}
                type="submit"
                disabled={sending || !message.trim()}
              >
                {sending
                  ? "Thinking…"
                  : threadId
                    ? "Send follow-up"
                    : "Ask Coach"}
              </button>
            </form>
          </section>
        </div>
      </div>
    </AuthenticatedShell>
  );
}
