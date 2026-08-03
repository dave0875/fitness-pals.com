import { useEffect, useState } from "react";
import axios from "axios";
import { useRouter } from "next/router";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import styles from "../styles/Journey.module.css";

const JOURNEY_API = "/api/journey";

const WINDOWS = [
  ["30d", "30 days"],
  ["90d", "90 days"],
  ["365d", "1 year"],
  ["all", "All available history"],
];
const SPORTS = [
  ["all", "All sports"],
  ["run", "Running"],
  ["bike", "Cycling"],
  ["walk", "Walking"],
  ["strength", "Strength"],
];

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatDistance(meters) {
  if (meters === null || meters === undefined) return "Unknown";
  return `${(meters / 1609.344).toFixed(1)} mi`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "Unknown";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function queryValue(value, allowed, fallback) {
  return typeof value === "string" && allowed.includes(value) ? value : fallback;
}

function goalQueryValue(value) {
  return typeof value === "string" && /^[a-zA-Z0-9_-]{1,40}$/.test(value)
    ? value.toLowerCase()
    : "all";
}

export default function Journey() {
  const router = useRouter();
  const [journey, setJourney] = useState(null);
  const [viewState, setViewState] = useState("loading");
  const [windowValue, setWindowValue] = useState("90d");
  const [sportValue, setSportValue] = useState("all");
  const [goalValue, setGoalValue] = useState("all");

  useEffect(() => {
    if (!router.isReady) return;
    const selectedWindow = queryValue(
      router.query.window,
      WINDOWS.map(([value]) => value),
      "90d"
    );
    const selectedSport = queryValue(
      router.query.sport,
      SPORTS.map(([value]) => value),
      "all"
    );
    const selectedGoal = goalQueryValue(router.query.goal);
    setWindowValue(selectedWindow);
    setSportValue(selectedSport);
    setGoalValue(selectedGoal);
    setViewState("loading");

    const params = new URLSearchParams({
      window: selectedWindow,
      sport: selectedSport,
      goal: selectedGoal,
    });
    axios.get(`${JOURNEY_API}?${params.toString()}`)
      .then((response) => {
        setJourney(response.data);
        setViewState("ready");
      })
      .catch((error) => {
        setJourney(null);
        setViewState(error.response?.status === 401 ? "unauthenticated" : "error");
      });
  }, [router.isReady, router.query.window, router.query.sport, router.query.goal]);

  function applyFilters(event) {
    event.preventDefault();
    router.replace({
      pathname: "/journey",
      query: { window: windowValue, sport: sportValue, goal: goalValue },
    });
  }

  const filterQuery = `window=${encodeURIComponent(windowValue)}&sport=${encodeURIComponent(sportValue)}&goal=${encodeURIComponent(goalValue)}`;

  return (
    <AuthenticatedShell active="journey">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your history</p>
        <h1>Your fitness journey</h1>
        <p>
          Review the work you completed, how consistently it accumulated, and which
          recovery signals are still missing.
        </p>
        {journey?.goal && (
          <span className={styles.goalPill}>Current focus: {journey.goal.label}</span>
        )}
      </header>

      <form className={styles.filters} onSubmit={applyFilters} aria-label="Journey filters">
        <label>
          Time window
          <select
            name="window"
            value={windowValue}
            onChange={(event) => setWindowValue(event.target.value)}
          >
            {WINDOWS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          Sport
          <select
            name="sport"
            value={sportValue}
            onChange={(event) => setSportValue(event.target.value)}
          >
            {SPORTS.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        <label>
          Goal period
          <select
            name="goal"
            value={goalValue}
            onChange={(event) => setGoalValue(event.target.value)}
          >
            <option value="all">All recorded goals</option>
            {(journey?.available_goals || []).map((goalOption) => (
              <option key={goalOption.key} value={goalOption.key}>
                {goalOption.label} ({goalOption.activity_count})
              </option>
            ))}
          </select>
        </label>
        <button type="submit">Apply filters</button>
      </form>

      {viewState === "loading" && (
        <div className={styles.statePanel} role="status">
          <strong>Loading your journey</strong>
          <p>Reconciling your selected canonical activities…</p>
        </div>
      )}
      {viewState === "unauthenticated" && (
        <StatusNotice tone="warning">
          Your session has ended. <a href="/auth/login?next=%2Fjourney">Sign in to continue</a>.
        </StatusNotice>
      )}
      {viewState === "error" && (
        <div className={styles.statePanel} role="alert">
          <strong>Your journey could not be loaded</strong>
          <p>Your saved fitness history has not been changed.</p>
        </div>
      )}

      {viewState === "ready" && journey && (
        <>
          <div className={styles.freshness}>
            <StatusNotice tone={journey.freshness.state === "fresh" ? "success" : "warning"}>
              {journey.freshness.state === "stale"
                ? "This window needs a data refresh"
                : journey.freshness.state === "partial"
                  ? "Some journey signals are still unknown"
                  : journey.freshness.state === "empty"
                    ? "No data is available in this window"
                    : "Journey data is current"}
            </StatusNotice>
            <span>
              Data through {formatDate(journey.freshness.data_through)}
            </span>
          </div>

          <section className={styles.summaryGrid} aria-label="Selected journey totals">
            <article>
              <span>Activities</span>
              <strong>{journey.totals.activity_count}</strong>
            </article>
            <article>
              <span>Distance</span>
              <strong>{formatDistance(journey.totals.distance_m)}</strong>
            </article>
            <article>
              <span>Training time</span>
              <strong>{formatDuration(journey.totals.duration_seconds)}</strong>
            </article>
            <article>
              <span>Active days</span>
              <strong>{journey.totals.active_days}</strong>
            </article>
          </section>

          {journey.totals.intensity_distribution === null && (
            <StatusNotice tone="neutral">
              Intensity distribution is unknown for this window.
            </StatusNotice>
          )}

          {journey.totals.intensity_distribution !== null && (
            <section className={styles.card} aria-label="Intensity distribution">
              <div className={styles.sectionHeading}>
                <div>
                  <p className={styles.eyebrow}>Training balance</p>
                  <h2>Intensity distribution</h2>
                </div>
              </div>
              <div className={styles.intensityGrid}>
                {Object.entries(journey.totals.intensity_distribution).map(
                  ([intensity, count]) => (
                    <div key={intensity}>
                      <span>{intensity}</span>
                      <strong>{count}</strong>
                    </div>
                  )
                )}
              </div>
            </section>
          )}

          <div className={styles.columns}>
            <section className={styles.card}>
              <h2>Weekly timeline</h2>
              {journey.weekly_summaries.length === 0 ? (
                <p>No weekly training appears in this window.</p>
              ) : (
                <ol className={styles.timeline}>
                  {journey.weekly_summaries.map((week) => (
                    <li key={week.period_start}>
                      <div>
                        <strong>Week of {formatDate(week.period_start)}</strong>
                        <span>{week.activity_count} activities · {week.active_days} active days</span>
                      </div>
                      <div>
                        <strong>{formatDistance(week.distance_m)}</strong>
                        <span>
                          Sleep {week.average_sleep_hours === null
                            ? "unknown"
                            : `${week.average_sleep_hours}h average`}
                        </span>
                      </div>
                    </li>
                  ))}
                </ol>
              )}
            </section>

            <section className={styles.card}>
              <h2>Monthly summary</h2>
              {journey.monthly_summaries.length === 0 ? (
                <p>No monthly training appears in this window.</p>
              ) : (
                <ol className={styles.timeline}>
                  {journey.monthly_summaries.map((month) => (
                    <li key={month.period_start}>
                      <div>
                        <strong>{formatDate(month.period_start)}</strong>
                        <span>{month.activity_count} activities</span>
                      </div>
                      <strong>{formatDistance(month.distance_m)}</strong>
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </div>

          <section className={styles.card}>
            <h2>Milestones in this window</h2>
            {journey.milestones.length === 0 ? (
              <p>Milestones will appear when the selected window contains activities.</p>
            ) : (
              <ul className={styles.milestones}>
                {journey.milestones.map((milestone) => (
                  <li key={milestone.kind}>
                    <strong>{milestone.label}</strong>
                    <span>{formatDistance(milestone.distance_m)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className={styles.handoff}>
            <div>
              <p className={styles.eyebrow}>Coaching context</p>
              <h2>Carry this window into your dossier</h2>
              <p>
                This link preserves the selected time, sport, and recorded goal period.
                The request stays inside your signed-in coaching flow.
              </p>
            </div>
            <a href={journey.dossier_handoff.href}>
              {journey.dossier_handoff.label}
            </a>
          </section>

          <StatusNotice tone="neutral">
            {journey.goal_attribution.unattributed_count > 0
              ? `${journey.goal_attribution.unattributed_count} activit${journey.goal_attribution.unattributed_count === 1 ? "y is" : "ies are"} older than your first recorded goal and remain unattributed.`
              : "Every activity in this window has a recorded goal period."}
          </StatusNotice>

          <section className={styles.card} id="activities">
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Selected record</p>
                <h2>Activities</h2>
              </div>
              <span>{journey.activities.length} shown</span>
            </div>
            {journey.activities.length === 0 ? (
              <p>No activities match these filters.</p>
            ) : (
              <ol className={styles.activities}>
                {journey.activities.map((activity) => (
                  <li key={activity.id}>
                    <a href={`/activities/${activity.id}?${filterQuery}`}>
                      <div>
                        <strong>{activity.title}</strong>
                        <span>{formatDate(activity.start_time)} · {activity.sport}</span>
                      </div>
                      <span>
                        {formatDistance(activity.distance_m)} · {formatDuration(activity.duration_seconds)}
                      </span>
                    </a>
                  </li>
                ))}
              </ol>
            )}
          </section>

          <p className={styles.boundary}>
            Summaries reconcile to the canonical activities visible for this selected window.
            Missing history and signals remain unknown rather than being treated as zero.
          </p>
        </>
      )}
    </AuthenticatedShell>
  );
}
