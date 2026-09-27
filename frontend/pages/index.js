import { useEffect, useState } from "react";
import { authenticatedFetch } from "../lib/authFetch.mjs";
import styles from "../styles/ElectricEntry.module.css";

const HERO_DOSSIER_URL =
  "https://fitness-pals.com/reports/urban-feet-coach-dossier-third-edition-2026-04-05.html";
const DEFAULT_AUTH_NEXT = "/today";
const AUTH_WELCOME_HREF = `/auth/login?next=${encodeURIComponent(DEFAULT_AUTH_NEXT)}`;

function isSafeNextPath(candidate) {
  return Boolean(candidate && candidate.startsWith("/") && !candidate.startsWith("//") && !candidate.includes("\\") && !/%5c/i.test(candidate));
}

function authLoginHref(nextPath = DEFAULT_AUTH_NEXT) {
  return `/auth/login?next=${encodeURIComponent(nextPath)}`;
}

function resolveAuthNextFromLocation(defaultPath = DEFAULT_AUTH_NEXT) {
  if (typeof window === "undefined") return defaultPath;
  try {
    const requestedNext = new URLSearchParams(window.location.search).get("next");
    return isSafeNextPath(requestedNext) ? requestedNext : defaultPath;
  } catch (_error) {
    return defaultPath;
  }
}

function CtaSkeleton({ compact = false }) {
  return <span className={compact ? styles.skeletonCompact : styles.skeleton} aria-hidden="true" />;
}

function HeroCtas({ state, authHref }) {
  if (state === "loading" || state === "checkingOnboarding") return <CtaSkeleton />;
  if (state === "activationNeeded") return <><a className={styles.primary} href="/welcome?first=1">Start with my goal</a><a className={styles.secondary} href="#trust">How your data is used</a></>;
  if (state === "importing") return <><a className={styles.primary} href="/welcome?first=1">See activation progress</a><a className={styles.secondary} href="#how-it-works">What happens next</a></>;
  if (state === "synced") return <><a className={styles.primary} href="/today">Open Today</a><a className={styles.secondary} href="#trust">How your data is used</a></>;
  return <><a className={styles.primary} href={authHref}>Continue with Gmail</a><a className={styles.secondary} href={HERO_DOSSIER_URL}>View sample coach dossier</a></>;
}

function NavCtas({ state, authHref }) {
  if (state === "loading" || state === "checkingOnboarding") return <CtaSkeleton compact />;
  const href = state === "synced" ? "/today" : state === "anonymous" ? authHref : "/welcome?first=1";
  const label = state === "synced" ? "Open Today" : state === "anonymous" ? "Sign in" : state === "importing" ? "Activation progress" : "Start with my goal";
  return <a className={styles.navAction} href={href}>{label}</a>;
}

