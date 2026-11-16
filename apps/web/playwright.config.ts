import { defineConfig } from '@playwright/test';

// Requiere PostGIS arriba y sembrado (make up && make migrate && make seed).
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 20_000 },
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:4173', locale: 'es-MX', launchOptions: { args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] } },
  webServer: [
    {
      command: 'uv run uvicorn milpa_api.main:app --app-dir apps/api --port 8000',
      cwd: '../..',
      url: 'http://127.0.0.1:8000/salud',
      reuseExistingServer: true,
      timeout: 60_000,
    },
    // Se prueba la versión de producción: es la que registra el service worker.
    { command: 'npm run build && npm run preview -- --host 127.0.0.1', url: 'http://127.0.0.1:4173', reuseExistingServer: true, timeout: 120_000 },
  ],
});
