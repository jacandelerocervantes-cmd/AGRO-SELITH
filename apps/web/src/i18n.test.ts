import { describe, expect, it } from 'vitest';
import { recursos } from './i18n';

const claves = (o: unknown, pref = ''): string[] =>
  Array.isArray(o)
    ? [`${pref}[${o.length}]`]
    : typeof o === 'object' && o !== null
      ? Object.entries(o).flatMap(([k, v]) => claves(v, pref ? `${pref}.${k}` : k))
      : [pref];

describe('español e inglés', () => {
  it('tienen exactamente las mismas claves (y las mismas listas con el mismo largo)', () => {
    expect(claves(recursos.en).sort()).toEqual(claves(recursos.es).sort());
  });

  it('ningún texto está vacío salvo los que se dejan vacíos a propósito', () => {
    const vacios = (o: unknown, pref = ''): string[] =>
      typeof o === 'string' ? (o.trim() === '' ? [pref] : []) : typeof o === 'object' && o !== null ? Object.entries(o).flatMap(([k, v]) => vacios(v, `${pref}.${k}`)) : [];
    expect(vacios(recursos.es)).toEqual(['.respaldo.no_aplica']);
    expect(vacios(recursos.en)).toEqual(['.respaldo.no_aplica']);
  });

  it('el inglés no es una copia del español', () => {
    expect(recursos.en.landing.titulo).not.toBe(recursos.es.landing.titulo);
    expect(recursos.en.respaldo.solo_ia).toContain('AI only');
  });
});
