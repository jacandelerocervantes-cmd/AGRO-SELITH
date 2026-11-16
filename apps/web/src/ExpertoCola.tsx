import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, post, type Cola, type Solicitud } from './api';
import { BadgeRespaldo, LangToggle } from './comunes';
import Estrategias from './Estrategias';
import { idiomaActual } from './i18n';
import { RedEstado } from './offline/Red';
import { useSession } from './store';
import { useDictado } from './voz';

type Modo = 'confirmar' | 'corregir' | 'revocar';
const AREAS = ['suelos', 'patogenos', 'agua', 'clima', 'mercado', 'cultivos'] as const;

/** Vista del experto: también es una conversación, pero su contenido es una cola de solicitudes de SU área,
 *  repartida al azar. La cola total se subdivide por área de agronomía. */
export default function ExpertoCola() {
  const { t } = useTranslation();
  const lang = idiomaActual();
  const qc = useQueryClient();
  const { areas, salir, login } = useSession();
  const [sol, setSol] = useState<Solicitud | null>(null);
  const [modo, setModo] = useState<Modo>('confirmar');
  const [texto, setTexto] = useState('');
  const [fuentes, setFuentes] = useState('');
  const [hecho, setHecho] = useState(false);

  const cola = useQuery<Cola>({ queryKey: ['cola'], queryFn: () => api('/experto/cola'), refetchInterval: 10_000, staleTime: 0 });
  const dictado = useDictado(lang, (x) => setTexto((p) => `${p} ${x}`.trim()));

  const tomar = useMutation({
    mutationFn: () => post<Solicitud>('/experto/cola/siguiente', {}),
    onSuccess: (s) => {
      setSol(s.vacia ? null : s);
      setHecho(false);
      setTexto('');
      setFuentes('');
      setModo('confirmar');
      void qc.invalidateQueries({ queryKey: ['cola'] });
    },
  });
  const revisar = useMutation({
    mutationFn: () =>
      post(`/experto/solicitudes/${sol?.id}/revision`, {
        decision: modo,
        texto_corregido: modo === 'corregir' ? texto : null,
        motivo: modo === 'revocar' ? texto : null,
        fuentes: fuentes.split('\n').map((x) => x.trim()).filter(Boolean),
      }),
    onSuccess: () => {
      setHecho(true);
      void qc.invalidateQueries({ queryKey: ['cola'] });
    },
  });

  const puedeEnviar = modo === 'confirmar' || texto.trim().length > 2;
  const miArea = areas[0];

  return (
    <div className="chat-layout" data-testid="pantalla-experto">
      <aside className="lateral">
        <b className="logo">{t('app')}</b>
        <small>{login}</small>
        <div className="especialidad"><small>{t('experto.miEspecialidad')}</small><b>{areas.map((a) => t(`areas.${a}`)).join(', ')}</b>
          <span>{t('experto.pendientes', { n: cola.data?.pendientes_mis_areas ?? 0 })}</span></div>
        <small className="sec">{t('experto.colaTotal')}</small>
        <div className="areas" data-testid="areas-cola">
          {AREAS.map((a) => (
            <div key={a} className={`area ${areas.includes(a) ? 'mia' : ''}`} data-area={a}>
              <span>{t(`areas.${a}`)} {areas.includes(a) ? t('experto.mia') : ''}</span><b>{cola.data?.areas_totales[a] ?? 0}</b>
            </div>
          ))}
        </div>
        <small className="nota">{t('experto.nota')}</small>
        <button className="big p" disabled={tomar.isPending} onClick={() => tomar.mutate()} data-testid="tomar">{t('experto.tomar')}</button>
        <div className="pie-lateral">
          <RedEstado etiqueta={{ con: lang === 'en' ? 'Online' : 'Con señal', sin: lang === 'en' ? 'Offline' : 'Sin señal', porEnviar: lang === 'en' ? 'to send' : 'por enviar' }} />
          <LangToggle />
          <button className="item" onClick={salir}>{t('nav.salir')}</button>
        </div>
      </aside>

      <main className="hilo">
        <div className="aviso-demo">{t('demoNota')}</div>
        {!sol && <div className="bienvenida"><p>{tomar.data?.vacia ? t('experto.vacia') : t('experto.nota')}</p></div>}
        {sol && (
          <div className="mensajes" data-testid="solicitud">
            <div className="barra-sol"><b>{t('experto.solicitud')}</b><span className="badge con_respaldo">{t(`areas.${sol.area}`)}</span><small>{t('experto.azar')}</small></div>
            <div className="card contexto"><span><b>{t('experto.contexto')}:</b> {sol.parcela ?? '—'}{sol.area_m2 ? ` · ${Math.round(sol.area_m2).toLocaleString()} m²` : ''}</span></div>
            <div className="msg usuario"><div className="burbuja"><small>{t('experto.productor')}{sol.via_voz ? ` (${t('experto.porVoz')})` : ''}</small><p>{sol.pregunta}</p></div></div>
            <div className="msg asistente"><div className="burbuja">
              <BadgeRespaldo estado="solo_ia" />
              <p>{sol.respuesta}</p>
              {sol.contenido.estrategias && <Estrategias contenido={sol.contenido} />}
            </div></div>

            {!hecho ? (
              <div className="card revision" data-testid="revision">
                <b>{t('experto.revision')}</b>
                <div className="acc">
                  {(['confirmar', 'corregir', 'revocar'] as const).map((m) => (
                    <button key={m} className={m === 'confirmar' ? 'big p' : m === 'revocar' ? 'big peligro' : 'big'} aria-pressed={modo === m} onClick={() => setModo(m)}>
                      {m === 'confirmar' ? '✓ ' : ''}{t(`experto.${m}`)}
                    </button>
                  ))}
                </div>
                {modo !== 'confirmar' && (
                  <div className="caja-texto">
                    <textarea rows={3} value={texto} onChange={(e) => setTexto(e.target.value)} aria-label={modo === 'corregir' ? t('experto.textoCorreccion') : t('experto.textoMotivo')}
                      placeholder={modo === 'corregir' ? t('experto.textoCorreccion') : t('experto.textoMotivo')} />
                    <button className={`mic ${dictado.escuchando ? 'activo' : ''}`} aria-label={t('experto.dictar')} disabled={!dictado.soporta}
                      onClick={dictado.escuchando ? dictado.detener : dictado.iniciar}>●</button>
                  </div>
                )}
                <textarea rows={2} value={fuentes} onChange={(e) => setFuentes(e.target.value)} aria-label={t('experto.fuentesPh')} placeholder={t('experto.fuentesPh')} />
                <button className="big p" disabled={!puedeEnviar || revisar.isPending} onClick={() => revisar.mutate()} data-testid="enviar-revision">{t('experto.enviar')}</button>
                {revisar.isError && <p role="alert" className="error">{(revisar.error as Error).message}</p>}
                <small className="nota">{t('experto.guardado')}</small>
              </div>
            ) : (
              <div className="card hecho" role="status" data-testid="revision-hecha">
                <b>{t('experto.hecho')}</b>
                <button className="big" onClick={() => tomar.mutate()}>{t('experto.siguiente')}</button>
              </div>
            )}
          </div>
        )}
        <span hidden>{miArea}</span>
      </main>
    </div>
  );
}
