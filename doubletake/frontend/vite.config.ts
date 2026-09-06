import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The FastAPI backend runs on http://localhost:8000. We proxy every request
// under /api to it (stripping the /api prefix) so the frontend code can use
// relative URLs and avoid CORS entirely in development. CORS is also enabled
// on the backend as a fallback for non-proxied setups.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
});
