import { useEffect, useState } from "react";
import { useRouter } from "next/router";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import { authenticatedJson } from "../lib/authFetch.mjs";
import styles from "../styles/Journey.module.css";

const TRAINING_API = "/api/journey";
const PAGE_SIZE = 25;
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
  if (!value) return "Date unavailable";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatDistance(meters) {
  if (meters === null || meters === undefined) return "Distance unavailable";
  return `${(meters / 1609.344).toFixed(1)} mi`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "Duration unavailable";
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

function pageQueryValue(value) {
  const parsed = Number.parseInt(typeof value === "string" ? value : "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

export default function Training() {
  const router = useRouter();
  const [journey, setJourney] = useState(null);
  const [state, setState] = useState("loading");
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
    const selectedPage = pageQueryValue(router.query.page);
    setWindowValue(selectedWindow);
    setSportValue(selectedSport);
    setGoalValue(selectedGoal);
    setState("loading");

    const params = new URLSearchParams({
      window: selectedWindow,
      sport: selectedSport,
      goal: selectedGoal,
      activity_page: String(selectedPage),
      activity_page_size: String(PAGE_SIZE),
    });
    authenticatedJson(`${TRAINING_API}?${params.toString()}`)
      .then((data) => {
        setJourney(data);
        setState("ready");
      })
      .catch((error) => {
        setJourney(null);
        setState(error.status === 401 ? "unauthenticated" : "error");
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
      pathname: "/training",
      query: { window: windowValue, sport: sportValue, goal: goalValue, page: 1 },
    });
  }

  function changePage(page) {
    router.replace({
      pathname: "/training",
      query: {
        window: journey.filters.window,
        sport: journey.filters.sport,
        goal: journey.filters.goal,
        page,
      },
    });
  }

  const pagination = journey?.activity_pagination;

  return (
    <AuthenticatedShell active="training">
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>Your record</p>
          <h1>Training history</h1>
          <p>
            Find the exact workouts behind your coaching decisions without loading
            your entire history into one browser page.
          </p>
        </div>
        <a href="/progress">See trends in Progress</a>
      </header>

      <form className={styles.filters} onSubmit={applyFilters} aria-label="Training filters">
        <label>
          Time window
          <select
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

      {state === "loading" && (
        <div className={styles.statePanel} role="status">
          <strong>Loading your training history</strong>
          <p>Reading the requested page of your canonical activity record…</p>
        </div>
      )}

      {state === "unauthenticated" && (
        <StatusNotice tone="warning">
          Your session ended. <a href="/auth/login?next=%2Ftraining">Sign in to continue</a>.
        </StatusNotice>
      )}

      {state === "error" && (
        <div className={styles.statePanel} role="alert">
          <strong>Training history could not be loaded</strong>
          <p>Your saved activities have not been changed.</p>
        </div>
      )}

      {state === "ready" && journey && pagination && (
        <>
          <div className={styles.freshness}>
            <StatusNotice tone={journey.freshness.state === "fresh" ? "success" : "warning"}>
              {journey.freshness.state === "stale"
                ? "This activity record needs a data refresh"
                : journey.freshness.state === "partial"
                  ? "Some activity signals are missing or stale"
                  : journey.freshness.state === "empty"
                    ? "No activity data is available yet"
                    : "Training data is current"}
            </StatusNotice>
            <span>
              {pagination.total_items} activities match this selection. Only{" "}
              {pagination.page_size} rows are requested at a time.
            </span>
          </div>

          <section className={styles.card}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Canonical activities</p>
                <h2>Activities</h2>
              </div>
              <span>
                {pagination.from}–{pagination.to} of {pagination.total_items} shown
              </span>
            </div>

            {pagination.total_items === 0 ? (
              <p>No activities are available for this selection.</p>
            ) : (
              <ol className={styles.activities}>
                {journey.activities.map((activity) => {
                  const params = new URLSearchParams({
                    window: journey.filters.window,
                    sport: journey.filters.sport,
                    goal: journey.filters.goal,
                    page: String(pagination.page),
                  });
                  return (
                    <li key={activity.id}>
                      <a href={`/activities/${activity.id}?${params.toString()}`}>
                        <div>
                          <strong>{activity.title}</strong>
                          <span>{formatDate(activity.start_time)} · {activity.sport}</span>
                        </div>
                        <span>
                          {formatDistance(activity.distance_m)} · {formatDuration(activity.duration_seconds)}
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ol>
            )}

            {pagination.total_pages > 1 && (
              <nav className={styles.pagination} aria-label="Training history pages">
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
        </>
      )}
    </AuthenticatedShell>
  );
}
