import { useEffect, useState } from "react";

const HERO_DOSSIER_URL =
  "https://fitness-pals.com/reports/urban-feet-coach-dossier-third-edition-2026-04-05.html";
const DEFAULT_AUTH_NEXT = "/welcome";
const AUTH_WELCOME_HREF = `/auth/login?next=${encodeURIComponent(DEFAULT_AUTH_NEXT)}`;
const GARMIN_WELCOME_HREF =
  "/api/providers/garmin/login?next=%2Fwelcome%3Fgarmin%3Dconnected";

function isSafeNextPath(candidate) {
  return Boolean(candidate && candidate.startsWith("/") && !candidate.startsWith("//"));
}

function authLoginHref(nextPath = DEFAULT_AUTH_NEXT) {
  return `/auth/login?next=${encodeURIComponent(nextPath)}`;
}

function resolveAuthNextFromLocation(defaultPath = DEFAULT_AUTH_NEXT) {
  if (typeof window === "undefined") {
    return defaultPath;
  }

  try {
    const params = new URLSearchParams(window.location.search);
    const requestedNext = params.get("next");
    return isSafeNextPath(requestedNext) ? requestedNext : defaultPath;
  } catch (_error) {
    return defaultPath;
  }
}

function ctaButtonStyle(kind) {
  if (kind === "primary") {
    return {
      textDecoration: "none",
      background: "#0d5a55",
      color: "#fff",
      padding: "0.95rem 1.3rem",
      borderRadius: "999px",
      fontWeight: 800,
    };
  }
  return {
    textDecoration: "none",
    color: "#13202c",
    padding: "0.95rem 1.3rem",
    borderRadius: "999px",
    border: "1px solid #c7d5df",
    fontWeight: 700,
    background: "#fff",
  };
}

function navButtonStyle(kind) {
  if (kind === "primary") {
    return {
      textDecoration: "none",
      color: "#fff",
      background: "#0d5a55",
      padding: "0.75rem 1rem",
      borderRadius: "999px",
      fontWeight: 700,
    };
  }
  return {
    textDecoration: "none",
    color: "#13202c",
    padding: "0.75rem 1rem",
    borderRadius: "999px",
    border: "1px solid #c7d5df",
    fontWeight: 700,
  };
}

function CtaSkeleton({ compact = false }) {
  const height = compact ? "2.6rem" : "3.2rem";
  const width = compact ? "7.5rem" : "11rem";
  return (
    <>
      {[0, 1].map((index) => (
        <div
          key={index}
          aria-hidden="true"
          style={{
            width,
            height,
            borderRadius: "999px",
            background: "linear-gradient(90deg, #e8eef3 0%, #f5f8fb 50%, #e8eef3 100%)",
            backgroundSize: "200% 100%",
            animation: "2s ease-in-out infinite shimmer",
          }}
        />
      ))}
    </>
  );
}

function renderHeroCtas(sessionState, authWelcomeHref) {
  if (sessionState === "loading" || sessionState === "checkingOnboarding") {
    return <CtaSkeleton />;
  }

  if (sessionState === "authenticatedNoGarmin") {
    return (
      <>
        <a href={GARMIN_WELCOME_HREF} style={ctaButtonStyle("primary")}>
          Connect Garmin
        </a>
        <a href="#trust" style={ctaButtonStyle("secondary")}>
          How your data is used
        </a>
      </>
    );
  }

  if (sessionState === "readyToSync" || sessionState === "syncQueued") {
    return (
      <>
        <a href="/welcome" style={ctaButtonStyle("primary")}>
          Import my training history
        </a>
        <a href="#how-it-works" style={ctaButtonStyle("secondary")}>
          What happens next
        </a>
      </>
    );
  }

  if (sessionState === "synced") {
    return (
      <>
        <a href="/dashboard" style={ctaButtonStyle("primary")}>
          Open dashboard
        </a>
        <a href="#trust" style={ctaButtonStyle("secondary")}>
          How your data is used
        </a>
      </>
    );
  }

  return (
    <>
      <a href={authWelcomeHref} style={ctaButtonStyle("primary")}>
        Continue with Gmail
      </a>
      <a href={HERO_DOSSIER_URL} style={ctaButtonStyle("secondary")}>
        View sample coach dossier
      </a>
      <a
        href="#how-it-works"
        style={{
          ...ctaButtonStyle("secondary"),
          background: "#f8fbff",
        }}
      >
        How it works
      </a>
    </>
  );
}

