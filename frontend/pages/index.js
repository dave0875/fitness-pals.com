import Link from "next/link";

export default function Home() {
  return (
    <main style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Run Trainer</h1>
      <p>Connect your data and get coaching insights.</p>
      <div style={{ display: "flex", gap: "1rem" }}>
        <a href="/auth/login" style={{ padding: "0.5rem 1rem", border: "1px solid #333" }}>
          Login with Google
        </a>
        <Link href="/dashboard">Dashboard</Link>
      </div>
    </main>
  );
}
