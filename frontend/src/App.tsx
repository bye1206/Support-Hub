import { useEffect, useState } from "react";

import { parseHealth, type HealthPhase } from "./lib/health";

export default function App() {
  const [phase, setPhase] = useState<HealthPhase>("invalid");
  const [version, setVersion] = useState<string>("");

  useEffect(() => {
    fetch("/healthz")
      .then((response) => response.json())
      .then((payload: unknown) => {
        setPhase(parseHealth(payload));
        if (payload !== null && typeof payload === "object" && "version" in payload) {
          setVersion(String((payload as { version?: unknown }).version ?? ""));
        }
      })
      .catch(() => setPhase("invalid"));
  }, []);

  return (
    <main style={{ fontFamily: "sans-serif", padding: "2rem" }}>
      <h1>Support Hub</h1>
      <p>
        Backend health: <strong>{phase === "ok" ? "OK" : "unavailable"}</strong>
        {version ? ` (v${version})` : ""}
      </p>
      <p>Bootstrap skeleton — operator workspace arrives at stage 8.</p>
    </main>
  );
}
