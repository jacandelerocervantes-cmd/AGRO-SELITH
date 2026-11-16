import { describe, expect, it } from 'vitest';
import { bboxAlrededor, latATile, lonATile, MAX_TESELAS, teselasParaBbox } from './teselas';

describe('teselas para el mapa sin señal', () => {
  it('el zoom 0 es una sola tesela', () => {
    expect(teselasParaBbox([-180, -85, 180, 85], 0, 0)).toEqual([{ z: 0, x: 0, y: 0 }]);
  });

  it('coincide con la tesela conocida de Tizimín en zoom 12 (x 1045, y 1801)', () => {
    // 21.1427 N, -88.1503 W
    expect(lonATile(-88.1503, 12)).toBe(1045);
    expect(latATile(21.1427, 12)).toBe(1801);
  });

  it('cada zoom agrega más teselas y todas contienen el punto central en su rango', () => {
    const b = bboxAlrededor(-88.1503, 21.1427, 1);
    const t = teselasParaBbox(b, 13, 16);
    const porZoom = (z: number) => t.filter((x) => x.z === z).length;
    expect(porZoom(14)).toBeGreaterThan(porZoom(13));
    expect(porZoom(16)).toBeGreaterThan(porZoom(15));
    for (const z of [13, 14, 15, 16]) {
      const cx = lonATile(-88.1503, z), cy = latATile(21.1427, z);
      expect(t.some((x) => x.z === z && x.x === cx && x.y === cy)).toBe(true);
    }
  });

  it('una región de 1 km de radio hasta zoom 17 es pequeña, no una descarga masiva', () => {
    const n = teselasParaBbox(bboxAlrededor(-88.1503, 21.1427, 1), 13, 17).length;
    expect(n).toBeGreaterThan(50);
    expect(n).toBeLessThan(MAX_TESELAS * 3);
  });

  it('el bbox alrededor mide aproximadamente el radio pedido', () => {
    const [w, s, e, n] = bboxAlrededor(-88.15, 21.14, 1);
    expect((n - s) * 110.57).toBeCloseTo(2, 1);
    expect((e - w) * 111.32 * Math.cos((21.14 * Math.PI) / 180)).toBeCloseTo(2, 1);
  });
});
