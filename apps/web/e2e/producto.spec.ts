import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

const EXPERTO = (area: string) => ({ 'X-Demo-Login': `demo-experto-${area}` });

async function limpio(page: Page) {
  await page.goto('/');
  await page.evaluate(() => localStorage.clear());
  await page.reload();
}

async function dibujarParcela(page: Page) {
  await expect(page.getByTestId('mapa')).toHaveAttribute('data-listo', '1');
  const b = (await page.getByTestId('mapa').boundingBox())!;
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  for (const [dx, dy] of [[-30, -30], [30, -30], [30, 30], [-30, 30]]) await page.mouse.click(cx + dx, cy + dy);
}

/** Entra como productor, dibuja una parcela y llega al chat. */
async function productorEnChat(page: Page) {
  await limpio(page);
  await page.getByTestId('entrar-productor').click();
  await dibujarParcela(page);
  await expect(page.getByTestId('m2')).toContainText('m²');
  const m2 = Number((await page.getByTestId('m2').innerText()).replace(/[^\d]/g, ''));
  expect(m2).toBeGreaterThan(10_000);
  expect(m2).toBeLessThan(500_000);
  await page.getByTestId('guardar-parcela').click();
  await expect(page.getByTestId('pantalla-chat')).toBeVisible({ timeout: 90_000 });
}

async function preguntar(page: Page, texto: string) {
  await page.getByTestId('enviar').isVisible();
  await page.locator('textarea').first().fill(texto);
  await page.getByTestId('enviar').click();
}

async function vaciarComoExperto(request: APIRequestContext, area: string, buscada: string) {
  for (let i = 0; i < 25; i++) {
    const s = await (await request.post('/api/experto/cola/siguiente', { headers: EXPERTO(area), data: {} })).json();
    if (s.vacia) return false;
    const ok = await request.post(`/api/experto/solicitudes/${s.id}/revision`, {
      headers: EXPERTO(area),
      data: { decision: 'confirmar', fuentes: ['INIFAP (ejemplo de prueba)'] },
    });
    expect(ok.ok()).toBeTruthy();
    if (s.pregunta === buscada) return true;
  }
  return false;
}

test('landing con acceso simulado, sin correo, en español e inglés', async ({ page }) => {
  await limpio(page);
  await expect(page.getByTestId('landing')).toContainText('Decida qué sembrar');
  await expect(page.locator('input[type=email], input[type=password]')).toHaveCount(0);
  await page.getByRole('button', { name: 'EN', exact: true }).click();
  await expect(page.getByTestId('landing')).toContainText('Decide what to plant');
  await expect(page.getByTestId('entrar-productor')).toHaveText('Enter');
  await page.getByRole('button', { name: 'ES', exact: true }).click();
  await expect(page.getByTestId('entrar-productor')).toHaveText('Entrar');
});

test('productor: dibuja su parcela en m², pregunta y recibe tres estrategias "Solo IA"', async ({ page }) => {
  await productorEnChat(page);
  await preguntar(page, '¿Qué siembro si la canícula se alarga?');
  const a = page.getByTestId('msg-asistente').last();
  await expect(a.getByTestId('estrategias')).toBeVisible({ timeout: 30_000 });
  await expect(a.getByTestId('badge-respaldo')).toHaveAttribute('data-estado', 'solo_ia');
  await expect(a.getByRole('tab')).toHaveCount(3);
  await a.getByRole('tab', { name: 'Rotación actual' }).click();
  await expect(a.locator('[data-crop="milpa_tradicional"]')).toHaveCount(4);
  const [agua, base] = (await a.getByTestId('agua-txt').innerText()).match(/\d+/g)!.map(Number);
  expect(agua).toBeLessThanOrEqual(base);
  await a.getByText('Evidencia', { exact: true }).click();
  await expect(a).toContainText('NASA POWER');
  await a.getByText('Lo que aún no se sabe', { exact: true }).click();
  await expect(a).toContainText('INEGI');
  await a.getByRole('tab', { name: 'Opción 1' }).click();
  await a.getByRole('button', { name: 'Aceptar' }).click();
  await expect(a.getByRole('status')).toContainText('Decisión guardada');
  await page.screenshot({ path: 'e2e/captura-chat.png', fullPage: true });
});

