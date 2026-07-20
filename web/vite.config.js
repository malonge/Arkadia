import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  server: {
    port: 5173,
    // Proxy API and WebSocket calls to the FastAPI backend during development.
    // In production the API serves everything from port 8000 directly, so no
    // proxy is used.  All API routes (including WebSocket) now live under /api.
    proxy: {
      // WebSocket must be listed before the HTTP /api catch-all so that
      // upgrade requests to /api/ws/* are handled by the ws-aware proxy entry.
      '/api/ws': {
        target: 'ws://localhost:8000',
        ws: true,
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        // No rewrite needed — FastAPI routes are now at /api/* in production.
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
});
