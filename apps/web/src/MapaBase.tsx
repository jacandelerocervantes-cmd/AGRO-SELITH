import { useQuery } from '@tanstack/react-query';
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type CapaInfo, type CapaValores } from './api';
import { idiomaActual } from './i18n';
import { bboxAlrededor, descargarRegion } from './teselas';

maplibregl.setWorkerUrl(workerUrl);

export type Fondo = 'satelite' | 'calles';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const OSM = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

/** Vistas regionales de la NASA (GIBS, sin llave). Ayudan a ver el contexto; los valores por celda vienen de la API. */
export const GIBS = [
  { id: 'gibs_imerg', layer: 'IMERG_Precipitation_Rate', ext: 'png', matriz: 'GoogleMapsCompatible_Level6', es: 'Lluvia regional (GPM IMERG)', en: 'Regional rainfall (GPM IMERG)' },
  { id: 'gibs_lst', layer: 'MODIS_Terra_Land_Surface_Temp_Day', ext: 'png', matriz: 'GoogleMapsCompatible_Level7', es: 'Temperatura regional (MODIS)', en: 'Regional temperature (MODIS)' },
  { id: 'gibs_ndvi', layer: 'MODIS_Terra_NDVI_8Day', ext: 'png', matriz: 'GoogleMapsCompatible_Level9', es: 'Vegetación regional (MODIS)', en: 'Regional vegetation (MODIS)' },
] as const;

const tilesGibs = (g: (typeof GIBS)[number]) =>
  `https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/${g.layer}/default/default/${g.matriz}/{z}/{y}/{x}.${g.ext}`;

export function crearMapa(el: HTMLElement, centro: [number, number], zoom: number, fondo: Fondo): maplibregl.Map {
  return new maplibregl.Map({
    container: el,
    center: centro,
    zoom,
    attributionControl: { compact: true },
    style: {
      version: 8,
      sources: {
        satelite: { type: 'raster', tiles: [ESRI], tileSize: 256, maxzoom: 19, attribution: 'Imágenes: Esri, Maxar, Earthstar Geographics' },
        calles: { type: 'raster', tiles: [OSM], tileSize: 256, maxzoom: 19, attribution: '© OpenStreetMap' },
        ...Object.fromEntries(GIBS.map((g) => [g.id, { type: 'raster' as const, tiles: [tilesGibs(g)], tileSize: 256, maxzoom: 8, attribution: 'NASA GIBS' }])),
      },
      layers: [
        { id: 'fondo-satelite', type: 'raster', source: 'satelite', layout: { visibility: fondo === 'satelite' ? 'visible' : 'none' } },
        { id: 'fondo-calles', type: 'raster', source: 'calles', layout: { visibility: fondo === 'calles' ? 'visible' : 'none' } },
        ...GIBS.map((g) => ({ id: g.id, type: 'raster' as const, source: g.id, paint: { 'raster-opacity': 0.65 }, layout: { visibility: 'none' as const } })),
      ],
    },
  });
}

export function ponerFondo(m: maplibregl.Map, fondo: Fondo) {
  m.setLayoutProperty('fondo-satelite', 'visibility', fondo === 'satelite' ? 'visible' : 'none');
  m.setLayoutProperty('fondo-calles', 'visibility', fondo === 'calles' ? 'visible' : 'none');
}

const RAMPAS: Record<string, [string, string]> = {
  ndvi_landsat: ['#a77d4a', '#2f7a2c'], ndvi_modis: ['#a77d4a', '#2f7a2c'], ndvi_s2: ['#a77d4a', '#2f7a2c'], lst_modis: ['#f2d36b', '#c4452f'], et_modis: ['#d6e6f2', '#1f4f8a'], imerg: ['#d6e6f2', '#1f4f8a'], smap: ['#e8d8a8', '#1f6a9c'],
  gldas: ['#e8d8a8', '#1f6a9c'], gldas_et: ['#d6e6f2', '#1f4f8a'], grace: ['#c4452f', '#1f6a9c'], lst: ['#f2d36b', '#c4452f'],
  srtm_pendiente_pct: ['#f2e8b0', '#9a4a1f'], srtm_elevacion: ['#9bc46f', '#8a6a3a'], gedi: ['#e8e2b0', '#2f5a2c'],
};