export default function Home() {
  const [sessionState, setSessionState] = useState("loading");
  const [authWelcomeHref, setAuthWelcomeHref] = useState(AUTH_WELCOME_HREF);

  useEffect(() => setAuthWelcomeHref(authLoginHref(resolveAuthNextFromLocation())), []);

  useEffect(() => {
    let active = true;
    async function resolveSessionState() {
      try {
        const sessionResponse = await authenticatedFetch("/api/auth/session", { credentials: "include" });
        if (!active) return;
        if (!sessionResponse.ok) return setSessionState("anonymous");
        setSessionState("checkingOnboarding");
        const onboardingResponse = await authenticatedFetch("/api/onboarding/status", { credentials: "include" });
        if (!active) return;
        if (!onboardingResponse.ok) return setSessionState("activationNeeded");
        const { activation } = await onboardingResponse.json();
        if (!active) return;
        if (activation?.requires_activation === false) return setSessionState("synced");
        if (activation?.state === "importing") return setSessionState("importing");
        setSessionState("activationNeeded");
      } catch (_error) {
        if (active) setSessionState("anonymous");
      }
    }
    resolveSessionState();
    return () => { active = false; };
  }, []);

  return (
    <main className={styles.page}>
      <section className={styles.hero}>
        <header className={styles.nav}>
          <a className={styles.wordmark} href="/" aria-label="Fitness Pals home">FITNESS <span>PALS</span></a>
          <div className={styles.navRight}>
            <span className={styles.coachPulse}><i aria-hidden="true" /> Amanda · coach online</span>
            <NavCtas state={sessionState} authHref={authWelcomeHref} />
          </div>
        </header>

        <div className={styles.heroGrid}>
          <div className={styles.heroCopy}>
            <p className={styles.kicker}>TRAINING INTELLIGENCE · BUILT AROUND YOU</p>
            <h1>Build the body.<br/><em>Read the signal.</em></h1>
            <p className={styles.lede}>Your workouts are only half the story. Fitness Pals connects load, recovery, sleep and ambition, then turns the full picture into the next move.</p>
            <div className={styles.ctas}><HeroCtas state={sessionState} authHref={authWelcomeHref} /></div>
            <p className={styles.microcopy}>Secure app sign-in · Garmin-backed training history · You stay in control</p>
          </div>

          <div className={styles.athleteStage} aria-label="Two adult runners in motion, representing strength, speed and focused training">
            <img src="/electric-form/electric-entry-athletes.svg" alt="Stylized adult woman and man running under sculptural stadium light" />
            <div className={styles.signalCard}>
              <span>READINESS</span><strong>74</strong><small>Load is building. Recovery still has room.</small>
            </div>
            <div className={styles.motionLabel}>FORM / LOAD / RECOVERY</div>
          </div>
        </div>

        <a className={styles.scrollCue} href="#how-it-works">See the system <span aria-hidden="true">↓</span></a>
      </section>

      <section className={styles.manifesto} id="how-it-works">
        <p className={styles.kicker}>ONE ATHLETE. ONE SIGNAL.</p>
        <h2>Stop training from fragments.</h2>
        <div className={styles.steps}>
          {[
            ["01", "Declare the target", "Give Coach the race, habit or outcome that matters now."],
            ["02", "Bring the evidence", "Connect the training history already living in Garmin."],
            ["03", "Read the whole athlete", "Load, sleep, recovery and consistency become one usable picture."],
            ["04", "Make the next move", "Amanda turns evidence into a decision and tells you why it changed."],
          ].map(([n,t,b]) => <article key={n}><span>{n}</span><h3>{t}</h3><p>{b}</p></article>)}
        </div>
      </section>

      <section className={styles.coachSection}>
        <div>
          <p className={styles.kicker}>AMANDA · COACH PRESENCE</p>
          <h2>Calm voice.<br/>Sharp signal.</h2>
        </div>
        <blockquote>“You bring the ambition. I’ll keep the evidence in the room.”<footer>Visual guidance first. Voice never autoplays.</footer></blockquote>
      </section>

      <section className={styles.explainability} id="explainability-preview">
        <p className={styles.kicker}>EXPLAINABILITY PREVIEW</p>
        <div className={styles.explainGrid}>
          <h2>Why this plan would change</h2>
          <p>Sleep dropped, long-run load spiked, and recovery compressed. The smarter move is to reduce intensity before momentum turns into fatigue.</p>
        </div>
      </section>

      <section className={styles.proof} id="proof">
        <p className={styles.kicker}>PUBLIC PROOF · NOT VAGUE CLAIMS</p>
        <div className={styles.proofGrid}>
          <article><strong>Sample readiness summary</strong><span>See how current load becomes a readable readiness signal.</span></article>
          <article><strong>Sample training pattern insight</strong><span>See how recent training translates into one next decision.</span></article>
        </div>
      </section>

      <section className={styles.trust} id="trust">
        <div><p className={styles.kicker}>CONTROL WITHOUT FRICTION</p><h2>Your data should work as hard as you do.</h2></div>
        <div className={styles.trustGrid}>
          <article><strong>Revocable</strong><p>Disconnect Garmin or revoke access anytime.</p></article>
          <article><strong>Explainable</strong><p>Coaching shows the evidence behind a changed recommendation.</p></article>
          <article><strong>Session-safe</strong><p>Your product session uses app cookies, not provider tokens.</p></article>
        </div>
      </section>

      <footer className={styles.footer}><span>FITNESS PALS · ELECTRIC FORM</span><a href="/privacy">Privacy Policy</a></footer>
    </main>
  );
}
