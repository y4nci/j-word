import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000; /api is proxied so the browser never deals with CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.JWORD_API ?? 'http://localhost:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
