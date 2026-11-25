import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /v1 to the FastAPI server (uvicorn service.api.app:app --reload);
// the UI fetches the API at /v1, same as in production.
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    proxy: { "/v1": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist" },
});
