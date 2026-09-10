import AuthenticatedShell from "../components/AuthenticatedShell";
import styles from "../styles/AthletePages.module.css";

export default function Settings() {
  return (
    <AuthenticatedShell active="settings">
      <header className={styles.pageHeader}>
        <p className={styles.eyebrow}>Your account</p>
        <h1>Settings</h1>
        <p className={styles.lede}>
          Manage how your fitness information reaches Fitness Pals. Account, privacy, and
          connection controls will continue to move into this one place.
        </p>
      </header>

      <div className={styles.sectionGrid}>
        <section className={styles.card}>
          <h2>Fitness connection</h2>
          <p>
            The guided connection flow is the easiest way to connect or refresh your activity data.
          </p>
          <a className={styles.textLink} href="/welcome">Open guided setup</a>
        </section>

        <section className={styles.card}>
          <h2>Session</h2>
          <p>Sign out when you are finished, especially on a shared device.</p>
          <a className={styles.textLink} href="/auth/logout">Sign out</a>
        </section>

        <section className={styles.card}>
          <h2>Historical Garmin archive</h2>
          <p>
            Import the private Drive archive assigned to your account, or stage a Garmin export
            zip. Imports run in the background and resume safely at each source object.
          </p>
          <a className={styles.textLink} href="/import/garmin-archive">Open archive import</a>
        </section>
      </div>
    </AuthenticatedShell>
  );
}
