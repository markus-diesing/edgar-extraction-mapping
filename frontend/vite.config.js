import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Local dev: proxy to localhost:8000 (default)
// Docker:    VITE_BACKEND_URL=http://backend:8000 (set in docker-compose.yml)
const backendUrl = process.env.VITE_BACKEND_URL || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',   // required when running inside Docker
    port: 5173,
    proxy: {
      '/api': backendUrl,
    },
  },
})
