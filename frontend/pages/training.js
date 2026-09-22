import { useEffect, useState } from "react";

import AuthenticatedShell, { StatusNotice } from "../components/AuthenticatedShell";
import { authenticatedJson } from "../lib/authFetch.mjs";
import { paginateActivities } from "../lib/coreFlowStates.mjs";
import styles from "../styles/Journey.module.css";

const TRAINING_API = "/api/journey";
const PAGE_SIZE = 25;

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(new Date(value));
}

function formatDistance(meters) {
  if (meters === null || meters === undefined) return "Distance unknown";
  return `${(meters / 1609.344).toFixed(1)} mi`;
}

function formatDuration(seconds) {
  if (seconds === null || seconds === undefined) return "Duration unknown";
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return hours ? `${hours}h ${minutes}m` : `${minutes}m`;
}

export default function Training() {
  const [journey, setJourney] = useState(null);
  const [state, setState] = useState("loading");
  const [page, setPage] = useState(1);

  useEffect(() => {
    let mounted = true;
    authenticatedJson(`${TRAINING_API}?window=90d&sport=all&goal=all`)
      .then((data) => {
        if (!mounted) return;
        setJourney(data);
        setState("ready");
      })
      .catch((error) => {
        if (!mounted) return;
        setState(error.status === 401 ? "unauthenticated" : "error");
      });
    return () => {
      mounted = false;
    };
  }, []);

  const pagination = paginateActivities(journey?.activities || [], page, PAGE_SIZE);

  return (
    <AuthenticatedShell active="training">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your record</p>
        <h1>Training history</h1>
        <p>
          Open the workouts behind your coaching decisions. Progress holds the broader trend;
          Training is the activity record.
        </p>
        <a href="/progress">See trends in Progress</a>
      </header>

      {state === "loading" && (
        <div className={styles.statePanel} role="status">
          <strong>Loading your training history</strong>
          <p>Reading your canonical activity record…</p>
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

      {state === "ready" && journey && (
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
          </div>

          <section className={styles.card}>
            <div className={styles.sectionHeading}>
              <div>
                <p className={styles.eyebrow}>Last 90 days</p>
                <h2>Activities</h2>
              </div>
              <span>
                {pagination.from}–{pagination.to} of {journey.activities.length} shown
              </span>
            </div>

            {journey.activities.length === 0 ? (
              <p>No activities are available in this period.</p>
            ) : (
              <ol className={styles.activities}>
                {pagination.items.map((activity) => (
                  <li key={activity.id}>
                    <a href={`/activities/${activity.id}?window=90d&sport=all&goal=all`}>
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

            {pagination.totalPages > 1 && (
              <nav className={styles.pagination} aria-label="Training history pages">
                <button
                  type="button"
                  disabled={pagination.page === 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  Previous
                </button>
                <span>Page {pagination.page} of {pagination.totalPages}</span>
                <button
                  type="button"
                  disabled={pagination.page === pagination.totalPages}
                  onClick={() => setPage((value) => Math.min(pagination.totalPages, value + 1))}
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
