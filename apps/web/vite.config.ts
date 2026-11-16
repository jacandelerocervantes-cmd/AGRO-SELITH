import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

const proxy = { '/api': { target: 'http://127.0.0.1:8000', rewrite: (p: string) => p.replace(/^\/api/, '') } };

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'SELITH AGRO',
        short_name: 'SELITH AGRO',
        description: 'Apoyo a la decisión para rotación de cultivos y milpa',
        lang: 'es',
        theme_color: '#1F5C3A',
        background_color: '#F4F1E8',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,mjs,css,html,svg,json,woff2}'],
        navigateFallback: 'index.html',
        navigateFallbackDenylist: [/^\/api\//],
        maximumFileSizeToCacheInBytes: 3 * 1024 * 1024,
        runtimeCaching: [
          {
            // Teselas del mapa: las que la persona vio o descargó con "Guardar mapa" funcionan sin señal
            urlPattern: ({ url }: { url: URL }) => url.hostname === 'server.arcgisonline.com' || url.hostname === 'tile.openstreetmap.org',
            handler: 'CacheFirst',
            options: { cacheName: 'teselas', expiration: { maxEntries: 2000, maxAgeSeconds: 60 * 60 * 24 * 30 }, cacheableResponse: { statuses: [0, 200] } },
          },
        ],
      },
    }),
  ],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
  test: { include: ['src/**/*.test.ts'] },
});
