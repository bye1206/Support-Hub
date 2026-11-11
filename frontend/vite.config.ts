import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Forward the operator REST and WebSocket APIs to the local FastAPI backend.
// BACKEND_ORIGIN overrides the default when Windows->WSL localhost forwarding
// is unavailable (corporate environments): pass the WSL IP instead, e.g.
//   BACKEND_ORIGIN=http://172.x.x.x:8000 npm run dev
const backendOrigin = process.env.BACKEND_ORIGIN ?? "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/healthz": backendOrigin,
      "/readyz": backendOrigin,
      "/api": backendOrigin,
      "/ws": {
        target: backendOrigin.replace(/^http/, "ws"),
        ws: true,
      },
    },
  },
});
