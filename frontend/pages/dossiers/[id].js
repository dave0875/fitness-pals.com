import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";

import AuthenticatedShell from "../../components/AuthenticatedShell";
import { authenticatedJson } from "../../lib/authFetch.mjs";
import styles from "../../styles/Dossiers.module.css";

function formatDate(value) {
  if (!value) return "Unknown";
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function FindingSection({ title, items }) {
  return (
    <section className={styles.card}>
      <h2>{title}</h2>
      <ul className={styles.findings}>
        {(items || []).map((item, index) => (
          <li key={`${title}-${index}`}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

export default function DossierDetail() {
  const router = useRouter();
  const [dossier, setDossier] = useState(null);
  const [viewState, setViewState] = useState("loading");

  useEffect(() => {
    if (!router.isReady || typeof router.query.id !== "string") return;
    let active = true;
    authenticatedJson(`/api/dossiers/${router.query.id}`)
      .then((data) => {
        if (active) {
          setDossier(data);
          setViewState("ready");
        }
      })
      .catch((error) => {
        if (!active) return;
        setViewState(
          error.status === 401
            ? "unauthenticated"
            : error.status === 404
              ? "not_found"
              : "error"
        );
      });
    return () => {
      active = false;
    };
  }, [router.isReady, router.query.id]);

  const content = dossier?.content;

  return (
    <AuthenticatedShell active="progress">
      <Head>
        <title>Private coaching dossier | Fitness Pals</title>
      </Head>

      {viewState !== "ready" ? (
        <section className={styles.statePanel} role="status">
          {viewState === "loading"
            ? "Loading your private dossier…"
            : "This dossier is unavailable for your account."}
        </section>
      ) : (
        <>
          <Link className={styles.backLink} href="/dossiers">
            ← Back to dossier library
          </Link>
          <header className={styles.pageHeader}>
            <div>
              <p className={styles.eyebrow}>Private dossier · Version {dossier.version}</p>
              <h1>{content.title}</h1>
              <p>{content.summary}</p>
            </div>
            <a
              className={styles.exportButton}
              href={`/api/dossiers/${dossier.id}/export`}
            >
              Export private copy
            </a>
          </header>

          <section className={styles.boundaries}>
            <div>
              <span>Data through</span>
              <strong>{formatDate(content.data_through)}</strong>
            </div>
            <div>
              <span>Connection window</span>
              <strong>{content.connection_window.key}</strong>
            </div>
            <div>
              <span>Freshness</span>
              <strong>{content.freshness}</strong>
            </div>
          </section>

          <section className={styles.card}>
            <h2>Material gaps</h2>
            {content.material_gaps.length ? (
              <ul className={styles.findings}>
                {content.material_gaps.map((gap) => <li key={gap}>{gap}</li>)}
              </ul>
            ) : (
              <p>No material gaps were recorded for this snapshot.</p>
            )}
          </section>

          <div className={styles.columns}>
            <FindingSection title="Evidence" items={content.findings.evidence} />
            <FindingSection title="Inference" items={content.findings.inference} />
            <FindingSection title="Uncertainty" items={content.findings.uncertainty} />
          </div>

          <section className={styles.card}>
            <h2>Evidence activities</h2>
            <ul className={styles.evidenceList}>
              {content.evidence.map((item) => (
                <li key={item.activity_href}>
                  <Link href={item.activity_href}>
                    <strong>{item.label}</strong>
                    <span>{item.summary}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>

          <section className={styles.card}>
            <h2>Next actions</h2>
            <ol className={styles.findings}>
              {content.next_actions.map((item) => <li key={item}>{item}</li>)}
            </ol>
          </section>

          <Link className={styles.journeyLink} href={content.journey_href}>
            Back to Progress evidence
          </Link>
          <p className={styles.privacy}>
            Private by default. Export is owner-authorized and does not create a
            public link. Coaching guidance is not a medical diagnosis.
          </p>
        </>
      )}
    </AuthenticatedShell>
  );
}
