import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const BACKEND_PORT = process.env.VITE_BACKEND_PORT || 8000;

// In dev, /api/* is proxied to the FastAPI server, so the browser sees one origin and CORS is not needed.
// Use 127.0.0.1 explicitly to avoid Node 18+ IPv6 (::1) lookup mismatches on Windows.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: `http://127.0.0.1:${BACKEND_PORT}`,
        changeOrigin: true,
      },
    },
  },
});
