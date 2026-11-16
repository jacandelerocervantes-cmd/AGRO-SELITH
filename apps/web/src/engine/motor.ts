/**
 * Motor reducido del cliente: portación fiel de packages/engine (Python) para uso sin señal.
 * Misma programación dinámica exacta (k-best), mismos filtros duros y mismo puntaje.
 * Paridad verificada contra casos de oro generados por Python (motor.test.ts).
 * No incluye Monte Carlo: sin señal no hay P10/P50/P90 (se muestran solo con servidor).
 */
import datos from './data.json';

export const CRITERIOS = [
  'agua_eficiencia', 'fijacion_n', 'materia_organica', 'control_erosion', 'infiltracion',
  'ruptura_plagas', 'valor_forrajero', 'ingreso_neto', 'estabilidad_ingreso', 'proteccion_etapas',
] as const;
export const PENALIZACIONES = ['barbecho_excesivo', 'concentracion_riesgo', 'dependencia_monocultivo'] as const;

const ETIQUETAS: Record<string, string> = {
  agua_eficiencia: 'Uso eficiente del agua',
  fijacion_n: 'Nitrógeno que deja en el suelo',
  materia_organica: 'Materia orgánica del suelo',
  control_erosion: 'Protección contra la erosión',
  infiltracion: 'Entrada de agua al suelo',
  ruptura_plagas: 'Corta el ciclo de plagas',
  valor_forrajero: 'Forraje para animales',
  ingreso_neto: 'Ingreso',
  estabilidad_ingreso: 'Ingreso estable año con año',
  proteccion_etapas: 'Protege floración y llenado de la canícula',
  barbecho_excesivo: 'Descanso sin cobertura',
  concentracion_riesgo: 'Riesgo concentrado en ciclos seguidos',
  dependencia_monocultivo: 'Depender de un solo cultivo',
};

export type Opcion = {
  id: string; nombre: string; familias: string[]; hospedantes: string[]; esBarbecho: boolean;
  esBarbechoDesnudo: boolean; aguaMm: number; toleranciaSequia: number; sensibilidadCanicula: number;
  ingresoMxnHa: number; nAporteKgHa: number; moAporte: number; utilidades: Record<string, number>;
  capacidadAbsorcionHa: number | null;
};
export type Regla = { id: string; tipo: string; selectorA: string; selectorB: string; aniosMin: number; severidad: number };
export type EscenarioMotor = { id: string; severidadCanicula: number; factorDemandaAgua: number; factorEstresIngreso: number; toleranciaMinima: number };
export type PrioridadesMotor = { agua: number; forraje: number; suelo: number; ingreso: number };

export const K = datos as unknown as {
  baseId: string; cuotaMax: number; pesosDefecto: Record<string, number>; lambdas: Record<string, number>;
  grupos: Record<string, string[]>; opciones: Opcion[]; reglas: Regla[]; escenarios: Record<string, EscenarioMotor>;
};

export type FactorLocal = { factor: string; valor_norm: number; peso: number; contribucion: number; explicacion: string };
export type PlanLocal = {
  ranking: number; secuencia: string[]; score: number; aguaTotalMm: number; aguaBaseMm: number;
  ingresoEstimado: number; deltaMo: number; deltaN: number; riesgoPlaga: number;
  factores: FactorLocal[]; porQue: string;
};

const clamp = (x: number) => (x < 0 ? 0 : x > 1 ? 1 : x);

/** sum() de Python 3.12 (suma compensada de Neumaier): necesaria para que los empates se rompan igual. */
function pysum(xs: number[]): number {
  let s = 0, c = 0;
  for (const x of xs) {
    const t = s + x;
    c += Math.abs(s) >= Math.abs(x) ? s - t + x : x - t + s;
    s = t;
  }
  return s + c;
}

export function pesosDesde(p: PrioridadesMotor): Record<string, number> {
  const pesos = { ...K.pesosDefecto };
  for (const [grupo, crits] of Object.entries(K.grupos)) {
    for (const c of crits) pesos[c] = (K.pesosDefecto[c] * p[grupo as keyof PrioridadesMotor]) / 3;
  }
  return pesos;
}

