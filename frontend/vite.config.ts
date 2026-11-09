import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev proxy forwards health checks to the local backend (uvicorn on :8000).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/healthz": "http://localhost:8000",
      "/readyz": "http://localhost:8000",
    },
  },
});
