import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Backend runs on :8000 (see backend/main.py); dev server proxies /api
// so the frontend never hardcodes a backend origin.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  // Vitest config: jsdom so React components can render/interact without a
  // browser; globals so tests read like the rest of the ecosystem (describe/
  // it/expect) without per-file imports. See src/test/setup.js.
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
  },
});