test('el chat responde en inglés', async ({ page }) => {
  await productorEnChat(page);
  await page.getByRole('button', { name: 'EN', exact: true }).first().click();
  await preguntar(page, 'What should I plant if there is a dry spell?');
  await expect(page.getByTestId('msg-asistente').last()).toContainText('I compared three strategies', { timeout: 30_000 });
  await expect(page.getByTestId('msg-asistente').last().getByRole('tab', { name: 'Current rotation' })).toBeVisible();
});

test('lazo completo: solo IA -> experto del área confirma -> con respaldo y reporte revisado', async ({ page, request }) => {
  await productorEnChat(page);
  const pregunta = `¿Cómo mejoro un suelo pedregoso? ${Date.now()}`;
  await preguntar(page, pregunta);
  await expect(page.getByTestId('msg-asistente').last().getByTestId('badge-respaldo')).toHaveAttribute('data-estado', 'solo_ia', { timeout: 30_000 });
  expect(await vaciarComoExperto(request, 'suelos', pregunta)).toBeTruthy();
  await page.reload();
  await page.getByRole('button', { name: new RegExp(pregunta.slice(0, 20)) }).first().click();
  await expect(page.getByTestId('badge-respaldo').filter({ hasText: 'Con respaldo' }).last()).toBeVisible({ timeout: 20_000 });
  await page.getByTestId('ir-reportes').click();
  const rep = page.getByTestId('reporte').filter({ hasText: 'pedregoso' }).first();
  await expect(rep).toHaveAttribute('data-estado', 'con_respaldo');
});

test('experto: solo recibe solicitudes de su área, al azar, y confirma con respaldo', async ({ page, request }) => {
  // garantiza al menos una solicitud de suelos pendiente (la cola de la base de desarrollo se va vaciando)
  const r = await request.post('/api/chat/mensajes', { headers: { 'X-Demo-Login': 'demo-agricultor' }, data: { texto: '¿Cómo mejoro el suelo de mi parcela?', idioma: 'es' } });
  expect(r.ok()).toBeTruthy();
  await limpio(page);
  await page.getByRole('button', { name: 'Suelos' }).click();
  await page.getByTestId('entrar-experto').click();
  await expect(page.getByTestId('areas-cola').locator('.area.mia')).toHaveCount(1);
  await page.getByTestId('tomar').click();
  const sol = page.getByTestId('solicitud');
  await expect(sol).toBeVisible();
  await expect(sol).toContainText('Suelos');
  await expect(sol.getByTestId('badge-respaldo')).toHaveAttribute('data-estado', 'solo_ia');
  await sol.getByRole('button', { name: /Confirmar con respaldo/ }).click();
  await page.getByLabel(/Fuente que respalda/).fill('INIFAP, guía del productor (prueba)');
  await page.getByTestId('enviar-revision').click();
  await expect(page.getByTestId('revision-hecha')).toBeVisible();
  await page.screenshot({ path: 'e2e/captura-experto.png', fullPage: true });
});

test('experto en patógenos no ve la cola de suelos como suya', async ({ page, request }) => {
  const r = await (await request.get('/api/experto/cola', { headers: EXPERTO('patogenos') })).json();
  expect(r.mis_areas).toEqual(['patogenos']);
  const s = await (await request.post('/api/experto/cola/siguiente', { headers: EXPERTO('patogenos'), data: {} })).json();
  if (!s.vacia) expect(s.area).toBe('patogenos');
  await limpio(page);
});

test('sin señal: el mensaje se guarda en el navegador y se envía al volver la red', async ({ page, context, request }) => {
  await productorEnChat(page);
  await page.evaluate(async () => {
    await navigator.serviceWorker.ready;
  });
  await page.reload();
  await expect(page.getByTestId('pantalla-chat')).toBeVisible();
  await context.setOffline(true);
  await expect(page.getByTestId('red')).toHaveAttribute('data-online', 'false');
  await page.reload(); // la app abre sin red gracias al service worker
  await expect(page.getByTestId('pantalla-chat')).toBeVisible();
  const texto = `¿Cuándo preparo el abono verde? ${Date.now()}`;
  await preguntar(page, texto);
  await expect(page.getByTestId('red')).toHaveAttribute('data-por-enviar', '1');
  await context.setOffline(false);
  await expect(page.getByTestId('red')).toHaveAttribute('data-por-enviar', '0', { timeout: 30_000 });
  await expect.poll(async () => {
    const r = await request.get('/api/chat/conversaciones', { headers: { 'X-Demo-Login': 'demo-agricultor' } });
    return (await r.json()).some((c: { titulo: string }) => texto.startsWith(c.titulo.slice(0, 40)));
  }).toBeTruthy();
});
