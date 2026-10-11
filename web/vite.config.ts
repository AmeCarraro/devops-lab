import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // keep the errors of the Rust compiler on screen when the desktop app is built
  clearScreen: false,
  server: {
    host: true,
    // In development the page comes from Vite, the API and the sample pictures from the cluster
    proxy: {
      '/api': process.env.API_URL ?? 'http://127.0.0.1:8080',
      '/samples': process.env.API_URL ?? 'http://127.0.0.1:8080',
    },
    watch: {
      // the native side is rebuilt by Tauri, not by Vite
      ignored: ['**/src-tauri/**'],
      // Inside a container, file change events do not arrive from Windows: look for changes instead
      usePolling: Boolean(process.env.WATCH_BY_POLLING),
      interval: 500,
    },
  },
})
