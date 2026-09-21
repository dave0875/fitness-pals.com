import Head from "next/head";

const CONTACT_EMAIL = "david.barker@fitness-pals.com";
const CANONICAL_URL = "https://fitness-pals.com/privacy";
const EFFECTIVE_DATE = "September 21, 2026";

const shellStyle = {
  minHeight: "100vh",
  background: "linear-gradient(180deg, #f8fbff 0%, #eef5f9 100%)",
  color: "#13202c",
  fontFamily: "system-ui, sans-serif",
};

const contentStyle = {
  maxWidth: "900px",
  margin: "0 auto",
  padding: "3rem 1.5rem 4rem",
};

const cardStyle = {
  background: "#ffffff",
  border: "1px solid #dbe6ed",
  borderRadius: "24px",
  padding: "clamp(1.25rem, 3vw, 2rem)",
  boxShadow: "0 20px 40px rgba(19, 32, 44, 0.06)",
};

const sectionStyle = {
  marginTop: "2rem",
  lineHeight: 1.75,
  color: "#334756",
};

function PolicySection({ title, children }) {
  return (
    <section style={sectionStyle}>
      <h2 style={{ margin: "0 0 0.75rem", color: "#13202c", fontSize: "1.45rem" }}>{title}</h2>
      {children}
    </section>
  );
}

