import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/router";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import AthleteOrbitStory from "../components/AthleteOrbitStory";
import { authenticatedJson } from "../lib/authFetch.mjs";
import styles from "../styles/Journey.module.css";

const JOURNEY_API = "/api/journey";
const ACTIVITY_PAGE_SIZE = 25;
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
  if (!value) return "Unavailable";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatDistance(meters) {
  if (meters === null || meters === undefined) return "Unavailable";
  return `${(meters / 1609.344).toFixed(1)} mi`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "Unavailable";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

function formatPercent(value) {
  if (value === null || value === undefined) return "Not comparable";
  if (value === 0) return "No change";
  return `${value > 0 ? "+" : ""}${value}%`;
}

function queryValue(value, allowed, fallback) {
  return typeof value === "string" && allowed.includes(value) ? value : fallback;
}

function goalQueryValue(value) {
  return typeof value === "string" && /^[a-zA-Z0-9_-]{1,40}$/.test(value)
    ? value.toLowerCase()
    : "all";
}

function pageQueryValue(value) {
  const parsed = Number.parseInt(typeof value === "string" ? value : "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export default function Journey() {
  const router = useRouter();
  const [journey, setJourney] = useState(null);
  const [viewState, setViewState] = useState("loading");
  const [windowValue, setWindowValue] = useState("90d");
  const [sportValue, setSportValue] = useState("all");
  const [goalValue, setGoalValue] = useState("all");

  const selectedPage = pageQueryValue(router.query.page);

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
    const activityPage = pageQueryValue(router.query.page);
    setWindowValue(selectedWindow);
    setSportValue(selectedSport);
    setGoalValue(selectedGoal);
    setViewState("loading");

    const params = new URLSearchParams({
      window: selectedWindow,
      sport: selectedSport,
      goal: selectedGoal,
      activity_page: String(activityPage),
      activity_page_size: String(ACTIVITY_PAGE_SIZE),
    });
    authenticatedJson(`${JOURNEY_API}?${params.toString()}`)
      .then((data) => {
        setJourney(data);
        setViewState("ready");
      })
      .catch((error) => {
        setJourney(null);
        setViewState(error.status === 401 ? "unauthenticated" : "error");
      });
  }, [
    router.isReady,
    router.query.window,
    router.query.sport,
    router.query.goal,
    router.query.page,
  ]);

  function applyFilters(event) {
    event.preventDefault();
    router.replace({
      pathname: "/progress",
      query: { window: windowValue, sport: sportValue, goal: goalValue, page: 1 },
    });
  }

  function changePage(page) {
    router.replace({
      pathname: "/progress",
      query: {
        window: journey.filters.window,
        sport: journey.filters.sport,
        goal: journey.filters.goal,
        page,
      },
    });
  }

  const appliedFilters = journey?.filters || {
    window: windowValue,
    sport: sportValue,
    goal: goalValue,
  };
  const filterQuery = useMemo(() => {
    const params = new URLSearchParams({
      window: appliedFilters.window,
      sport: appliedFilters.sport,
      goal: appliedFilters.goal,
      page: String(selectedPage),
    });
    return params.toString();
  }, [appliedFilters.goal, appliedFilters.sport, appliedFilters.window, selectedPage]);

  const coachHref = useMemo(() => {
    const params = new URLSearchParams({
      from: router.asPath || "/progress",
      window: appliedFilters.window,
      sport: appliedFilters.sport,
      goal: appliedFilters.goal,
      label: "Selected Progress window",
    });
    return `/coach?${params.toString()}`;
  }, [appliedFilters.goal, appliedFilters.sport, appliedFilters.window, router.asPath]);

  const appliedWindow = WINDOWS.find(
    ([value]) => value === journey?.filters?.window
  )?.[1] || journey?.filters?.window;
  const appliedSport = SPORTS.find(
    ([value]) => value === journey?.filters?.sport
  )?.[1] || journey?.filters?.sport;
  const pagination = journey?.activity_pagination;

  return (
    <AuthenticatedShell active="progress">
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>Your progress</p>
          <h1>Progress through your own history</h1>
          <p>
            Compare the work you completed with your own prior training, then open
            the exact activities behind the story.
          </p>
        </div>
        {journey?.goal && (
          <span className={styles.goalPill}>Current focus: {journey.goal.label}</span>
        )}
      </header>

      {viewState !== "unauthenticated" && viewState !== "error" && (
        <AthleteOrbitStory decision={journey?.decision} surface="Progress" />
      )}

      <form className={styles.filters} onSubmit={applyFilters} aria-label="Progress filters">
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

      {viewState === "ready" && journey && (
        <p className={styles.appliedFilters} role="status">
          <strong>Applied filters:</strong> {appliedWindow} · {appliedSport} ·{" "}
          {journey.filters.goal === "all" ? "All recorded goals" : journey.filters.goal}
        </p>
      )}

      {viewState === "loading" && (
        <div className={styles.statePanel} role="status">
          <strong>Loading Progress</strong>
          <p>Reconciling your selected canonical evidence…</p>
        </div>
      )}
      {viewState === "unauthenticated" && (
        <StatusNotice tone="warning">
          Your session has ended. <a href="/auth/login?next=%2Fprogress">Sign in to continue</a>.
        </StatusNotice>
      )}
      {viewState === "error" && (
        <div className={styles.statePanel} role="alert">
          <strong>Progress could not be loaded</strong>
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
                  ? "Some Progress signals are missing or stale"
                  : journey.freshness.state === "empty"
                    ? "No data is available in this window"
                    : "Progress data is current"}
            </StatusNotice>
            <span>Data through {formatDate(journey.freshness.data_through)}</span>
            <span>
              Workouts: {journey.freshness.signals.activities.state}. Sleep:{" "}
              {journey.freshness.signals.sleep.state}. Intensity:{" "}
              {journey.freshness.signals.intensity.state}.
            </span>
          </div>

          <section className={styles.summaryGrid} aria-label="Selected Progress totals">
            <article><span>Activities</span><strong>{journey.totals.activity_count}</strong></article>
            <article><span>Distance</span><strong>{formatDistance(journey.totals.distance_m)}</strong></article>
            <article><span>Training time</span><strong>{formatDuration(journey.totals.duration_seconds)}</strong></article>
            <article><span>Active days</span><strong>{journey.totals.active_days}</strong></article>
          </section>

          <section className={styles.card} aria-label="Athlete-to-self comparison">
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Athlete-to-self</p>
                <h2>How this window compares with you</h2>
              </div>
              <span>{journey.comparison.basis}</span>
            </div>
            {journey.comparison.state === "available" ? (
              <div className={styles.summaryGrid}>
                <article>
                  <span>Distance change</span>
                  <strong>{formatPercent(journey.comparison.changes.distance_percent)}</strong>
                </article>
                <article>
                  <span>Training-time change</span>
                  <strong>{formatPercent(journey.comparison.changes.duration_percent)}</strong>
                </article>
                <article>
                  <span>Activity-count change</span>
                  <strong>{formatPercent(journey.comparison.changes.activity_count_percent)}</strong>
                </article>
                <article>
                  <span>Active-day change</span>
                  <strong>{formatPercent(journey.comparison.changes.active_days_percent)}</strong>
                </article>
              </div>
            ) : (
              <p>{journey.comparison.basis}</p>
            )}
            <p className={styles.boundary}>
              This is a direct comparison with the immediately preceding equal window,
              not a readiness score or prediction.
            </p>
          </section>

          {journey.totals.intensity_distribution === null ? (
            <StatusNotice tone="neutral">
              Intensity distribution is unavailable for this window.
            </StatusNotice>
          ) : (
            <section className={styles.card} aria-label="Intensity distribution">
              <div className={styles.sectionHeading}>
                <div><p className={styles.eyebrow}>Training balance</p><h2>Intensity distribution</h2></div>
              </div>
              <div className={styles.intensityGrid}>
                {Object.entries(journey.totals.intensity_distribution).map(([intensity, count]) => (
                  <div key={intensity}><span>{intensity}</span><strong>{count}</strong></div>
                ))}
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
                            ? "unavailable"
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

          <section className={styles.handoff}>
            <div>
              <p className={styles.eyebrow}>Coaching context</p>
              <h2>Ask Coach about this window</h2>
              <p>Carry these exact filters and this evidence window into your durable Coach thread.</p>
            </div>
            <a href={coachHref}>Ask Coach about this window</a>
          </section>

          <section className={styles.handoff}>
            <div>
              <p className={styles.eyebrow}>Saved analysis</p>
              <h2>Go deeper without losing this selection</h2>
              <p>
                Create or revisit an immutable deeper analysis using the same window,
                sport, and recorded goal period.
              </p>
            </div>
            <a href={journey.dossier_handoff.href}>{journey.dossier_handoff.label}</a>
          </section>

          <StatusNotice tone="neutral">
            {journey.goal_attribution.unattributed_count > 0
              ? `${journey.goal_attribution.unattributed_count} activit${journey.goal_attribution.unattributed_count === 1 ? "y is" : "ies are"} older than your first recorded goal and remain unattributed.`
              : "Every activity in this window has a recorded goal period."}
          </StatusNotice>

          <section className={styles.card} id="activities">
            <div className={styles.sectionHeading}>
              <div><p className={styles.eyebrow}>Selected evidence</p><h2>Activities</h2></div>
              <span>
                {pagination.from}–{pagination.to} of {pagination.total_items} shown
              </span>
            </div>
            {pagination.total_items === 0 ? (
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
                      <span>{formatDistance(activity.distance_m)} · {formatDuration(activity.duration_seconds)}</span>
                    </a>
                  </li>
                ))}
              </ol>
            )}
            {pagination.total_pages > 1 && (
              <nav className={styles.pagination} aria-label="Progress activity pages">
                <button
                  type="button"
                  disabled={pagination.page === 1}
                  onClick={() => changePage(pagination.page - 1)}
                >
                  Previous
                </button>
                <span>Page {pagination.page} of {pagination.total_pages}</span>
                <button
                  type="button"
                  disabled={pagination.page === pagination.total_pages}
                  onClick={() => changePage(pagination.page + 1)}
                >
                  Next
                </button>
              </nav>
            )}
          </section>

          <p className={styles.boundary}>
            Full-window summaries reconcile to the complete canonical selection even
            though activity rows are delivered one bounded page at a time. Missing
            history and signals remain unavailable rather than becoming zero.
          </p>
        </>
      )}
    </AuthenticatedShell>
  );
}
