import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies REST + WebSocket to the FastAPI backend on :8002,
// so the React app and the engine API share an origin during development.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8002", changeOrigin: true, ws: true },
    },
  },
});
