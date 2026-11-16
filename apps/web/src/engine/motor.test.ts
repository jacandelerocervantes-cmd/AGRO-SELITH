import { describe, expect, it } from 'vitest';
import golden from './golden.json';
import { recomendarLocal } from './motor';

type Caso = {
  escenario: string; areaHa: number; prioridades: { agua: number; forraje: number; suelo: number; ingreso: number };
  planes: { secuencia: string[]; score: number; aguaTotalMm: number; ingresoEstimado: number; deltaMo: number; deltaN: number; riesgoPlaga: number; factores: Record<string, number> }[];
};

describe('paridad del motor TS con el motor Python (casos de oro)', () => {
  const casos = golden as Caso[];
  it('hay casos para todos los escenarios', () => {
    expect(new Set(casos.map((c) => c.escenario)).size).toBe(4);
    expect(casos.length).toBeGreaterThanOrEqual(32);
  });
  for (const [i, c] of casos.entries()) {
    it(`caso ${i}: ${c.escenario} ${JSON.stringify(c.prioridades)} ${c.areaHa} ha`, () => {
      const planes = recomendarLocal(c.escenario, 4, c.areaHa, c.prioridades);
      expect(planes.map((p) => p.secuencia)).toEqual(c.planes.map((p) => p.secuencia));
      planes.forEach((p, j) => {
        const g = c.planes[j];
        expect(p.score).toBeCloseTo(g.score, 9);
        expect(p.aguaTotalMm).toBeCloseTo(g.aguaTotalMm, 6);
        expect(p.ingresoEstimado).toBeCloseTo(g.ingresoEstimado, 6);
        expect(p.deltaMo).toBeCloseTo(g.deltaMo, 9);
        expect(p.deltaN).toBeCloseTo(g.deltaN, 9);
        expect(p.riesgoPlaga).toBeCloseTo(g.riesgoPlaga, 9);
        for (const f of p.factores) expect(f.contribucion).toBeCloseTo(g.factores[f.factor], 9);
        expect(p.factores.reduce((a, f) => a + f.contribucion, 0)).toBeCloseTo(p.score, 9);
        expect(p.aguaTotalMm).toBeLessThanOrEqual(p.aguaBaseMm + 1e-6);
      });
    });
  }
});
