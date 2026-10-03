import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  // The charting library makes the bundle ~650 KB (~200 KB gzipped) – fine for this app.
  build: { chunkSizeWarningLimit: 900 },
});
