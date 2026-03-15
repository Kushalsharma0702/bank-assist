import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    host: '0.0.0.0', 
    strictPort: true,
    allowedHosts: ['eb5c-2401-4900-8841-f341-d3d-3ff0-7b6b-1e04.ngrok-free.app', 'localhost', '.ngrok-free.app']
  },
  preview: {
    port: 5173,
    host: '0.0.0.0'
  }
})
