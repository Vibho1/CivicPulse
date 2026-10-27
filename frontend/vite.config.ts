import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// The FastAPI backend (uvicorn app.main:app --port 8000) serves /api and /uploads.
// In dev we proxy both so the app can use relative URLs exactly like production,
// where the backend serves frontend/dist at "/".
const BACKEND = 'http://localhost:8000';
const proxy = {
  '/api': { target: BACKEND, changeOrigin: true },
  '/uploads': { target: BACKEND, changeOrigin: true },
};

export default defineConfig({
  base: '/',
  plugins: [react()],
  server: { port: 5173, host: true, proxy },
  preview: { port: 4173, proxy },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes('node_modules')) return undefined;
          if (/[\\/]node_modules[\\/](react-leaflet|@react-leaflet|leaflet)[\\/]/.test(id)) return 'leaflet';
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler|react-router|react-router-dom)[\\/]/.test(id)) return 'react';
          return undefined;
        },
      },
    },
  },
});
