import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // --host publishes this on the LAN. 127.0.0.1 below is correct and stays:
    // the proxy runs on the machine serving the page, so it is Django's
    // address as seen from *here*, not from the phone or laptop connecting.
    host: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
      // Uploaded revision files and manual PDFs are served by Django from
      // MEDIA_URL. Without this they would 404 on every device.
      '/media': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        secure: false,
      },
    }
  }
})
