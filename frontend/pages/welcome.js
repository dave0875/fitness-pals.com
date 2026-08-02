import { useEffect, useMemo, useState } from "react";

const GOAL_OPTIONS = [
  ["marathon", "Train for a marathon"],
  ["half", "Train for a half"],
  ["consistency", "Rebuild consistency"],
  ["recovery", "Understand recovery"],
];

const GARMIN_WELCOME_NEXT = encodeURIComponent("/welcome?garmin=connected");
const GARMIN_EXPORT_IMPORT_HREF = "/import/garmin-export";

function panelStyle() {
  return {
    background: "#ffffff",
    border: "1px solid #dbe6ed",
    borderRadius: "24px",
    padding: "1.4rem",
    boxShadow: "0 18px 36px rgba(19, 32, 44, 0.05)",
  };
}

function GoalHandshake({ selectedGoal, onSelect, disabled = false }) {
  return (
    <div style={panelStyle()}>
      <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Goal handshake</h2>
      <p style={{ color: "#526472", lineHeight: 1.7, marginTop: "0.75rem" }}>
        Pick the reason you are here so the first insight is pointed in the right direction.
      </p>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
          gap: "0.8rem",
          marginTop: "1rem",
        }}
      >
        {GOAL_OPTIONS.map(([value, label]) => (
          <button
            key={value}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(value)}
            style={{
              padding: "0.9rem 1rem",
              borderRadius: "18px",
              border: selectedGoal === value ? "2px solid #0d5a55" : "1px solid #dbe6ed",
              background: selectedGoal === value ? "#e7f3f1" : "#f9fcfe",
              color: "#13202c",
              fontWeight: 700,
              cursor: disabled ? "default" : "pointer",
            }}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function Welcome() {
  const [welcomeState, setWelcomeState] = useState("bootstrapping");
  const [selectedGoal, setSelectedGoal] = useState("marathon");
  const [statusPayload, setStatusPayload] = useState(null);
  const [syncMessage, setSyncMessage] = useState("");

  const latestActivities = statusPayload?.latest_activities ?? [];
  const readinessPreview = statusPayload?.readiness_preview ?? null;
  const coachInsight = statusPayload?.coach_insight ?? null;
  const nextAction = statusPayload?.next_action ?? null;

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem("welcome_goal_handshake");
      if (stored) {
        setSelectedGoal(stored);
      }
    } catch (_error) {
      // ignore localStorage failures
    }
  }, []);

  useEffect(() => {
    let active = true;
    let pollId = null;

    async function loadStatus() {
      try {
        const sessionResponse = await fetch("/api/auth/session", { credentials: "include" });
        if (!active) {
          return;
        }
        if (!sessionResponse.ok) {
          setWelcomeState("unauthenticated");
          return;
        }

        const onboardingResponse = await fetch("/api/onboarding/status", {
          credentials: "include",
        });
        if (!active) {
          return;
        }
        if (!onboardingResponse.ok) {
          setWelcomeState("connect_garmin");
          return;
        }

        const payload = await onboardingResponse.json();
        if (!active) {
          return;
        }
        setStatusPayload(payload);
        if (payload.selected_goal) {
          setSelectedGoal(payload.selected_goal);
        }

        if (!payload.garmin_connected) {
          setWelcomeState("connect_garmin");
          return;
        }

        if (payload.first_sync?.state === "queued" || payload.first_sync?.state === "running") {
          setWelcomeState("sync_queued");
          setSyncMessage("Your training history is being imported now.");
          return;
        }

        if (payload.first_sync?.state === "completed" && payload.latest_activities?.length) {
          setWelcomeState("synced");
          return;
        }

        setWelcomeState("ready_to_sync");
      } catch (_error) {
        if (active) {
          setWelcomeState("unauthenticated");
        }
      }
    }

    loadStatus();

    if (welcomeState === "sync_queued") {
      pollId = window.setInterval(loadStatus, 4000);
    }

    return () => {
      active = false;
      if (pollId) {
        window.clearInterval(pollId);
      }
    };
  }, [welcomeState]);

  async function persistGoal(goal) {
    setSelectedGoal(goal);
    try {
      window.localStorage.setItem("welcome_goal_handshake", goal);
    } catch (_error) {
      // ignore localStorage failures
    }

    try {
      await fetch("/api/onboarding/goal", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });
    } catch (_error) {
      // keep local state even if the persistence call fails
    }
  }

  async function queueFirstSync() {
    setWelcomeState("sync_queued");
    setSyncMessage("Building your first coaching view from recent Garmin history.");
    try {
      const response = await fetch("/api/onboarding/first-sync", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal: selectedGoal }),
      });
      if (!response.ok) {
        setWelcomeState("ready_to_sync");
        setSyncMessage("Sync could not be queued yet. Please try again.");
        return;
      }
      setStatusPayload(await response.json());
    } catch (_error) {
      setWelcomeState("ready_to_sync");
      setSyncMessage("Sync could not be queued yet. Please try again.");
    }
  }

  const garminLoginHref = useMemo(
    () => `/api/providers/garmin/login?next=${GARMIN_WELCOME_NEXT}`,
    []
  );

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "linear-gradient(180deg, #f7fbff 0%, #edf4f8 100%)",
        color: "#13202c",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <section style={{ maxWidth: "1040px", margin: "0 auto", padding: "3.5rem 1.5rem 4rem" }}>
        <div style={{ marginBottom: "2rem" }}>
          <div style={{ fontWeight: 800, letterSpacing: "0.06em", fontSize: "0.95rem" }}>
            FITNESS PALS
          </div>
          <h1 style={{ fontSize: "clamp(2.4rem, 6vw, 4.4rem)", lineHeight: 0.98, margin: "0.85rem 0 0" }}>
            Welcome to the real onboarding path.
          </h1>
          <p style={{ marginTop: "1rem", maxWidth: "60ch", color: "#526472", lineHeight: 1.75 }}>
            This flow takes you from login to provider connection to first value. The goal is to get
            you from account creation to useful coaching context without dumping you into a dead end.
          </p>
        </div>

        {welcomeState === "bootstrapping" && (
          <div style={panelStyle()}>
            <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Loading your onboarding state</h2>
            <p style={{ marginTop: "0.9rem", color: "#526472" }}>
              Checking your session, Garmin connection, and first-sync status.
            </p>
          </div>
        )}

        {welcomeState === "unauthenticated" && (
          <div style={panelStyle()}>
            <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Continue with Gmail</h2>
            <p style={{ marginTop: "0.9rem", color: "#526472", lineHeight: 1.7 }}>
              Use the Fitness Pals sign-in screen and choose Gmail before the welcome flow can continue.
            </p>
            <div style={{ display: "flex", gap: "0.9rem", marginTop: "1rem", flexWrap: "wrap" }}>
              <a
                href="/auth/login?next=/welcome"
                style={{
                  textDecoration: "none",
                  background: "#0d5a55",
                  color: "#fff",
                  padding: "0.95rem 1.3rem",
                  borderRadius: "999px",
                  fontWeight: 800,
                }}
              >
                Continue with Gmail
              </a>
              <a
                href="/"
                style={{
                  textDecoration: "none",
                  border: "1px solid #c7d5df",
                  padding: "0.95rem 1.3rem",
                  borderRadius: "999px",
                  color: "#13202c",
                  fontWeight: 700,
                  background: "#fff",
                }}
              >
                Back to homepage
              </a>
            </div>
          </div>
        )}

        {welcomeState === "connect_garmin" && (
          <div style={{ display: "grid", gap: "1rem" }}>
            <div style={panelStyle()}>
              <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Connect Garmin</h2>
              <p style={{ marginTop: "0.9rem", color: "#526472", lineHeight: 1.7 }}>
                Use Garmin to import training, recovery, and race-build context automatically.
              </p>
              <div style={{ display: "flex", gap: "0.9rem", marginTop: "1rem", flexWrap: "wrap" }}>
                <a
                  href={garminLoginHref}
                  style={{
                    textDecoration: "none",
                    background: "#0d5a55",
                    color: "#fff",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    fontWeight: 800,
                  }}
                >
                  Connect Garmin
                </a>
                <a
                  href="/#trust"
                  style={{
                    textDecoration: "none",
                    border: "1px solid #c7d5df",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    color: "#13202c",
                    fontWeight: 700,
                    background: "#fff",
                  }}
                >
                  Why Garmin?
                </a>
                <a
                  href={GARMIN_EXPORT_IMPORT_HREF}
                  style={{
                    textDecoration: "none",
                    border: "1px solid #c7d5df",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    color: "#13202c",
                    fontWeight: 700,
                    background: "#fff",
                  }}
                >
                  Import Garmin export zip instead
                </a>
              </div>
            </div>
            <GoalHandshake selectedGoal={selectedGoal} onSelect={persistGoal} />
          </div>
        )}

        {welcomeState === "ready_to_sync" && (
          <div style={{ display: "grid", gap: "1rem" }}>
            <GoalHandshake selectedGoal={selectedGoal} onSelect={persistGoal} />
            <div style={panelStyle()}>
              <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Import my training history</h2>
              <p style={{ marginTop: "0.9rem", color: "#526472", lineHeight: 1.7 }}>
                Your Garmin account is connected. Queue the first sync to turn that data into a
                useful coaching view.
              </p>
              <div style={{ display: "flex", gap: "0.9rem", marginTop: "1rem", flexWrap: "wrap" }}>
                <button
                  type="button"
                  onClick={queueFirstSync}
                  style={{
                    border: 0,
                    background: "#0d5a55",
                    color: "#fff",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    fontWeight: 800,
                    cursor: "pointer",
                  }}
                >
                  Import my training history
                </button>
                <a
                  href="/#how-it-works"
                  style={{
                    textDecoration: "none",
                    border: "1px solid #c7d5df",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    color: "#13202c",
                    fontWeight: 700,
                    background: "#fff",
                  }}
                >
                  What sync includes
                </a>
                <a
                  href={GARMIN_EXPORT_IMPORT_HREF}
                  style={{
                    textDecoration: "none",
                    border: "1px solid #c7d5df",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    color: "#13202c",
                    fontWeight: 700,
                    background: "#fff",
                  }}
                >
                  Import Garmin export zip instead
                </a>
              </div>
            </div>
          </div>
        )}

        {welcomeState === "sync_queued" && (
          <div style={{ display: "grid", gap: "1rem" }}>
            <GoalHandshake selectedGoal={selectedGoal} onSelect={persistGoal} disabled />
            <div style={panelStyle()}>
              <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Sync in progress</h2>
              <p style={{ marginTop: "0.9rem", color: "#526472", lineHeight: 1.7 }}>
                {syncMessage || "Your Garmin sync is queued. We are building context for your goal now."}
              </p>
            </div>
          </div>
        )}

        {welcomeState === "synced" && (
          <div style={{ display: "grid", gap: "1rem" }}>
            <div style={panelStyle()}>
              <h2 style={{ margin: 0, fontSize: "1.6rem" }}>First win</h2>
              <p style={{ marginTop: "0.9rem", color: "#526472", lineHeight: 1.7 }}>
                Here is your first value: the latest 5 activities and a readiness preview based on
                the data already synced.
              </p>
              <div style={{ display: "flex", gap: "0.9rem", marginTop: "1rem", flexWrap: "wrap" }}>
                <a
                  href="/dashboard"
                  style={{
                    textDecoration: "none",
                    background: "#0d5a55",
                    color: "#fff",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    fontWeight: 800,
                  }}
                >
                  Open dashboard
                </a>
                <a
                  href="/dashboard#readiness"
                  style={{
                    textDecoration: "none",
                    border: "1px solid #c7d5df",
                    padding: "0.95rem 1.3rem",
                    borderRadius: "999px",
                    color: "#13202c",
                    fontWeight: 700,
                    background: "#fff",
                  }}
                >
                  See my latest readiness
                </a>
              </div>
            </div>

            <div style={panelStyle()}>
              <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Latest 5 activities</h2>
              {latestActivities.length === 0 ? (
                <p style={{ marginTop: "0.9rem", color: "#526472" }}>
                  Latest activities will appear here as soon as sync data is available.
                </p>
              ) : (
                <ul style={{ margin: "1rem 0 0", paddingLeft: "1.2rem", lineHeight: 1.8, color: "#334756" }}>
                  {latestActivities.map((activity) => (
                    <li key={activity.id}>
                      {activity.sport || "activity"} on {new Date(activity.start_time).toLocaleString()}
                    </li>
                  ))}
                </ul>
              )}
            </div>

                <div style={panelStyle()}>
                  <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Readiness preview</h2>
                  {readinessPreview ? (
                <>
                  <div style={{ marginTop: "0.9rem", fontSize: "2rem", fontWeight: 800 }}>
                    {readinessPreview.score}
                  </div>
                  <div style={{ marginTop: "0.4rem", fontWeight: 700 }}>{readinessPreview.label}</div>
                  <p style={{ marginTop: "0.9rem", color: "#526472", lineHeight: 1.7 }}>
                    {readinessPreview.summary}
                  </p>
                </>
              ) : (
                <p style={{ marginTop: "0.9rem", color: "#526472" }}>
                  Readiness preview coming next as more history is processed.
                    </p>
                  )}
                </div>

                <div style={panelStyle()}>
                  <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Coach insight</h2>
                  {coachInsight ? (
                    <>
                      <div style={{ marginTop: "0.9rem", fontWeight: 800, fontSize: "1.1rem" }}>
                        {coachInsight.title}
                      </div>
                      <p style={{ marginTop: "0.85rem", color: "#526472", lineHeight: 1.7 }}>
                        {coachInsight.explanation}
                      </p>
                    </>
                  ) : (
                    <p style={{ marginTop: "0.9rem", color: "#526472" }}>
                      Coach insight will appear here as soon as enough synced history is available.
                    </p>
                  )}
                </div>

                <div style={panelStyle()}>
                  <h2 style={{ margin: 0, fontSize: "1.6rem" }}>Next action</h2>
                  {nextAction ? (
                    <>
                      <div style={{ marginTop: "0.9rem", fontWeight: 800, fontSize: "1.1rem" }}>
                        {nextAction.label}
                      </div>
                      <p style={{ marginTop: "0.85rem", color: "#526472", lineHeight: 1.7 }}>
                        {nextAction.description}
                      </p>
                      <a
                        href={nextAction.href}
                        style={{
                          display: "inline-block",
                          marginTop: "1rem",
                          textDecoration: "none",
                          background: "#0d5a55",
                          color: "#fff",
                          padding: "0.85rem 1.15rem",
                          borderRadius: "999px",
                          fontWeight: 800,
                        }}
                      >
                        Open my dashboard
                      </a>
                    </>
                  ) : (
                    <p style={{ marginTop: "0.9rem", color: "#526472" }}>
                      Next action will appear here once the first synced pattern is ready.
                    </p>
                  )}
                </div>
              </div>
            )}
          </section>
        </main>
      );
}
