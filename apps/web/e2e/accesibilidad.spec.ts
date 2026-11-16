import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

/** Solo abre pantallas (sin escribir en la base): revisa WCAG 2 A/AA con axe, en español e inglés. */
async function auditar(page: Page, nombre: string) {
  const r = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).disableRules(['color-contrast-enhanced']).analyze();
  const graves = r.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  if (graves.length) console.log(nombre, JSON.stringify(graves.map((v) => ({ id: v.id, impacto: v.impact, nodos: v.nodes.length, ejemplo: v.nodes[0]?.html.slice(0, 140) })), null, 1));
  expect(graves, `${nombre}: violaciones graves de accesibilidad`).toEqual([]);
}

async function entrar(page: Page, sesion: object | null, lang = 'es') {
  await page.goto('/');
  await page.evaluate(([s, l]) => {
    localStorage.clear();
    localStorage.setItem('milpa.lang', l as string);
    if (s) sessionStorage.setItem('selith.sesion', JSON.stringify(s));
  }, [sesion, lang]);
  await page.reload();
}

for (const lang of ['es', 'en']) {
  test(`landing accesible (${lang})`, async ({ page }) => {
    await entrar(page, null, lang);
    await expect(page.getByTestId('landing')).toBeVisible();
    await auditar(page, `landing-${lang}`);
  });

  test(`mapa accesible (${lang})`, async ({ page }) => {
    await entrar(page, { login: 'demo-agricultor', rol: 'agricultor', areas: [], parcelaId: null }, lang);
    await expect(page.getByTestId('mapa')).toHaveAttribute('data-listo', '1');
    await auditar(page, `mapa-${lang}`);
  });

  test(`reportes accesible (${lang})`, async ({ page, request }) => {
    const ps = await (await request.get('/api/mis-parcelas', { headers: { 'X-Demo-Login': 'demo-agricultor' } })).json();
    await entrar(page, { login: 'demo-agricultor', rol: 'agricultor', areas: [], parcelaId: ps[0].id }, lang);
    await expect(page.getByTestId('pantalla-chat')).toBeVisible();
    await auditar(page, `chat-${lang}`);
    await page.getByTestId('ir-reportes').click();
    await expect(page.getByTestId('pantalla-reportes')).toBeVisible();
    await auditar(page, `reportes-${lang}`);
  });

  test(`experto accesible (${lang})`, async ({ page }) => {
    await entrar(page, { login: 'demo-experto-suelos', rol: 'extensionista', areas: ['suelos'], parcelaId: null }, lang);
    await expect(page.getByTestId('pantalla-experto')).toBeVisible();
    await auditar(page, `experto-${lang}`);
  });
}
