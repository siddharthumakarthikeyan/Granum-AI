import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The dashboard talks to a locally-running Object Service. Proxying in dev keeps the
// browser on one origin, so there is no CORS preflight on every row fetch.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.GRANUM_SERVICE_URL ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        // The service refuses cross-origin requests. Through this dev proxy the page is
        // on :5173 and the service on :8000, so drop the browser's Origin header here.
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => request.removeHeader("origin"));
        },
      },
    },
  },
  // Built straight into the Python package, which ships it as the dashboard.
  build: { outDir: "../src/granum/service/static", emptyOutDir: true, sourcemap: true },
});
