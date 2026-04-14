import { useEffect, useState } from "react";

const AUTH_HREF = "/auth/login?next=/import/garmin-export";

export default function GarminExportImportPage() {
  const [sessionState, setSessionState] = useState("checking");
  const [selectedFile, setSelectedFile] = useState(null);
  const [message, setMessage] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    let active = true;

    async function loadSession() {
      try {
        const response = await fetch("/api/auth/session", { credentials: "include" });
        if (!active) {
          return;
        }
        setSessionState(response.ok ? "authenticated" : "unauthenticated");
      } catch (_error) {
        if (active) {
          setSessionState("unauthenticated");
        }
      }
    }

    loadSession();
    return () => {
      active = false;
    };
  }, []);

  async function handleSubmit(event) {
    event.preventDefault();
    if (!selectedFile) {
      setMessage("Choose a Garmin export zip first.");
      return;
    }

    const formData = new FormData();
    formData.append("archive", selectedFile);

    setIsSubmitting(true);
    setMessage("Importing Garmin export...");

    try {
      const response = await fetch("/api/dossiers/import/garmin-export", {
        method: "POST",
        body: formData,
        credentials: "include",
      });

      if (response.status === 401) {
        setSessionState("unauthenticated");
        setMessage("Sign in first, then retry the import.");
        return;
      }

      const payload = await response.json();
      if (!response.ok) {
        setMessage(payload.detail || "Garmin export import failed.");
        return;
      }

      window.location.assign(payload.dossier_url);
    } catch (_error) {
      setMessage("Garmin export import failed.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main
      style={{
        minHeight: "100vh",
        background: "linear-gradient(180deg, #f7fbff 0%, #edf3f8 100%)",
        color: "#13202c",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <div style={{ maxWidth: "880px", margin: "0 auto", padding: "3rem 1.5rem 4rem" }}>
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
          Garmin Export Import
        </p>
        <h1 style={{ margin: "0.5rem 0 0", fontSize: "clamp(2.2rem, 5vw, 3.6rem)" }}>
          Import a Garmin export zip safely
        </h1>
        <p style={{ maxWidth: "60ch", color: "#526472", lineHeight: 1.75 }}>
          Sign in with the athlete account first. The import only proceeds when the signed-in email
          matches the athlete contact inside the Garmin export zip.
        </p>

        {sessionState !== "authenticated" && (
          <section
            style={{
              background: "#fff",
              border: "1px solid #dbe6ed",
              borderRadius: "22px",
              padding: "1.5rem",
              boxShadow: "0 18px 36px rgba(19, 32, 44, 0.06)",
              marginTop: "1.75rem",
            }}
          >
            <p style={{ margin: 0, color: "#526472", lineHeight: 1.7 }}>
              This route is authenticated. Establish the athlete account through the normal sign-in
              flow, then return here to upload the Garmin Export zip.
            </p>
            <a
              href={AUTH_HREF}
              style={{
                display: "inline-block",
                marginTop: "1rem",
                textDecoration: "none",
                color: "#fff",
                background: "#0d5a55",
                padding: "0.9rem 1.15rem",
                borderRadius: "999px",
                fontWeight: 800,
              }}
            >
              Continue with Gmail
            </a>
          </section>
        )}

        {sessionState === "authenticated" && (
          <form
            onSubmit={handleSubmit}
            style={{
              background: "#fff",
              border: "1px solid #dbe6ed",
              borderRadius: "22px",
              padding: "1.5rem",
              boxShadow: "0 18px 36px rgba(19, 32, 44, 0.06)",
              marginTop: "1.75rem",
              display: "grid",
              gap: "1rem",
            }}
          >
            <label style={{ display: "grid", gap: "0.6rem", fontWeight: 700 }}>
              Garmin Export zip
              <input
                type="file"
                accept=".zip,application/zip"
                onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <p style={{ margin: 0, color: "#526472", lineHeight: 1.7 }}>
              The import stays bound to the current athlete account and publishes a separate coach
              dossier without touching the sample dossier pages.
            </p>
            <div style={{ display: "flex", gap: "0.9rem", flexWrap: "wrap" }}>
              <button
                type="submit"
                disabled={isSubmitting}
                style={{
                  border: 0,
                  background: "#0d5a55",
                  color: "#fff",
                  padding: "0.95rem 1.3rem",
                  borderRadius: "999px",
                  fontWeight: 800,
                  cursor: isSubmitting ? "default" : "pointer",
                }}
              >
                {isSubmitting ? "Importing..." : "Import Garmin export"}
              </button>
            </div>
            {message && <p style={{ margin: 0, color: "#526472" }}>{message}</p>}
          </form>
        )}
      </div>
    </main>
  );
}