export default function PrivacyPolicy() {
  return (
    <>
      <Head>
        <title>Privacy Policy | Fitness Pals</title>
        <meta
          name="description"
          content="How Fitness Pals collects, uses, stores, and shares account, fitness, wellness, and coaching data."
        />
        <link rel="canonical" href={CANONICAL_URL} />
      </Head>

      <main style={shellStyle}>
        <div style={contentStyle}>
          <header
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              gap: "1rem",
              flexWrap: "wrap",
              marginBottom: "1.5rem",
            }}
          >
            <a
              href="/"
              style={{
                color: "#13202c",
                textDecoration: "none",
                fontWeight: 800,
                letterSpacing: "0.06em",
                fontSize: "0.95rem",
              }}
            >
              FITNESS PALS
            </a>
            <a
              href="/"
              style={{
                color: "#0b5f58",
                textDecoration: "none",
                fontWeight: 700,
              }}
            >
              Back to Fitness Pals
            </a>
          </header>

          <article style={cardStyle}>
            <div
              style={{
                display: "inline-block",
                padding: "0.4rem 0.75rem",
                borderRadius: "999px",
                background: "#e5f1f0",
                color: "#0b5f58",
                fontWeight: 800,
                fontSize: "0.85rem",
                letterSpacing: "0.04em",
              }}
            >
              PRIVACY POLICY
            </div>
            <h1
              style={{
                margin: "1rem 0 0",
                fontSize: "clamp(2.2rem, 6vw, 3.8rem)",
                lineHeight: 1.02,
              }}
            >
              Your training data should work for you.
            </h1>
            <p style={{ marginTop: "1rem", color: "#526472", lineHeight: 1.75, maxWidth: "68ch" }}>
              This Privacy Policy explains how Fitness Pals handles information when you use the
              Fitness Pals website and product, including account, training, recovery, wellness,
              and coaching information.
            </p>
            <p style={{ marginTop: "0.75rem", color: "#627585", lineHeight: 1.6 }}>
              <strong>Effective date:</strong> {EFFECTIVE_DATE}
              <br />
              <strong>Last updated:</strong> {EFFECTIVE_DATE}
            </p>

            <PolicySection title="1. Who operates Fitness Pals">
              <p>
                Fitness Pals operates the service available at fitness-pals.com. Questions or
                privacy requests can be sent to{" "}
                <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#0b5f58", fontWeight: 700 }}>
                  {CONTACT_EMAIL}
                </a>
                .
              </p>
            </PolicySection>

            <PolicySection title="2. Information we handle">
              <p>Depending on the features you use, Fitness Pals may handle the following categories of information:</p>
              <ul>
                <li>
                  <strong>Account and identity information:</strong> such as your name, email
                  address, login identity, and account/session identifiers supplied through the
                  sign-in flow.
                </li>
                <li>
                  <strong>Training and activity information:</strong> such as activity type, date
                  and time, duration, distance, pace or speed, heart rate, cadence, power, route or
                  location fields when present, and other workout metrics supplied by a connected
                  provider or imported file.
                </li>
                <li>
                  <strong>Recovery and wellness information:</strong> such as sleep, heart-rate
                  variability, resting heart rate, stress, respiration, Pulse Ox or similar
                  wellness signals when you connect or import a source that provides them.
                </li>
                <li>
                  <strong>Goals and coaching information:</strong> such as target events, training
                  goals, preferences, plans, workout feedback, readiness summaries, coaching
                  recommendations, and athlete dossiers generated from your data.
                </li>
                <li>
                  <strong>Connection and import information:</strong> such as provider connection
                  status, sync state, provenance, import history, and archive metadata needed to
                  retrieve or reconcile your training history.
                </li>
                <li>
                  <strong>Technical and security information:</strong> such as browser and request
                  information, service logs, timestamps, error details, and security/audit events
                  needed to operate and protect the service.
                </li>
              </ul>
            </PolicySection>

            <PolicySection title="3. Where training and wellness data can come from">
              <p>
                Fitness Pals can work with data you authorize, upload, or import. Current product
                paths include Garmin-connected or Garmin-exported data and Garmin archive imports.
                Fitness Pals also supports account-owned archive ingestion, including read-only
                Google Drive archive access when you explicitly authorize it. The product data
                model can retain provenance from additional supported fitness sources, such as
                Strava or Apple Health, when those sources are enabled and data is supplied to the
                service.
              </p>
              <p>
                Garmin archive import is separate from Garmin's official developer APIs. Official
                Garmin API access is used only when Fitness Pals has the required Garmin developer
                approval, the applicable integration is enabled, and you authorize that
                connection. We do not treat ordinary Garmin Connect website sign-in as third-party
                API consent.
              </p>
            </PolicySection>

            <PolicySection title="4. How we use information">
              <p>We use information to:</p>
              <ul>
                <li>authenticate your account and maintain your Fitness Pals session;</li>
                <li>connect, import, normalize, reconcile, and display your training history;</li>
                <li>deduplicate activity records while preserving source provenance;</li>
                <li>generate training, recovery, readiness, and coaching experiences you request;</li>
                <li>operate connection, sync, archive, and troubleshooting workflows;</li>
                <li>protect accounts, investigate errors, and maintain service reliability; and</li>
                <li>comply with legal obligations and enforce applicable service terms.</li>
              </ul>
            </PolicySection>

            <PolicySection title="5. Connected accounts and authorization">
              <p>
                Fitness Pals uses account-based authorization for supported providers. The
                production sign-in path uses an identity broker with Google sign-in available as
                an upstream identity source. Where a provider connection requires access or
                refresh credentials, those credentials are handled server-side and are not
                intended to be exposed through normal athlete-facing pages.
              </p>
              <p>
                For Google Drive archive imports, the service requests read-only Drive access and
                uses that authorization to discover supported training archive files in the
                authorized account. You may revoke provider access through the applicable provider
                and, where supported in Fitness Pals, disconnect the connection in the product.
              </p>
            </PolicySection>

            <PolicySection title="6. How we share information">
              <p>
                Fitness Pals does <strong>not sell your personal fitness or wellness data</strong>.
                We may disclose information only as needed to operate the service, including to
                service providers that support authentication, hosting, security, monitoring,
                storage, or other product functions; to connected providers at your direction; or
                when required by law, legal process, or to protect rights and security.
              </p>
              <p>
                A connected provider's own handling of data is governed by that provider's terms
                and privacy practices.
              </p>
            </PolicySection>

            <PolicySection title="7. Storage, retention, and disconnecting a source">
              <p>
                Fitness Pals maintains account-owned product records so that training history can
                support longitudinal analysis and coaching. Disconnecting a provider stops or
                limits future access according to the connection, but it does not automatically
                erase training history that was already imported into Fitness Pals. This preserves
                canonical activity history and provenance unless that information is later
                removed through an applicable deletion process.
              </p>
              <p>
                We retain information for as long as reasonably needed to provide and secure the
                service, maintain necessary records, resolve disputes, and meet legal obligations.
                Retention can vary by data type and the state of your account.
              </p>
            </PolicySection>

            <PolicySection title="8. Your choices and requests">
              <p>
                Depending on the feature and applicable law, you may be able to disconnect a data
                source, revoke authorization at the provider, update account information, or ask
                us to access, correct, export, or delete information associated with your account.
                To make a privacy request, contact{" "}
                <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#0b5f58", fontWeight: 700 }}>
                  {CONTACT_EMAIL}
                </a>
                . We may need to verify your identity before acting on a request.
              </p>
            </PolicySection>

            <PolicySection title="9. Security">
              <p>
                Fitness Pals uses technical and organizational measures intended to protect account
                and training information, including user-scoped access controls and separation of
                provider credentials from normal athlete-facing interfaces. No system can
                guarantee absolute security, and we continually treat security as an operational
                responsibility rather than a promise of perfect protection.
              </p>
            </PolicySection>

            <PolicySection title="10. Cookies and session technology">
              <p>
                Fitness Pals uses cookies or similar session technology that is necessary for
                authentication, account security, and core product operation. Product sessions are
                designed to use Fitness Pals session credentials rather than exposing connected
                provider tokens to the browser as the athlete's application session.
              </p>
            </PolicySection>

            <PolicySection title="11. Children">
              <p>
                Fitness Pals is not directed to children under 13. If we learn that information
                from a child under 13 was provided without appropriate authorization, we will take
                reasonable steps to address it.
              </p>
            </PolicySection>

            <PolicySection title="12. International processing">
              <p>
                Fitness Pals and the service providers used to operate it may process information
                in the United States and in other locations where those providers operate. Those
                locations may have data-protection rules that differ from those where you live.
              </p>
            </PolicySection>

            <PolicySection title="13. Changes to this policy">
              <p>
                We may update this Privacy Policy as Fitness Pals changes. When we do, we will
                update the "Last updated" date on this page. Material changes may also be surfaced
                through the product or another appropriate notice.
              </p>
            </PolicySection>

            <PolicySection title="14. Contact">
              <p>
                Privacy questions and requests:{" "}
                <a href={`mailto:${CONTACT_EMAIL}`} style={{ color: "#0b5f58", fontWeight: 700 }}>
                  {CONTACT_EMAIL}
                </a>
              </p>
              <p>
                Website:{" "}
                <a href="https://fitness-pals.com" style={{ color: "#0b5f58", fontWeight: 700 }}>
                  https://fitness-pals.com
                </a>
              </p>
              <p>
                Privacy Policy:{" "}
                <a href={CANONICAL_URL} style={{ color: "#0b5f58", fontWeight: 700 }}>
                  {CANONICAL_URL}
                </a>
              </p>
            </PolicySection>
          </article>
        </div>
      </main>
    </>
  );
}