function renderNavCtas(sessionState, authWelcomeHref) {
  if (sessionState === "loading" || sessionState === "checkingOnboarding") {
    return <CtaSkeleton compact />;
  }

  if (sessionState === "authenticatedNoGarmin") {
    return (
      <>
        <a href={GARMIN_WELCOME_HREF} style={navButtonStyle("primary")}>
          Connect Garmin
        </a>
        <a href={HERO_DOSSIER_URL} style={navButtonStyle("secondary")}>
          View sample coach dossier
        </a>
      </>
    );
  }

  if (sessionState === "readyToSync" || sessionState === "syncQueued") {
    return (
      <>
        <a href="/welcome" style={navButtonStyle("primary")}>
          Import my training history
        </a>
        <a href={HERO_DOSSIER_URL} style={navButtonStyle("secondary")}>
          View sample coach dossier
        </a>
      </>
    );
  }

  if (sessionState === "synced") {
    return (
      <>
        <a href="/dashboard" style={navButtonStyle("primary")}>
          Open dashboard
        </a>
        <a href={HERO_DOSSIER_URL} style={navButtonStyle("secondary")}>
          View sample coach dossier
        </a>
      </>
    );
  }

  return (
    <>
      <a href={authWelcomeHref} style={navButtonStyle("secondary")}>
        Sign in
      </a>
      <a href={HERO_DOSSIER_URL} style={navButtonStyle("secondary")}>
        View sample coach dossier
      </a>
    </>
  );
}

