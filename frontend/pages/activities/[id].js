import axios from "axios";
import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import AuthenticatedShell from "../../components/AuthenticatedShell";
import styles from "../../styles/Journey.module.css";

const formatDate = (value) => {
  if (!value) return "Unknown date";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
};

const formatDuration = (seconds) => {
  if (!Number.isFinite(seconds)) return "Unknown";
  const minutes = Math.round(seconds / 60);
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
    : `${minutes} min`;
};

const formatDistance = (metres) => {
  if (!Number.isFinite(metres)) return "Unknown";
  return `${(metres / 1000).toFixed(1)} km`;
};

export default function ActivityDetailPage() {
  const router = useRouter();
  const [activity, setActivity] = useState(null);
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState("");

  const backHref = useMemo(() => {
    const query = new URLSearchParams();
    if (typeof router.query.window === "string") {
      query.set("window", router.query.window);
    }
    if (typeof router.query.sport === "string") {
      query.set("sport", router.query.sport);
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return `/journey${suffix}#activities`;
  }, [router.query.sport, router.query.window]);

  useEffect(() => {
    if (!router.isReady || typeof router.query.id !== "string") return;
    let active = true;

    setState("loading");
    axios
      .get(`/api/journey/activities/${router.query.id}`)
      .then(({ data }) => {
        if (!active) return;
        setActivity(data);
        setState("ready");
      })
      .catch((error) => {
        if (!active) return;
        if (error?.response?.status === 401) {
          setMessage("Please sign in again to review this activity.");
          setState("unauthorized");
        } else if (error?.response?.status === 404) {
          setMessage("This activity is unavailable or does not belong to your account.");
          setState("not-found");
        } else {
          setMessage("We could not load this activity. Please try again.");
          setState("error");
        }
      });

    return () => {
      active = false;
    };
  }, [router.isReady, router.query.id]);

  return (
    <AuthenticatedShell active="activities">
      <Head>
        <title>Activity details | Fitness Pals</title>
      </Head>

      <main>
        <Link className={styles.backLink} href={backHref}>
          ← Back to journey
        </Link>

        {state !== "ready" ? (
          <section className={styles.statePanel} aria-live="polite">
            <h1>{state === "loading" ? "Loading activity…" : "Activity unavailable"}</h1>
            {message ? <p>{message}</p> : null}
          </section>
        ) : (
          <>
            <header className={styles.pageHeader}>
              <div>
                <p className={styles.eyebrow}>Personal activity</p>
                <h1>{activity.title || activity.sport || "Activity details"}</h1>
                <p>{formatDate(activity.started_at)}</p>
              </div>
              <span className={styles.goalPill}>{activity.sport || "Unclassified"}</span>
            </header>

            <section className={styles.detailGrid} aria-label="Activity summary">
              <article className={styles.metric}>
                <span>Distance</span>
                <strong>{formatDistance(activity.distance_m)}</strong>
              </article>
              <article className={styles.metric}>
                <span>Duration</span>
                <strong>{formatDuration(activity.duration_seconds)}</strong>
              </article>
              <article className={styles.metric}>
                <span>Intensity</span>
                <strong>{activity.intensity || "Unknown"}</strong>
              </article>
              <article className={styles.metric}>
                <span>Status</span>
                <strong>{activity.status || "Recorded"}</strong>
              </article>
            </section>

            <div className={styles.columns}>
              <section className={styles.card}>
                <div className={styles.sectionHeading}>
                  <div>
                    <p className={styles.eyebrow}>Quality</p>
                    <h2>Data completeness</h2>
                  </div>
                </div>
                {activity.data_quality?.missing?.length ? (
                  <>
                    <p>These fields were not supplied by the connected source:</p>
                    <ul className={styles.quality}>
                      {activity.data_quality.missing.map((field) => (
                        <li key={field}>{field.replaceAll("_", " ")}</li>
                      ))}
                    </ul>
                  </>
                ) : (
                  <p>All supported summary fields are available.</p>
                )}
              </section>

              <section className={styles.card}>
                <div className={styles.sectionHeading}>
                  <div>
                    <p className={styles.eyebrow}>Source</p>
                    <h2>Data provenance</h2>
                  </div>
                </div>
                {activity.provenance?.length ? (
                  <ul className={styles.provenance}>
                    {activity.provenance.map((source, index) => (
                      <li key={`${source.provider}-${index}`}>
                        <strong>{source.provider || "Connected provider"}</strong>
                        <span>
                          {source.upstream_provider
                            ? ` via ${source.upstream_provider}`
                            : ""}
                        </span>
                        <small>
                          Source timestamp: {formatDate(source.source_timestamp)}
                        </small>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>Source details are unavailable for this historical activity.</p>
                )}
              </section>
            </div>

            <p className={styles.boundary}>
              Fitness Pals shows canonical activity facts only. Provider credentials,
              private ingestion URLs, and raw payloads are never displayed.
            </p>
          </>
        )}
      </main>
    </AuthenticatedShell>
  );
}
