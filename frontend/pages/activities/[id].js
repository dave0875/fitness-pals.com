import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useMemo, useState } from "react";

import AuthenticatedShell from "../../components/AuthenticatedShell";
import { authenticatedJson } from "../../lib/authFetch.mjs";
import styles from "../../styles/Journey.module.css";

const formatDate = (value) => {
  if (!value) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
};

const formatDuration = (seconds) => {
  if (!Number.isFinite(seconds)) return "Unavailable";
  const minutes = Math.round(seconds / 60);
  return minutes >= 60
    ? `${Math.floor(minutes / 60)}h ${minutes % 60}m`
    : `${minutes} min`;
};

const formatDistance = (metres) => {
  if (!Number.isFinite(metres)) return "Unavailable";
  return `${(metres / 1000).toFixed(1)} km`;
};

const formatPercent = (value) => {
  if (!Number.isFinite(value)) return "Not comparable";
  if (value === 0) return "At your recent median";
  return `${Math.abs(value)}% ${value > 0 ? "above" : "below"} recent median`;
};

export default function ActivityDetailPage() {
  const router = useRouter();
  const [activity, setActivity] = useState(null);
  const [comparison, setComparison] = useState(null);
  const [state, setState] = useState("loading");
  const [message, setMessage] = useState("");

  const backHref = useMemo(() => {
    const query = new URLSearchParams();
    for (const key of ["window", "sport", "goal", "page"]) {
      if (typeof router.query[key] === "string") {
        query.set(key, router.query[key]);
      }
    }
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return `/training${suffix}`;
  }, [
    router.query.goal,
    router.query.page,
    router.query.sport,
    router.query.window,
  ]);

  const coachHref = useMemo(() => {
    if (!activity?.id) return "/coach";
    const params = new URLSearchParams({
      from: router.asPath,
      activity: activity.id,
      label: activity.title || activity.sport || "Activity",
    });
    return "/coach?" + params.toString();
  }, [activity, router.asPath]);

  useEffect(() => {
    if (!router.isReady || typeof router.query.id !== "string") return;
    let active = true;

    setState("loading");
    authenticatedJson(`/api/journey/activities/${router.query.id}`)
      .then((data) => {
        if (!active) return;
        setActivity({
          ...data.activity,
          provenance: data.provenance,
          data_quality: data.data_quality,
        });
        setComparison(data.comparison);
        setState("ready");
      })
      .catch((error) => {
        if (!active) return;
        if (error?.status === 401) {
          setMessage("Please sign in again to review this activity.");
          setState("unauthorized");
        } else if (error?.status === 404) {
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
    <AuthenticatedShell active="training">
      <Head>
        <title>Activity details | Fitness Pals</title>
      </Head>

      <main>
        <Link className={styles.backLink} href={backHref}>
          ← Back to Training
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
                <p>{formatDate(activity.start_time)}</p>
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
                <strong>{activity.intensity || "Unavailable"}</strong>
              </article>
              <article className={styles.metric}>
                <span>Status</span>
                <strong>{activity.status || "Recorded"}</strong>
              </article>
            </section>

            <section className={styles.card}>
              <div className={styles.sectionHeading}>
                <div>
                  <p className={styles.eyebrow}>Compared with your recent self</p>
                  <h2>Same-sport context</h2>
                </div>
                <span>{comparison?.sample_size || 0} prior activities</span>
              </div>
              {comparison?.state === "available" ? (
                <>
                  <div className={styles.summaryGrid}>
                    <article>
                      <span>Distance</span>
                      <strong>{formatPercent(comparison.distance_percent_vs_median)}</strong>
                    </article>
                    <article>
                      <span>Recent distance median</span>
                      <strong>{formatDistance(comparison.distance_median)}</strong>
                    </article>
                    <article>
                      <span>Duration</span>
                      <strong>{formatPercent(comparison.duration_percent_vs_median)}</strong>
                    </article>
                    <article>
                      <span>Recent duration median</span>
                      <strong>{formatDuration(comparison.duration_seconds_median)}</strong>
                    </article>
                  </div>
                  <p className={styles.boundary}>{comparison.basis}</p>
                </>
              ) : (
                <p>{comparison?.basis || "Comparable prior evidence is unavailable."}</p>
              )}
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
                        <small>Source timestamp: {formatDate(source.source_timestamp)}</small>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p>Source details are unavailable for this historical activity.</p>
                )}
              </section>
            </div>

            <section className={styles.handoff}>
              <div>
                <p className={styles.eyebrow}>Coaching context</p>
                <h2>Ask about this workout</h2>
                <p>Carry this exact canonical activity and its self-comparison into a durable Coach conversation.</p>
              </div>
              <Link href={coachHref}>Ask Coach about this workout</Link>
            </section>

            <p className={styles.boundary}>
              Fitness Pals shows canonical activity facts and transparent self-comparisons
              only. Provider credentials, private ingestion URLs, and raw payloads are never displayed.
            </p>
          </>
        )}
      </main>
    </AuthenticatedShell>
  );
}
