import Head from "next/head";
import Link from "next/link";

const pageStyle = {
  minHeight: "100vh",
  background: "linear-gradient(180deg, #f7fbff 0%, #edf3f8 100%)",
  color: "#13202c",
  fontFamily: "system-ui, sans-serif",
};

const wrapStyle = {
  maxWidth: "980px",
  margin: "0 auto",
  padding: "3rem 1.5rem 4rem",
};

const cardStyle = {
  background: "#fff",
  border: "1px solid #dbe6ed",
  borderRadius: "22px",
  padding: "1.5rem",
  boxShadow: "0 18px 36px rgba(19, 32, 44, 0.06)",
};

const buttonStyle = {
  display: "inline-block",
  marginTop: "1rem",
  textDecoration: "none",
  color: "#0d5a55",
  border: "1px solid #0d5a55",
  borderRadius: "999px",
  padding: "0.85rem 1.1rem",
  fontWeight: 800,
  background: "#fff",
};

const BACKEND_ORIGIN = process.env.RUNTRAINER_FRONTEND_BACKEND_ORIGIN || "http://backend:8000";

export default function CoachDossiersIndexPage({ dossiers }) {
  return (
    <>
      <Head>
        <title>Coach Dossiers | Fitness Pals</title>
      </Head>
      <main style={pageStyle}>
        <div style={wrapStyle}>
          <p
            style={{
              margin: 0,
              textTransform: "uppercase",
              letterSpacing: "0.14em",
              fontSize: "0.78rem",
              color: "#0d5a55",
              fontWeight: 800,
            }}
          >
            Coach Dossiers
          </p>
          <h1 style={{ margin: "0.5rem 0 0", fontSize: "clamp(2.2rem, 5vw, 3.6rem)" }}>
            Published coaching artifacts
          </h1>
          <p style={{ maxWidth: "60ch", color: "#526472", lineHeight: 1.75 }}>
            Fitness Pals sample dossiers plus published athlete dossiers created from imported
            Garmin archives.
          </p>

          <div style={{ display: "grid", gap: "1rem", marginTop: "1.75rem" }}>
            {dossiers.length === 0 && (
              <section style={cardStyle}>
                <h2 style={{ margin: 0, fontSize: "1.5rem" }}>No imported dossiers yet</h2>
                <p style={{ margin: "0.75rem 0 0", color: "#526472", lineHeight: 1.75 }}>
                  Publish a dossier by signing in as the athlete and importing a Garmin export zip.
                </p>
                <Link href="/import/garmin-export" style={buttonStyle}>
                  Import Garmin export
                </Link>
              </section>
            )}
            {dossiers.map((dossier) => (
              <section key={dossier.slug} style={cardStyle}>
                <h2 style={{ margin: 0, fontSize: "1.5rem" }}>{dossier.title}</h2>
                <p style={{ margin: "0.75rem 0 0", color: "#526472", lineHeight: 1.75 }}>
                  {dossier.summary}
                </p>
                <Link href={`/coach-dossiers/${dossier.slug}`} style={buttonStyle}>
                  Open dossier
                </Link>
              </section>
            ))}
          </div>
        </div>
      </main>
    </>
  );
}

export async function getServerSideProps() {
  let importedDossiers = [];

  try {
    const response = await fetch(`${BACKEND_ORIGIN}/api/dossiers/public`);
    if (response.ok) {
      importedDossiers = await response.json();
    }
  } catch (_error) {
    importedDossiers = [];
  }

  return {
    props: {
      dossiers: importedDossiers,
    },
  };
}
