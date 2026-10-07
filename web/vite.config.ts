import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    // In development the page comes from Vite and the API from the cluster
    proxy: { '/api': process.env.API_URL ?? 'http://127.0.0.1:8080' },
    // Inside a container, file change events do not arrive from Windows: look for changes instead
    watch: process.env.WATCH_BY_POLLING ? { usePolling: true, interval: 500 } : undefined,
  },
})
