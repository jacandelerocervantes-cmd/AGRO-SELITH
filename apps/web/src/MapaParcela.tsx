import { useQuery, useQueryClient } from '@tanstack/react-query';
import area from '@turf/area';
import kinks from '@turf/kinks';
import * as maplibregl from 'maplibre-gl';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, post, type Parcela } from './api';
import { LangToggle } from './comunes';
import { CapasPanel, crearMapa, ponerFondo, type Fondo } from './MapaBase';
import { useSession } from './store';

type LngLat = [number, number];
const CENTRO: LngLat = [-88.1503, 21.1427]; // Tizimín, Yucatán (piloto)

const poligono = (v: LngLat[]): GeoJSON.Feature<GeoJSON.Polygon> => ({
  type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [[...v, v[0]]] },
});

/** Paso 1: el productor delimita su parcela sobre la imagen satelital y ve su superficie en m². */
export default function MapaParcela() {
  const { t } = useTranslation();
  const { setParcela, ir, parcelaId, salir } = useSession();
  const qc = useQueryClient();
  const el = useRef<HTMLDivElement>(null);
  const [mapa, setMapa] = useState<maplibregl.Map | null>(null);
  const marcadores = useRef<maplibregl.Marker[]>([]);
  const [vertices, setVertices] = useState<LngLat[]>([]);
  const [fondo, setFondo] = useState<Fondo>('satelite');
  const [nombre, setNombre] = useState(t('mapa.nombreDef'));
  const [busca, setBusca] = useState('');
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState('');
  const existentes = useQuery<Parcela[]>({ queryKey: ['mis-parcelas'], queryFn: () => api('/mis-parcelas') });

  useEffect(() => {
    if (!el.current) return;
    const m = crearMapa(el.current, CENTRO, 14, 'satelite');
    m.on('load', () => {
      m.addSource('dibujo', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      m.addLayer({ id: 'dibujo-relleno', type: 'fill', source: 'dibujo', filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': '#e0a42f', 'fill-opacity': 0.4 } });
      m.addLayer({ id: 'dibujo-linea', type: 'line', source: 'dibujo', paint: { 'line-color': '#ffffff', 'line-width': 3 } });
      m.addSource('existentes', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
      m.addLayer({ id: 'existentes-linea', type: 'line', source: 'existentes', paint: { 'line-color': '#4aa3ff', 'line-width': 3 } });
      setMapa(m);
    });
    m.on('click', (e) => setVertices((v) => [...v, [e.lngLat.lng, e.lngLat.lat]]));
    return () => m.remove();
  }, []);

  useEffect(() => {
    if (mapa) ponerFondo(mapa, fondo);
  }, [mapa, fondo]);

  // Dibujo: línea/polígono y esquinas arrastrables
  useEffect(() => {
    if (!mapa) return;
    const feats: GeoJSON.Feature[] = [];
    if (vertices.length >= 3) feats.push(poligono(vertices));
    else if (vertices.length === 2) feats.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: vertices } });
    (mapa.getSource('dibujo') as maplibregl.GeoJSONSource).setData({ type: 'FeatureCollection', features: feats });
    marcadores.current.forEach((x) => x.remove());
    marcadores.current = vertices.map((p, i) => {
      const d = document.createElement('div');
      d.className = 'esquina';
      const mk = new maplibregl.Marker({ element: d, draggable: true }).setLngLat(p).addTo(mapa);
      mk.on('dragend', () => {
        const ll = mk.getLngLat();
        setVertices((v) => v.map((x, j) => (j === i ? [ll.lng, ll.lat] : x)));
      });
      return mk;
    });
  }, [mapa, vertices]);

  // Parcelas ya guardadas
  useEffect(() => {
    if (!mapa || !existentes.data) return;
    (mapa.getSource('existentes') as maplibregl.GeoJSONSource).setData({
      type: 'FeatureCollection', features: existentes.data.map((p) => ({ type: 'Feature', properties: { id: p.id }, geometry: p.geom })),
    });
  }, [mapa, existentes.data]);

  const m2 = vertices.length >= 3 ? area(poligono(vertices)) : 0;
  const cruzado = vertices.length >= 4 && kinks(poligono(vertices)).features.length > 0;
  const puedeGuardar = vertices.length >= 3 && !cruzado && !guardando;

  const buscar = useCallback(async () => {
    if (!busca.trim() || !mapa) return;
    try {
      const r = await fetch(`https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(busca)}`);
      const j = (await r.json()) as { lat: string; lon: string }[];
      if (j[0]) mapa.flyTo({ center: [Number(j[0].lon), Number(j[0].lat)], zoom: 16 });
    } catch {
      /* sin red: se queda donde está */
    }
  }, [busca, mapa]);

  async function guardar() {
    setGuardando(true);
    setError('');
    try {
      const p = await post<Parcela>('/mis-parcelas', { nombre: nombre || t('mapa.nombreDef'), geojson: poligono(vertices).geometry });
      try {
        await post(`/mis-parcelas/${p.id}/capas`, {});
      } catch {
        /* las capas se pueden preparar después */
      }
      await qc.invalidateQueries({ queryKey: ['mis-parcelas'] });
      setParcela(p.id);
      ir('chat');
    } catch (e) {
      setError(e instanceof Error ? e.message : t('mapa.errorGuardar'));
      setGuardando(false);
    }
  }

  return (
    <div className="pantalla-mapa" data-testid="pantalla-mapa">
      <div ref={el} className="mapa-lleno" data-testid="mapa" data-listo={mapa ? '1' : '0'} />
      <div className="sup">
        <button className="big" data-testid="inicio" onClick={salir}>← {t('nav.inicio')}</button>
        <div className="card marca"><b>{t('app')}</b><span>{t('mapa.paso')}</span></div>
        <div className="card buscador">
          <input aria-label={t('mapa.buscar')} placeholder={t('mapa.buscar')} value={busca} onChange={(e) => setBusca(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void buscar()} />
        </div>
        <LangToggle />
      </div>

      <div className="card herramientas">
        <b>{t('mapa.dibujar')}</b>
        <button className="tool" data-on="true">{t('mapa.marcar')}</button>
        <button className="tool" onClick={() => setVertices((v) => v.slice(0, -1))} disabled={!vertices.length}>{t('mapa.deshacer')}</button>
        <button className="tool" onClick={() => setVertices([])} disabled={!vertices.length}>{t('mapa.borrar')}</button>
        <label className="campo">{t('mapa.nombre')}<input value={nombre} onChange={(e) => setNombre(e.target.value)} /></label>
      </div>

      <div className="derecha"><CapasPanel parcelId={parcelaId} mapa={mapa} fondo={fondo} onFondo={setFondo} /></div>

      <div className="card barra-inf">
        <div className="medida">
          <small>{t('mapa.tamano')}</small>
          <strong data-testid="m2">{Math.round(m2).toLocaleString()} m²</strong>
          <span>{t('mapa.hectareas', { ha: (m2 / 10_000).toFixed(2), n: vertices.length })}</span>
        </div>
        <p className="ayuda">{cruzado ? t('mapa.cruzado') : vertices.length < 3 ? `${t('mapa.ayuda')} ${vertices.length ? t('mapa.minimo') : ''}` : t('mapa.ayuda')}</p>
        {error && <p role="alert" className="error">{error}</p>}
        <div className="acciones-inf">
          {existentes.data && existentes.data.length > 0 && (
            <button className="big" onClick={() => { setParcela(existentes.data![0].id); ir('chat'); }}>
              {existentes.data[0].nombre} · {Math.round(existentes.data[0].area_m2 ?? 0).toLocaleString()} m²
            </button>
          )}
          <button className="big p" disabled={!puedeGuardar} onClick={() => void guardar()} data-testid="guardar-parcela">
            {guardando ? t('mapa.preparando') : t('mapa.guardar')}
          </button>
        </div>
      </div>
    </div>
  );
}