export default function Home() {
  const [sessionState, setSessionState] = useState("loading");
  const [authWelcomeHref, setAuthWelcomeHref] = useState(AUTH_WELCOME_HREF);

  useEffect(() => {
    setAuthWelcomeHref(authLoginHref(resolveAuthNextFromLocation()));
  }, []);

  useEffect(() => {
    let active = true;

    async function resolveSessionState() {
      try {
        const sessionResponse = await fetch("/api/auth/session", {
          credentials: "include",
        });

        if (!active) {
          return;
        }

        if (!sessionResponse.ok) {
          setSessionState("anonymous");
          return;
        }

        setSessionState("checkingOnboarding");

        const onboardingResponse = await fetch("/api/onboarding/status", {
          credentials: "include",
        });

        if (!active) {
          return;
        }

        if (!onboardingResponse.ok) {
          setSessionState("authenticatedNoGarmin");
          return;
        }

        const onboardingStatus = await onboardingResponse.json();
        if (!active) {
          return;
        }

        if (!onboardingStatus.garmin_connected) {
          setSessionState("authenticatedNoGarmin");
          return;
        }

        if (
          onboardingStatus.first_sync?.state === "completed" &&
          onboardingStatus.latest_activities?.length
        ) {
          setSessionState("synced");
          return;
        }

        if (
          onboardingStatus.first_sync?.state === "queued" ||
          onboardingStatus.first_sync?.state === "running"
        ) {
          setSessionState("syncQueued");
          return;
        }

        setSessionState("readyToSync");
      } catch (_error) {
        if (active) {
          setSessionState("anonymous");
        }
      }
    }

    resolveSessionState();
    return () => {
      active = false;
    };
  }, []);

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "linear-gradient(180deg, #f8fbff 0%, #eef5f9 100%)",
        color: "#13202c",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <section
        style={{
          maxWidth: "1040px",
          margin: "0 auto",
          padding: "4rem 1.5rem 3rem",
        }}
      >
        <header
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            gap: "1rem",
            marginBottom: "4rem",
          }}
        >
          <div style={{ fontWeight: 800, letterSpacing: "0.06em", fontSize: "0.95rem" }}>
            FITNESS PALS
          </div>
          <nav style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
            {renderNavCtas(sessionState, authWelcomeHref)}
          </nav>
        </header>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1.4fr) minmax(280px, 0.8fr)",
            gap: "2rem",
            alignItems: "start",
          }}
        >
          <div>
            <div
              style={{
                display: "inline-block",
                marginBottom: "1rem",
                padding: "0.4rem 0.8rem",
                borderRadius: "999px",
                background: "#e5f1f0",
                color: "#0b5f58",
                fontSize: "0.9rem",
                fontWeight: 700,
              }}
                >
                  Built for runners who want more than generic plans
                </div>
            <h1
              style={{
                fontSize: "clamp(2.6rem, 7vw, 4.9rem)",
                lineHeight: 0.96,
                margin: 0,
                maxWidth: "12ch",
              }}
            >
              Train with the full truth of your training.
            </h1>
            <p
              style={{
                marginTop: "1.25rem",
                maxWidth: "58ch",
                fontSize: "1.08rem",
                lineHeight: 1.75,
                color: "#4b5d6b",
              }}
                >
                  Fitness Pals turns workouts, recovery, sleep, and consistency into coaching you can
                  actually use. Continue through Fitness Pals sign-in, choose Gmail, connect Garmin,
                  and start building a training record that can shape better next decisions.
                </p>
                <div
                  style={{
                    display: "flex",
                    gap: "0.9rem",
                    flexWrap: "wrap",
                    marginTop: "1.75rem",
                    minHeight: "3.5rem",
                    alignItems: "center",
                  }}
                >
                  {renderHeroCtas(sessionState, authWelcomeHref)}
                </div>
                <p style={{ marginTop: "1rem", color: "#5a6d7b", fontSize: "0.96rem" }}>
                  Fitness Pals sign-in handles Gmail SSO. Garmin handles training data. Revocable anytime.
                </p>
              </div>

          <aside
            style={{
              background: "#ffffff",
              border: "1px solid #dbe6ed",
              borderRadius: "24px",
              padding: "1.4rem",
              boxShadow: "0 20px 40px rgba(19, 32, 44, 0.08)",
            }}
          >
            <div style={{ fontSize: "0.85rem", textTransform: "uppercase", letterSpacing: "0.12em", color: "#627585", fontWeight: 800 }}>
              What you get back
            </div>
            <ul style={{ margin: "1rem 0 0", paddingLeft: "1.2rem", lineHeight: 1.8, color: "#334756" }}>
              <li>Real connection between load, recovery, and race goals</li>
              <li>Fast onboarding into Garmin-backed coaching data</li>
              <li>Sample artifacts serious enough to share with a coach</li>
            </ul>
          </aside>
        </div>
      </section>

      <section
        id="how-it-works"
        style={{
          maxWidth: "1040px",
          margin: "0 auto",
          padding: "0 1.5rem 4rem",
        }}
      >
        <div
          style={{
            background: "#ffffff",
            border: "1px solid #dbe6ed",
            borderRadius: "28px",
            padding: "1.5rem",
            boxShadow: "0 20px 40px rgba(19, 32, 44, 0.05)",
          }}
        >
          <h2 style={{ margin: 0, fontSize: "1.9rem" }}>How it works</h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
              gap: "1rem",
              marginTop: "1.5rem",
            }}
          >
            {[
              ["1. Sign in", "Use the Fitness Pals sign-in screen and continue with Gmail to create an app-backed session."],
              ["2. Connect Garmin", "Authorize Garmin so your training history can flow in."],
              ["3. Sync your data", "Queue your first import and let the product build context."],
              ["4. Get coaching value", "See readiness, recent activity patterns, and next actions."],
            ].map(([title, body]) => (
              <div
                key={title}
                style={{
                  border: "1px solid #dbe6ed",
                  borderRadius: "20px",
                  padding: "1rem",
                  background: "#f9fcfe",
                }}
              >
                <div style={{ fontWeight: 800, marginBottom: "0.55rem" }}>{title}</div>
                <div style={{ color: "#526472", lineHeight: 1.65 }}>{body}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section
        id="trust"
        style={{
          maxWidth: "1040px",
          margin: "0 auto",
          padding: "0 1.5rem 4rem",
        }}
      >
        <div
          style={{
            background: "#ffffff",
            border: "1px solid #dbe6ed",
            borderRadius: "28px",
            padding: "1.5rem",
            boxShadow: "0 20px 40px rgba(19, 32, 44, 0.05)",
          }}
        >
          <h2 style={{ margin: 0, fontSize: "1.9rem" }}>Why trust this</h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "1rem",
              marginTop: "1.5rem",
            }}
          >
            {[
              ["You stay in control", "Disconnect Garmin or revoke access anytime."],
              ["OAuth-based connection", "The product path uses Garmin auth, not a dead-end setup wall."],
              ["App-session auth", "Your product session uses app cookies, not provider tokens."],
              ["Transparent coaching", "Recommendations should explain what changed and why."],
            ].map(([title, body]) => (
              <div
                key={title}
                style={{
                  border: "1px solid #dbe6ed",
                  borderRadius: "20px",
                  padding: "1rem",
                  background: "#f9fcfe",
                }}
              >
                <div style={{ fontWeight: 800, marginBottom: "0.55rem" }}>{title}</div>
                <div style={{ color: "#526472", lineHeight: 1.65 }}>{body}</div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section
        id="explainability-preview"
        style={{
          maxWidth: "1040px",
          margin: "0 auto",
          padding: "0 1.5rem 4rem",
        }}
      >
        <div
          style={{
            background: "#0f2130",
            color: "#f4f8fb",
            borderRadius: "28px",
            padding: "1.6rem",
            boxShadow: "0 20px 40px rgba(19, 32, 44, 0.12)",
          }}
        >
          <div style={{ fontSize: "0.84rem", textTransform: "uppercase", letterSpacing: "0.12em", color: "#9ec4d9", fontWeight: 800 }}>
            Explainability preview
          </div>
          <h2 style={{ margin: "0.8rem 0 0", fontSize: "1.9rem" }}>Why this plan would change</h2>
          <p style={{ marginTop: "1rem", maxWidth: "62ch", color: "#d8e4eb", lineHeight: 1.75 }}>
            Sleep dropped, long-run load spiked, and recovery compressed. A good coach would reduce
            intensity before momentum turns into fatigue. Fitness Pals should make the same move,
            and it should explain why.
          </p>
        </div>
      </section>

      <section
        id="proof"
        style={{
          maxWidth: "1040px",
          margin: "0 auto",
          padding: "0 1.5rem 4rem",
        }}
      >
        <div
          style={{
            background: "#ffffff",
            border: "1px solid #dbe6ed",
            borderRadius: "28px",
            padding: "1.5rem",
            boxShadow: "0 20px 40px rgba(19, 32, 44, 0.05)",
          }}
        >
          <h2 style={{ margin: 0, fontSize: "1.9rem" }}>Public proof, not vague claims</h2>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: "1rem",
              marginTop: "1.5rem",
            }}
          >
            {[
              [
                "Sample coach dossier",
                "See a serious athlete-facing artifact instead of generic AI copy.",
                HERO_DOSSIER_URL,
              ],
              [
                "Sample readiness summary",
                "See how recent training load becomes a readable readiness signal.",
                "#sample-readiness",
              ],
              [
                "Sample training pattern insight",
                "See how recent activity patterns translate into one next decision.",
                "#sample-pattern-insight",
              ],
            ].map(([title, body, href]) => (
              <div
                key={title}
                style={{
                  border: "1px solid #dbe6ed",
                  borderRadius: "20px",
                  padding: "1rem",
                  background: "#f9fcfe",
                }}
              >
                <div style={{ fontWeight: 800, marginBottom: "0.55rem" }}>{title}</div>
                <div style={{ color: "#526472", lineHeight: 1.65 }}>{body}</div>
                <a
                  href={href}
                  style={{
                    display: "inline-block",
                    marginTop: "1rem",
                    textDecoration: "none",
                    color: "#0b5f58",
                    fontWeight: 800,
                  }}
                >
                  Open artifact
                </a>
              </div>
            ))}
          </div>

          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
              gap: "1rem",
              marginTop: "1.5rem",
            }}
          >
            <div
              id="sample-readiness"
              style={{
                border: "1px solid #dbe6ed",
                borderRadius: "20px",
                padding: "1rem",
                background: "#ffffff",
              }}
            >
              <div style={{ fontWeight: 800 }}>Sample readiness summary</div>
              <div style={{ marginTop: "0.8rem", fontSize: "2rem", fontWeight: 800 }}>74</div>
              <p style={{ marginTop: "0.65rem", color: "#526472", lineHeight: 1.7 }}>
                Recent load is strong enough to build, but not so strong that the next decision should
                ignore recovery.
              </p>
            </div>

            <div
              id="sample-pattern-insight"
              style={{
                border: "1px solid #dbe6ed",
                borderRadius: "20px",
                padding: "1rem",
                background: "#ffffff",
              }}
            >
              <div style={{ fontWeight: 800 }}>Sample training pattern insight</div>
              <p style={{ marginTop: "0.8rem", color: "#526472", lineHeight: 1.7 }}>
                Your last long effort landed close to two shorter quality days. The better move is to
                keep the next run easy so the block stays intact.
              </p>
            </div>
          </div>
        </div>
      </section>

      <style jsx global>{`
        @keyframes shimmer {
          0% {
            background-position: 200% 0;
          }
          100% {
            background-position: -200% 0;
          }
        }
      `}</style>
    </main>
  );
}
