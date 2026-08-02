import { useEffect, useState } from "react";
import styles from "../styles/AuthenticatedShell.module.css";

const navigation = [
  { key: "home", label: "Home", href: "/dashboard" },
  { key: "journey", label: "Journey", href: "/dashboard#journey" },
  { key: "activities", label: "Activities", href: "/dashboard#activities" },
  { key: "dossiers", label: "Dossiers", href: "/dashboard#dossiers" },
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

export default function AuthenticatedShell({ active = "home", children }) {
  const [profile, setProfile] = useState(null);

  useEffect(() => {
    let mounted = true;
    fetch("/api/auth/session", { credentials: "same-origin" })
      .then((response) => (response.ok ? response.json() : null))
      .then((session) => {
        if (mounted) setProfile(session);
      })
      .catch(() => {
        if (mounted) setProfile(null);
      });
    return () => {
      mounted = false;
    };
  }, []);

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
