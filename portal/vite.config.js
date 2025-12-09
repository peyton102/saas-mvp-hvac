import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // let ngrok reach dev server
    allowedHosts: ['unreproached-physiocratic-madisyn.ngrok-free.dev'], // <-- paste YOUR current ngrok host here
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8799',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
    // If HMR fails through ngrok, uncomment the next line:
    // hmr: { clientPort: 443 },
  },
})
