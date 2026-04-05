import { useState } from "react";
import axios from "axios";

export default function Settings() {
  const [form, setForm] = useState({ url: "", org: "", bucket: "", token: "" });
  const [status, setStatus] = useState("");

  const connect = async () => {
    try {
      await axios.post("/api/datasource/influx/connect", form);
      setStatus("Saved");
    } catch (err) {
      setStatus("Login required or error saving");
    }
  };

  const verify = async () => {
    try {
      await axios.get("/api/datasource/influx/verify");
      setStatus("Connection OK");
    } catch (err) {
      setStatus("Login required or verify failed");
    }
  };

  return (
    <main style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Settings</h1>
      <p>Your app session is used automatically for these requests.</p>
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
