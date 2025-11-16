import { useEffect, useState } from "react";
import axios from "axios";

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState("");
  const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;

  useEffect(() => {
    if (!token) return;
    axios
      .post(
        "/api/metrics/summary",
        {},
        { headers: { Authorization: `Bearer ${token}` } }
      )
      .then((res) => setMetrics(res.data))
      .catch(() => setMetrics(null));
  }, [token]);

  const sendChat = async () => {
    const res = await axios.post(
      "/api/chat",
      { message },
      { headers: { Authorization: `Bearer ${token}` } }
    );
    setChat(res.data.response);
  };

  return (
    <main style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Dashboard</h1>
      {!token && <p>Please login and store your access token in localStorage.</p>}
      {metrics && (
        <pre style={{ background: "#f5f5f5", padding: "1rem" }}>
          {JSON.stringify(metrics, null, 2)}
        </pre>
      )}
      <section>
        <h2>Chat</h2>
        <textarea value={message} onChange={(e) => setMessage(e.target.value)} />
        <button onClick={sendChat}>Send</button>
        {chat && <p>{chat}</p>}
      </section>
    </main>
  );
}
