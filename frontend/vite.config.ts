import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 3000,
    // Bind both stacks: Node 18+ resolves "localhost" to ::1 first, so an IPv4-only bind
    // makes http://127.0.0.1:3000 unreachable for anything that prefers IPv4.
    host: true,
    // The SPA talks to a relative /api in both dev and production, so no base URL ever
    // needs to be configured in the client. In dev this proxy points it at the backend;
    // in production nginx serves the same path.
    proxy: {
      "/api": {
        // Inside the dev container the backend is another service, not
        // localhost, so the target is overridable by environment.
        target: process.env.VITE_API_PROXY_TARGET ?? "http://127.0.0.1:8000",
        changeOrigin: true,
        // SSE must not be buffered, or streamed tokens arrive all at once at the end.
        configure: (proxy) => {
          proxy.on("proxyRes", (proxyRes) => {
            if (proxyRes.headers["content-type"]?.includes("text/event-stream")) {
              proxyRes.headers["cache-control"] = "no-cache, no-transform";
            }
          });
        },
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
