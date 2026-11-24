import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api to the FastAPI server (uvicorn service.api.app:app --reload).
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist" },
});
