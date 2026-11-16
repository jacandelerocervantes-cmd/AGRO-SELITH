/** Mapa sin señal: calcula y descarga las teselas de una región pequeña para que el service worker las guarde. */

export type Bbox = [number, number, number, number]; // [oeste, sur, este, norte]

const tope = (n: number, z: number) => Math.min(Math.max(n, 0), 2 ** z - 1);
export const lonATile = (lon: number, z: number) => tope(Math.floor(((lon + 180) / 360) * 2 ** z), z);
export const latATile = (lat: number, z: number) => {
  const r = (lat * Math.PI) / 180;
  return tope(Math.floor(((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z), z);
};

export type Tesela = { z: number; x: number; y: number };

/** Teselas que cubren el bbox entre los zooms dados. */
export function teselasParaBbox(b: Bbox, zmin: number, zmax: number): Tesela[] {
  const out: Tesela[] = [];
  for (let z = zmin; z <= zmax; z++) {
    const x0 = lonATile(b[0], z), x1 = lonATile(b[2], z);
    const y0 = latATile(b[3], z), y1 = latATile(b[1], z);
    for (let x = x0; x <= x1; x++) for (let y = y0; y <= y1; y++) out.push({ z, x, y });
  }
  return out;
}

/** Margen en grados alrededor de un punto para ~ radioKm (aprox. a latitud lat). */
export function bboxAlrededor(lon: number, lat: number, radioKm: number): Bbox {
  const dLat = radioKm / 110.57;
  const dLon = radioKm / (111.32 * Math.cos((lat * Math.PI) / 180));
  return [lon - dLon, lat - dLat, lon + dLon, lat + dLat];
}

export const URL_SATELITE = (t: Tesela) => `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${t.z}/${t.y}/${t.x}`;
export const URL_CALLES = (t: Tesela) => `https://tile.openstreetmap.org/${t.z}/${t.x}/${t.y}.png`;

/** Tope de teselas por descarga: es una región pequeña pedida por la persona, no una descarga masiva. */
export const MAX_TESELAS = 450;

/** Descarga las teselas (el service worker las guarda al verlas pasar). Devuelve cuántas se pudieron pedir. */
export async function descargarRegion(
  b: Bbox,
  fondo: 'satelite' | 'calles',
  alAvanzar: (hechas: number, total: number) => void,
  zmin = 13,
  zmax = 17,
): Promise<{ total: number; ok: number }> {
  let zmaxUsado = zmax;
  while (teselasParaBbox(b, zmin, zmaxUsado).length > MAX_TESELAS && zmaxUsado > zmin) zmaxUsado--;
  const lista = teselasParaBbox(b, zmin, zmaxUsado);
  const url = fondo === 'satelite' ? URL_SATELITE : URL_CALLES;
  let ok = 0;
  let hechas = 0;
  const cola = [...lista];
  const trabajador = async () => {
    for (let t = cola.pop(); t; t = cola.pop()) {
      try {
        const r = await fetch(url(t)); // con CORS, igual que lo pide MapLibre, para que la copia guardada sirva
        if (!r.ok) throw new Error('tesela no disponible');
        ok++;
      } catch {
        /* sin red: se cuenta como no descargada */
      }
      alAvanzar(++hechas, lista.length);
    }
  };
  await Promise.all([trabajador(), trabajador(), trabajador(), trabajador()]);
  return { total: lista.length, ok };
}
