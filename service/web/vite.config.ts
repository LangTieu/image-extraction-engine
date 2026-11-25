import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Production: `vite build` emits static files in dist/ that the FastAPI app serves at /.
// Dev only: set VITE_PROXY_API=1 to proxy /v1 to a locally running FastAPI server
// (uvicorn service.api.app:app) — off by default.
const proxyApi = process.env.VITE_PROXY_API === '1'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: proxyApi ? { '/v1': 'http://127.0.0.1:8000' } : undefined,
  },
  build: { outDir: 'dist' },
})