export function colorDe(capa: string, v: CapaValores): maplibregl.ExpressionSpecification {
  if (capa === 'vulnerabilidad') {
    return ['interpolate', ['linear'], ['coalesce', ['get', 'valor'], 0], 0, '#4f9a4a', 0.35, '#e0a42f', 0.6, '#c4452f'];
  }
  const [c0, c1] = RAMPAS[capa] ?? ['#e8d8a8', '#1f6a9c'];
  const lo = v.min ?? 0;
  const hi = v.max !== null && v.max > lo ? v.max : lo + 1;
  return ['interpolate', ['linear'], ['coalesce', ['get', 'valor'], lo], lo, c0, hi, c1];
}

/** Pinta (o quita) una capa de celdas de 100 m sobre el mapa. */
export function pintarCapa(m: maplibregl.Map, id: string | null, v: CapaValores | null) {
  for (const l of ['capa-celdas']) if (m.getLayer(l)) m.removeLayer(l);
  if (m.getSource('capa-celdas')) m.removeSource('capa-celdas');
  if (!id || !v || v.features.length === 0) return;
  m.addSource('capa-celdas', { type: 'geojson', data: { type: 'FeatureCollection', features: v.features } });
  m.addLayer({ id: 'capa-celdas', type: 'fill', source: 'capa-celdas', paint: { 'fill-color': colorDe(id, v), 'fill-opacity': 0.62, 'fill-outline-color': '#ffffff55' } });
}

export function ponerGibs(m: maplibregl.Map, id: string | null) {
  for (const g of GIBS) m.setLayoutProperty(g.id, 'visibility', g.id === id ? 'visible' : 'none');
}

type PanelProps = {
  parcelId: string | null;
  mapa: maplibregl.Map | null;
  fondo: Fondo;
  onFondo: (f: Fondo) => void;
};

