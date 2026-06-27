import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

const API = "http://127.0.0.1:8765";

// Dev server proxies the API + WebSocket to the FastAPI sidecar, so the
// frontend can use same-origin relative URLs ("/api/...", "/ws/...").
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "./", // relative asset paths so the built bundle loads from file:// in Electron
  server: {
    port: 5173,
    proxy: {
      "/api": { target: API, changeOrigin: true },
      "/ws": { target: API, ws: true, changeOrigin: true },
    },
  },
  build: { outDir: "dist", emptyOutDir: true },
});
