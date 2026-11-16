import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, type Reporte } from './api';
import { LangToggle, fecha } from './comunes';
import { idiomaActual } from './i18n';
import { useSession } from './store';
import { hablar } from './voz';

const AREAS = ['suelos', 'patogenos', 'agua', 'clima', 'mercado', 'cultivos'] as const;

/** Vista de reportes: respuestas que un experto de su área ya revisó (con respaldo) o retiró (revocadas). */
export default function Reportes() {
  const { t } = useTranslation();
  const lang = idiomaActual();
  const { ir } = useSession();
  const [filtro, setFiltro] = useState<string>('todos');
  const q = useQuery<Reporte[]>({ queryKey: ['reportes'], queryFn: () => api('/chat/reportes'), staleTime: 0 });
  const filas = (q.data ?? []).filter((r) => filtro === 'todos' || r.area === filtro);

  return (
    <div className="reportes" data-testid="pantalla-reportes">
      <header className="barra-sup">
        <button className="big" onClick={() => ir('chat')}>{t('reportes.volver')}</button>
        <LangToggle />
      </header>
      <h1>{t('reportes.titulo')}</h1>
      <p className="sub">{t('reportes.sub')}</p>
      <div className="chips">
        <button className="chip" aria-pressed={filtro === 'todos'} onClick={() => setFiltro('todos')}>{t('reportes.todos')}</button>
        {AREAS.map((a) => <button key={a} className="chip" aria-pressed={filtro === a} onClick={() => setFiltro(a)}>{t(`areas.${a}`)}</button>)}
      </div>
      {filas.length === 0 && <p className="vacio">{t('reportes.vacio')}</p>}
      <div className="lista-reportes">
        {filas.map((r) => {
          const revocada = r.estado_respaldo === 'revocada';
          const texto = r.texto_corregido ?? r.respuesta;
          return (
            <article key={r.id} className={`card reporte ${revocada ? 'revocada' : ''}`} data-testid="reporte" data-estado={r.estado_respaldo}>
              <div className="fila"><span className={`badge ${r.estado_respaldo}`}>{revocada ? t('respaldo.revocada') : `✓ ${t('respaldo.con_respaldo', { area: t(`areas.${r.area}`) })}`}</span></div>
              <h2>{r.pregunta ?? t('reportes.pregunta')}</h2>
              <small className="nota">{t('reportes.revisado', { f: fecha(r.revisado_at, lang) })}{r.fuentes.length ? ` · ${r.fuentes.length} ${t('respaldo.fuentes').toLowerCase()}` : ''}</small>
              <p>{revocada ? `${t('respaldo.motivo')}: ${r.motivo}` : texto}</p>
              {r.fuentes.length > 0 && <small className="nota">{r.fuentes.join(' · ')}</small>}
              {!revocada && <button className="big" onClick={() => hablar(texto, lang)}>{t('chat.escuchar')}</button>}
            </article>
          );
        })}
      </div>
    </div>
  );
}
