import Head from "next/head";
import Link from "next/link";

const BACKEND_ORIGIN =
  process.env.RUNTRAINER_FRONTEND_BACKEND_ORIGIN || "http://backend:8000";

export default function PublishedCoachDossierPage({ dossier }) {
  return (
    <>
      <Head>
        <title>{dossier.title} | Fitness Pals</title>
      </Head>
      <main
        style={{
          minHeight: "100vh",
          background: "#eef4f8",
          color: "#13202c",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <div style={{ maxWidth: "1280px", margin: "0 auto", padding: "1.5rem" }}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: "1rem",
              alignItems: "center",
              flexWrap: "wrap",
              marginBottom: "1rem",
            }}
          >
            <div>
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
              <h1 style={{ margin: "0.35rem 0 0", fontSize: "clamp(1.8rem, 4vw, 2.8rem)" }}>
                {dossier.title}
              </h1>
            </div>
            <div style={{ display: "flex", gap: "0.75rem", flexWrap: "wrap" }}>
              <Link href="/coach-dossiers" style={navButtonStyle("secondary")}>
                All dossiers
              </Link>
              <Link href="/import/garmin-export" style={navButtonStyle("primary")}>
                Import another archive
              </Link>
            </div>
          </div>
          <iframe
            title={dossier.title}
            srcDoc={dossier.html}
            style={{
              width: "100%",
              minHeight: "88vh",
              border: "1px solid #dbe6ed",
              borderRadius: "24px",
              background: "#fff",
            }}
          />
        </div>
      </main>
    </>
  );
}

function navButtonStyle(kind) {
  if (kind === "primary") {
    return {
      textDecoration: "none",
      color: "#fff",
      background: "#0d5a55",
      padding: "0.8rem 1rem",
      borderRadius: "999px",
      fontWeight: 700,
    };
  }

  return {
    textDecoration: "none",
    color: "#13202c",
    padding: "0.8rem 1rem",
    borderRadius: "999px",
    border: "1px solid #c7d5df",
    fontWeight: 700,
    background: "#fff",
  };
}

export async function getServerSideProps({ params, res }) {
  const response = await fetch(`${BACKEND_ORIGIN}/api/dossiers/public/${params.slug}`);
  if (!response.ok) {
    if (response.status === 404) {
      return { notFound: true };
    }
    res.statusCode = response.status;
    return { notFound: true };
  }

  return {
    props: {
      dossier: await response.json(),
    },
  };
}