/** Panel de capas: fondo, capas NASA por celda (desde la API) y vistas regionales NASA GIBS. */
export function CapasPanel({ parcelId, mapa, fondo, onFondo }: PanelProps) {
  const { t } = useTranslation();
  const lang = idiomaActual();
  const [capa, setCapa] = useState<string | null>(null);
  const [gibs, setGibs] = useState<string | null>(null);
  const lista = useQuery<CapaInfo[]>({ queryKey: ['capas'], queryFn: () => api('/capas') });
  const valores = useQuery<CapaValores>({
    queryKey: ['capa', capa, parcelId],
    queryFn: () => api(`/capas/${capa}${parcelId ? `?parcel_id=${parcelId}` : ''}`),
    enabled: !!capa,
  });
  const serie = useQuery<{ serie: { fecha: string; valor: number | null }[] }>({
    queryKey: ['capa-serie', capa, parcelId],
    queryFn: () => api(`/capas/${capa}/serie?parcel_id=${parcelId}`),
    enabled: !!capa && !!parcelId,
  });
  const [avance, setAvance] = useState<string | null>(null);
  const info = lista.data?.find((c) => c.id === capa);
  const guardarMapa = async () => {
    if (!mapa) return;
    const c = mapa.getCenter();
    setAvance('0');
    const r = await descargarRegion(bboxAlrededor(c.lng, c.lat, 1), fondo, (h, tot) => setAvance(`${h}/${tot}`));
    setAvance(`ok:${r.ok}/${r.total}`);
  };

  useEffect(() => {
    if (mapa && mapa.isStyleLoaded()) pintarCapa(mapa, capa, capa ? valores.data ?? null : null);
  }, [mapa, capa, valores.data]);
  useEffect(() => {
    if (mapa && mapa.isStyleLoaded()) ponerGibs(mapa, gibs);
  }, [mapa, gibs]);

  return (
    <div className="card capas" data-testid="capas">
      <b>{t('mapa.capas')}</b>
      <div className="seg-mini" role="group" aria-label={t('mapa.base')}>
        <button aria-pressed={fondo === 'satelite'} onClick={() => onFondo('satelite')}>{t('mapa.satelite')}</button>
        <button aria-pressed={fondo === 'calles'} onClick={() => onFondo('calles')}>{t('mapa.calles')}</button>
      </div>
      <button className="tool" onClick={() => void guardarMapa()} disabled={!mapa || (avance !== null && !avance.startsWith('ok'))} data-testid="guardar-mapa">
        <span>{avance === null ? t('mapa.guardarMapa') : avance.startsWith('ok') ? t('mapa.mapaGuardado', { n: avance.slice(3) }) : t('mapa.guardandoMapa', { n: avance })}</span>
      </button>
      <div className="capas-lista">
        {lista.data?.map((c) => (
          <button key={c.id} className="tool" role="switch" aria-checked={capa === c.id} data-on={capa === c.id}
            onClick={() => setCapa(capa === c.id ? null : c.id)} disabled={!c.disponible} title={c.disponible ? c.fuente : t('mapa.sinDatos')}>
            <span>{c.nombre[lang]}</span>
            <span className="etiquetas">{c.nasa && <i className="tag nasa">{t('mapa.nasa')}</i>}{c.sintetico && <i className="tag">{t('mapa.ejemplo')}</i>}</span>
          </button>
        ))}
        {GIBS.map((g) => (
          <button key={g.id} className="tool" role="switch" aria-checked={gibs === g.id} data-on={gibs === g.id} onClick={() => setGibs(gibs === g.id ? null : g.id)}>
            <span>{lang === 'en' ? g.en : g.es}</span>
            <span className="etiquetas"><i className="tag nasa">GIBS</i></span>
          </button>
        ))}
      </div>
      {capa && valores.data && info && (
        <div className="leyenda-capa" data-testid="leyenda-capa">
          <div className="barra-color" style={{ background: capa === 'vulnerabilidad' ? 'linear-gradient(90deg,#4f9a4a,#e0a42f,#c4452f)' : `linear-gradient(90deg,${(RAMPAS[capa] ?? ['#e8d8a8', '#1f6a9c']).join(',')})` }} />
          <div className="rango"><span>{valores.data.min?.toFixed(2) ?? '–'}</span><span>{valores.data.unidad}</span><span>{valores.data.max?.toFixed(2) ?? '–'}</span></div>
          <small>{t('mapa.fuente')}: {valores.data.fuente}{valores.data.sintetico ? ` · ${t('mapa.ejemplo')}` : ''}</small>
          {valores.data.resolucion_nativa_m && <small>{t('mapa.resolucion', { m: valores.data.resolucion_nativa_m })}</small>}
          <Tendencia puntos={serie.data?.serie ?? []} />

        </div>
      )}
    </div>
  );
}

/** Tendencia en el tiempo de la capa elegida para la parcela (línea de tiempo en miniatura). */
function Tendencia({ puntos }: { puntos: { fecha: string; valor: number | null }[] }) {
  const { t } = useTranslation();
  const v = puntos.filter((p): p is { fecha: string; valor: number } => p.valor !== null);
  if (v.length < 3) return null;
  const lo = Math.min(...v.map((p) => p.valor));
  const hi = Math.max(...v.map((p) => p.valor));
  const y = (x: number) => 38 - (hi === lo ? 0.5 : (x - lo) / (hi - lo)) * 34;
  const d = v.map((p, i) => `${(i / (v.length - 1)) * 240},${y(p.valor).toFixed(1)}`).join(' ');
  return (
    <div className="tendencia" data-testid="tendencia">
      <svg viewBox="0 0 240 42" role="img" aria-label={t('mapa.tendencia')}>
        <polyline points={d} fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
      <div className="rango"><span>{v[0].fecha}</span><span>{t('mapa.tendencia')}</span><span>{v[v.length - 1].fecha}</span></div>
    </div>
  );
}
