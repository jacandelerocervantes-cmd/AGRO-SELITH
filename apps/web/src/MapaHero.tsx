import type * as maplibregl from 'maplibre-gl';
import { useEffect, useRef, useState } from 'react';
import { GIBS, crearMapa, ponerGibs } from './MapaBase';

const TIZIMIN: [number, number] = [-88.15, 21.14];
const ORDEN = ['gibs_ndvi', 'gibs_lst', 'gibs_imerg'] as const;

/** Fondo vivo de la portada: imagen satelital de Tizimín con capas reales de la NASA (GIBS) que van rotando. */
export default function MapaHero({ lang }: { lang: 'es' | 'en' }) {
  const caja = useRef<HTMLDivElement>(null);
  const [mapa, setMapa] = useState<maplibregl.Map | null>(null);
  const [activa, setActiva] = useState(0);
  const quieto = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

  useEffect(() => {
    if (!caja.current) return;
    const m = crearMapa(caja.current, TIZIMIN, 9.2, 'satelite');
    for (const h of [m.dragPan, m.scrollZoom, m.boxZoom, m.dragRotate, m.keyboard, m.doubleClickZoom, m.touchZoomRotate]) h.disable();
    m.on('load', () => {
      setMapa(m);
      if (!quieto) m.easeTo({ center: [-88.12, 21.12], zoom: 11.4, bearing: 18, pitch: 30, duration: 40_000, essential: true });
    });
    return () => m.remove();
  }, [quieto]);

  useEffect(() => {
    if (!mapa) return;
    ponerGibs(mapa, ORDEN[activa]);
    const t = setTimeout(() => setActiva((a) => (a + 1) % ORDEN.length), 4500);
    return () => clearTimeout(t);
  }, [mapa, activa]);

  const g = GIBS.find((x) => x.id === ORDEN[activa])!;
  return (
    <>
      <div ref={caja} className="hero-mapa" aria-hidden="true" data-testid="hero-mapa" />
      <div className="hero-capa" role="status">
        <i aria-hidden="true" /> NASA GIBS · {lang === 'en' ? g.en : g.es}
      </div>
    </>
  );
}
