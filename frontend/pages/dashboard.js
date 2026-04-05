import { useEffect, useState } from "react";
import axios from "axios";

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [authState, setAuthState] = useState("loading");
  const [message, setMessage] = useState("");
  const [chat, setChat] = useState("");

  useEffect(() => {
    axios
      .post("/api/metrics/summary", {})
      .then((res) => {
        setMetrics(res.data);
        setAuthState("authenticated");
      })
      .catch(() => {
        setMetrics(null);
        setAuthState("unauthenticated");
      });
  }, []);

  const sendChat = async () => {
    try {
      const res = await axios.post("/api/chat", { message });
      setChat(res.data.response);
    } catch (err) {
      setChat("Login required.");
      setAuthState("unauthenticated");
    }
  };

  return (
    <main style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Dashboard</h1>
      {authState === "loading" && <p>Loading your session...</p>}
      {authState === "unauthenticated" && <p>Please log in to continue.</p>}
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
