import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { authenticatedFetch } from "../lib/authFetch.mjs";
import styles from "../styles/AuthenticatedShell.module.css";

const navigation = [
  { key: "home", label: "Home", href: "/dashboard" },
  { key: "journey", label: "Journey", href: "/journey" },
  { key: "activities", label: "Activities", href: "/journey#activities" },
  { key: "dossiers", label: "Dossiers", href: "/dossiers" },
  { key: "coach", label: "Coach", href: "/dashboard#coach" },
  { key: "settings", label: "Settings", href: "/settings" },
];

function displayName(profile) {
  return profile?.name || profile?.email || "Your account";
}

export function StatusNotice({ tone = "neutral", children }) {
  return (
    <div className={`${styles.notice} ${styles[`notice_${tone}`]}`} role="status">
      {children}
    </div>
  );
}

function safeReturnPath(asPath) {
  return typeof asPath === "string" && asPath.startsWith("/") && !asPath.startsWith("//")
    ? asPath
    : "/dashboard";
}

export default function AuthenticatedShell({ active = "home", children }) {
  const router = useRouter();
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    if (!router.isReady) return undefined;
    let mounted = true;
    authenticatedFetch("/api/auth/session")
      .then((response) => {
        if (response.status === 401 || response.status === 403) {
          const next = encodeURIComponent(safeReturnPath(router.asPath));
          window.location.assign(`/auth/login?next=${next}`);
          return null;
        }
        return response.ok ? response.json() : null;
      })
      .then((session) => {
        if (mounted) setProfile(session);
      })
      .catch(() => {
        if (mounted) setProfile(null);
      });
    return () => {
      mounted = false;
    };
  }, [router.asPath, router.isReady]);

  return (
    <div className={styles.shell}>
      <a className={styles.skipLink} href="#main-content">
        Skip to content
      </a>
      <header className={styles.header}>
        <a className={styles.brand} href="/dashboard" aria-label="Fitness Pals home">
          <span className={styles.brandMark} aria-hidden="true">FP</span>
          <span>
            <strong>Fitness Pals</strong>
            <small>Your training companion</small>
          </span>
        </a>
        <div className={styles.account}>
          <a href="/settings" className={styles.accountLink}>{displayName(profile)}</a>
          <a href="/auth/logout" className={styles.logout}>Sign out</a>
        </div>
      </header>

      <nav className={styles.navigation} aria-label="Primary navigation">
        {navigation.map((item) => (
          <a
            key={item.key}
            href={item.href}
            className={item.key === active ? styles.activeLink : styles.navLink}
            aria-current={item.key === active ? "page" : undefined}
          >
            {item.label}
          </a>
        ))}
      </nav>

      <main className={styles.content} id="main-content">
        {children}
      </main>
    </div>
  );
}
