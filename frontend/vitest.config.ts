/**
 * Vitest config, kept separate from vite.config.ts.
 *
 * Vitest bundles its own copy of Vite's types, and merging the two in one file produces a
 * spurious plugin type conflict. Separate files keep both type-clean.
 */
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    // happy-dom rather than jsdom: jsdom's html-encoding-sniffer pulls an ESM/CJS
    // combination that fails to load under Node 20 ESM.
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