function coincide(sel: string, o: Opcion): boolean {
  const i = sel.indexOf(':');
  const tipo = sel.slice(0, i);
  const val = sel.slice(i + 1);
  if (tipo === 'id') return o.id === val;
  if (tipo === 'fam') return o.familias.includes(val);
  if (tipo === 'host') return o.hospedantes.includes(val);
  throw new Error(`selector inválido: ${sel}`);
}

export function vulnerabilidadBase(escenario: string): { indice: number; nivel: 'ok' | 'mid' | 'bad' } {
  const base = K.opciones.find((o) => o.id === K.baseId)!;
  const indice = base.sensibilidadCanicula * K.escenarios[escenario].severidadCanicula;
  return { indice, nivel: indice < 0.25 ? 'ok' : indice < 0.5 ? 'mid' : 'bad' };
}

export function recomendarLocal(
  escenarioId: string, horizonteAnios: number, areaHa: number, prio: PrioridadesMotor, k = 3,
): PlanLocal[] {
  const ops = K.opciones;
  const esc = K.escenarios[escenarioId];
  const pesos = pesosDesde(prio);
  const n = horizonteAnios;
  const base = ops.find((o) => o.id === K.baseId)!;
  const aguaBase = Array.from({ length: n }, () => base.aguaMm * esc.factorDemandaAgua);
  const maxIng = Math.max(0, ...ops.map((o) => o.ingresoMxnHa)) || 1;
  const H = Math.max(1, Math.min(Math.max(1, ...K.reglas.map((r) => r.aniosMin)), Math.max(n - 1, 1)));

  const okLocal = (o: Opcion, t: number) => {
    if (!o.esBarbecho && o.toleranciaSequia < esc.toleranciaMinima) return false;
    if (o.aguaMm * esc.factorDemandaAgua > aguaBase[t] + 1e-9) return false;
    const cap = o.capacidadAbsorcionHa;
    return cap === null || areaHa <= cap * K.cuotaMax + 1e-9;
  };
  const permitidas = Array.from({ length: n }, (_, t) => ops.flatMap((o, i) => (okLocal(o, t) ? [i] : [])));

  const golpes = (hist: number[], nuevo: number, soloDuras: boolean) => {
    const no = ops[nuevo];
    for (let d = 1; d <= hist.length; d++) {
      const e = ops[hist[hist.length - d]];
      for (const r of K.reglas) {
        if (soloDuras && r.severidad < 3) continue;
        if (d <= r.aniosMin && coincide(r.selectorA, e) && coincide(r.selectorB, no)) return true;
      }
    }
    return false;
  };

  const terminos = (hist: number[], i: number, sev: number, ingMult: number) => {
    const o = ops[i];
    const u: Record<string, number> = {};
    for (const c of CRITERIOS) u[c] = clamp(o.utilidades[c] ?? 0);
    u.proteccion_etapas = clamp(1 - o.sensibilidadCanicula * sev);
    const estres = 1 - esc.factorEstresIngreso * sev * o.sensibilidadCanicula;
    u.ingreso_neto = clamp((o.ingresoMxnHa / maxIng) * estres * ingMult);
    if (golpes(hist, i, false)) u.ruptura_plagas = 0;
    const prev = hist.length ? ops[hist[hist.length - 1]] : null;
    const pen: Record<string, number> = { barbecho_excesivo: 0, concentracion_riesgo: 0, dependencia_monocultivo: 0 };
    if (o.esBarbecho) {
      const seguido = prev !== null && prev.esBarbecho;
      pen.barbecho_excesivo = o.esBarbechoDesnudo ? (seguido ? 1 : 0.5) : seguido ? 0.5 : 0;
    }
    if (prev !== null && o.sensibilidadCanicula > 0.7 && prev.sensibilidadCanicula > 0.7) pen.concentracion_riesgo = 1;
    if (prev !== null && prev.id === o.id && !o.esBarbecho) pen.dependencia_monocultivo = 1;
    return { u, pen };
  };

  const puntajeSlot = (u: Record<string, number>, pen: Record<string, number>) => {
    return (
      pysum(CRITERIOS.map((c) => (pesos[c] ?? 0) * u[c])) -
      pysum(PENALIZACIONES.map((c) => (K.lambdas[c] ?? 0) * pen[c]))
    );
  };

  // ---- DP k-best exacta ----
  type Ruta = [number, number[]];
  const cmp = (x: Ruta, y: Ruta) => {
    if (x[0] !== y[0]) return y[0] - x[0];
    for (let j = 0; j < Math.min(x[1].length, y[1].length); j++) if (x[1][j] !== y[1][j]) return x[1][j] - y[1][j];
    return 0;
  };
  let estados = new Map<string, { hist: number[]; rutas: Ruta[] }>([['', { hist: [], rutas: [[0, []]] }]]);
  for (let t = 0; t < n; t++) {
    const nuevos = new Map<string, { hist: number[]; rutas: Ruta[] }>();
    for (const { hist, rutas } of estados.values()) {
      for (const i of permitidas[t]) {
        if (golpes(hist, i, true)) continue;
        const { u, pen } = terminos(hist, i, esc.severidadCanicula, 1);
        const s = puntajeSlot(u, pen);
        const nh = [...hist, i].slice(-H);
        const key = nh.join(',');
        let cub = nuevos.get(key);
        if (!cub) nuevos.set(key, (cub = { hist: nh, rutas: [] }));
        for (const [sc, seq] of rutas) cub.rutas.push([sc + s, [...seq, i]]);
      }
    }
    for (const c of nuevos.values()) {
      c.rutas.sort(cmp);
      c.rutas.length = Math.min(c.rutas.length, k);
    }
    estados = nuevos;
  }
  const todos = [...estados.values()].flatMap((e) => e.rutas).sort(cmp).slice(0, k);

  // ---- evaluación y explicación ----
  return todos.map(([, seq], r) => {
    const sumU = Object.fromEntries(CRITERIOS.map((c) => [c, 0])) as Record<string, number>;
    const sumP = Object.fromEntries(PENALIZACIONES.map((c) => [c, 0])) as Record<string, number>;
    let hist: number[] = [];
    let agua = 0, ing = 0, dMo = 0, dN = 0;
    for (const i of seq) {
      const { u, pen } = terminos(hist, i, esc.severidadCanicula, 1);
      for (const c of CRITERIOS) sumU[c] += u[c];
      for (const c of PENALIZACIONES) sumP[c] += pen[c];
      const o = ops[i];
      agua += o.aguaMm * esc.factorDemandaAgua;
      ing += o.ingresoMxnHa * areaHa * (1 - esc.factorEstresIngreso * esc.severidadCanicula * o.sensibilidadCanicula);
      dMo += o.moAporte;
      dN += o.nAporteKgHa;
      hist = [...hist, i].slice(-H);
    }
    const factores: FactorLocal[] = [];
    const expl = (f: string, c: number) => `${ETIQUETAS[f]}: ${c >= 0 ? 'suma' : 'resta'} ${Math.abs(c).toFixed(2)} al puntaje`;
    for (const c of CRITERIOS) {
      const v = sumU[c] / n, w = pesos[c] ?? 0;
      factores.push({ factor: c, valor_norm: v, peso: w, contribucion: w * v, explicacion: expl(c, w * v) });
    }
    for (const c of PENALIZACIONES) {
      const v = sumP[c] / n, lam = K.lambdas[c] ?? 0;
      factores.push({ factor: c, valor_norm: v, peso: lam, contribucion: -lam * v, explicacion: expl(c, -lam * v) });
    }
    const score = pysum(factores.map((f) => f.contribucion));
    const top = [...factores].sort((a, b) => b.contribucion - a.contribucion).slice(0, 2)
      .map((f) => f.explicacion.split(':')[0].toLowerCase());
    return {
      ranking: r + 1, secuencia: seq.map((i) => ops[i].id), score,
      aguaTotalMm: agua, aguaBaseMm: aguaBase.reduce((a, b) => a + b, 0), ingresoEstimado: ing, deltaMo: dMo, deltaN: dN,
      riesgoPlaga: 1 - sumU.ruptura_plagas / n, factores, porQue: `Aporta sobre todo en: ${top.join(' y ')}.`,
    };
  });
}
