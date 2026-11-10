import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
// Forward the operator REST and WebSocket APIs to local FastAPI.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/healthz": "http://localhost:8000",
      "/readyz": "http://localhost:8000",
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
