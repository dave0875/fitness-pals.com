import { useState } from "react";
import axios from "axios";

export default function Settings() {
  const [form, setForm] = useState({ url: "", org: "", bucket: "", token: "" });
  const [status, setStatus] = useState("");
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  const connect = async () => {
    try {
      await axios.post("/api/datasource/influx/connect", form, {
        headers: { Authorization: `Bearer ${token}` },
      });
      setStatus("Saved");
    } catch (err) {
      setStatus("Error saving");
    }
  };

  const verify = async () => {
    try {
      await axios.get("/api/datasource/influx/verify", {
        headers: { Authorization: `Bearer ${token}` },
      });
      setStatus("Connection OK");
    } catch (err) {
      setStatus("Verify failed");
    }
  };

  return (
    <main style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Settings</h1>
      {!token && <p>Store your access_token in localStorage.</p>}
      <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", maxWidth: "420px" }}>
        {["url", "org", "bucket", "token"].map((field) => (
          <input
            key={field}
            placeholder={field}
            type={field === "token" ? "password" : "text"}
            value={form[field]}
            onChange={(e) => setForm({ ...form, [field]: e.target.value })}
          />
        ))}
        <button onClick={connect}>Connect</button>
        <button onClick={verify}>Test connection</button>
        <p>{status}</p>
      </div>
    </main>
  );
}
