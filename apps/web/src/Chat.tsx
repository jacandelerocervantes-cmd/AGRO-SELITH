import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { api, post, type Conversacion, type Msg } from './api';
import { BadgeRespaldo, LangToggle } from './comunes';
import Estrategias from './Estrategias';
import { idiomaActual } from './i18n';
import { db } from './offline/db';
import { RedEstado, useEnLinea } from './offline/Red';
import { useSession } from './store';
import { hablar, useDictado } from './voz';

type Conv = { id: string; titulo: string; parcel_id: string | null; mensajes: Msg[] };
type Env = { conversation_id: string; mensajes: Msg[] };

/** Paso 2: conversación estilo Claude/Gemini. Nada de formularios ni paneles: el plan llega como mensaje. */
export default function Chat() {
  const { t, i18n } = useTranslation();
  const lang = idiomaActual();
  const qc = useQueryClient();
  const { conversationId, setConversacion, parcelaId, ir, salir } = useSession();
  const [texto, setTexto] = useState('');
  const [consiente, setConsiente] = useState(false);
  const [decididos, setDecididos] = useState<Record<string, { ranking: number; decision: 'aceptar' | 'ajustar' | 'descartar' }>>({});
  const [pendiente, setPendiente] = useState<string | null>(null);
  const [aviso, setAviso] = useState('');
  const fin = useRef<HTMLDivElement>(null);
  const enLinea = useEnLinea();

  const lista = useQuery<Conversacion[]>({ queryKey: ['conversaciones'], queryFn: () => api('/chat/conversaciones') });
  const conv = useQuery<Conv>({
    queryKey: ['conversacion', conversationId],
    queryFn: () => api(`/chat/conversaciones/${conversationId}`),
    enabled: !!conversationId,
    refetchInterval: 15_000, // para ver pronto el respaldo de un experto
  });
  const mensajes = conv.data?.mensajes ?? [];

  const enviar = useMutation({
    mutationFn: async (v: { texto: string; viaVoz: boolean }) => {
      const cuerpo = {
        texto: v.texto, idioma: lang, parcel_id: parcelaId, conversation_id: conversationId,
        via_voz: v.viaVoz, consentimiento_uso: consiente,
      };
      if (!navigator.onLine) {
        await db.outbox.add({ creadoAt: new Date().toISOString(), texto: v.texto, idioma: lang, parcelId: parcelaId,
          conversationId, viaVoz: v.viaVoz, consentimientoUso: consiente });
        return null;
      }
      return post<Env>('/chat/mensajes', cuerpo);
    },
    onMutate: (v) => setPendiente(v.texto),
    onSuccess: async (r) => {
      setPendiente(null);
      if (r === null) return setAviso(t('chat.sinConexion'));
      setConversacion(r.conversation_id);
      await qc.invalidateQueries({ queryKey: ['conversacion', r.conversation_id] });
      await qc.invalidateQueries({ queryKey: ['conversaciones'] });
    },
    onError: () => setPendiente(null),
  });

  const enviarTexto = useCallback((x: string, viaVoz = false) => {
    const limpio = x.trim();
    if (limpio.length < 2 || enviar.isPending) return;
    setTexto('');
    setAviso('');
    enviar.mutate({ texto: limpio, viaVoz });
  }, [enviar]);

  const dictado = useDictado(lang, (x) => enviarTexto(x, true));

  const decidir = useMutation({
    mutationFn: (v: { mid: string; ranking: number; decision: 'aceptar' | 'ajustar' | 'descartar' }) =>
      post(`/chat/mensajes/${v.mid}/decision`, { decision: v.decision, ranking: v.decision === 'descartar' ? null : v.ranking }),
    onSuccess: (_r, v) => setDecididos((d) => ({ ...d, [v.mid]: { ranking: v.ranking, decision: v.decision } })),
  });

  useEffect(() => {
    fin.current?.scrollIntoView({ behavior: 'smooth' });
  }, [mensajes.length, pendiente]);

  const sugerencias = t('chat.sugerencias', { returnObjects: true }) as unknown as string[];
  const nuevos = (lista.data ?? []).length;
  void nuevos;

  return (
    <div className="chat-layout" data-testid="pantalla-chat">
      <aside className="lateral">
        <b className="logo">{t('app')}</b>
        <button className="big p" onClick={() => setConversacion(null)}>{t('nav.nueva')}</button>
        <small className="sec">{t('nav.recientes')}</small>
        <div className="historial">
          {lista.data?.map((c) => (
            <button key={c.id} className="item" aria-current={c.id === conversationId} onClick={() => setConversacion(c.id)}>{c.titulo}</button>
          ))}
        </div>
        <hr />
        <button className="item" onClick={() => ir('reportes')} data-testid="ir-reportes">{t('nav.reportes')}</button>
        <button className="item" onClick={() => ir('mapa')}>{t('nav.mapa')}</button>
        <div className="pie-lateral">
          <RedEstado etiqueta={{ con: lang === 'en' ? 'Online' : 'Con señal', sin: lang === 'en' ? 'Offline' : 'Sin señal', porEnviar: lang === 'en' ? 'to send' : 'por enviar' }} />
          <LangToggle />
          <button className="item" onClick={salir}>{t('nav.salir')}</button>
        </div>
      </aside>

      <main className="hilo">
        <div className="aviso-demo">{t('demoNota')}</div>
        <div className="mensajes" data-testid="mensajes" aria-live="polite">
          {mensajes.length === 0 && !pendiente && (
            <div className="bienvenida">
              <p>{t('chat.bienvenida')}</p>
              {!parcelaId && <div className="por"><span>{t('chat.sinParcela')}</span> <button className="big" onClick={() => ir('mapa')}>{t('chat.irMapa')}</button></div>}
              <div className="chips">{sugerencias.map((s) => <button key={s} className="chip" onClick={() => enviarTexto(s)}>{s}</button>)}</div>
            </div>
          )}
          {mensajes.map((m) => (
            <Burbuja key={m.id} m={m} lang={lang} decidido={decididos[m.id] ?? null}
              onDecidir={(ranking, decision) => decidir.mutate({ mid: m.id, ranking, decision })} />
          ))}
          {pendiente && (
            <>
              <div className="msg usuario"><div className="burbuja">{pendiente}</div></div>
              <div className="msg asistente"><div className="burbuja pensando">{t('chat.pensando')}</div></div>
            </>
          )}
          {aviso && <div className="sistema" role="status">{aviso}</div>}
          <div ref={fin} />
        </div>

        <div className="compositor">
          {!dictado.soporta && <small className="nota">{t('chat.noVoz')}</small>}
          <div className="caja-texto">
            <textarea rows={1} value={texto} placeholder={dictado.escuchando ? t('chat.escuchando') : t('chat.escriba')}
              aria-label={t('chat.escriba')} onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); enviarTexto(texto); } }} />
            <button className={`mic ${dictado.escuchando ? 'activo' : ''}`} aria-label={t('chat.hablar')} aria-pressed={dictado.escuchando}
              disabled={!dictado.soporta} onClick={dictado.escuchando ? dictado.detener : dictado.iniciar} data-testid="mic">●</button>
            <button className="enviar" aria-label={t('chat.enviar')} disabled={texto.trim().length < 2 || enviar.isPending} onClick={() => enviarTexto(texto)} data-testid="enviar">➤</button>
          </div>
          <label className="check"><input type="checkbox" checked={consiente} onChange={(e) => setConsiente(e.target.checked)} /> {t('chat.consiente')}</label>
          {!enLinea && <small className="nota">{t('chat.sinConexion')}</small>}
        </div>
      </main>
      <span hidden>{i18n.language}</span>
    </div>
  );
}

function Burbuja({ m, lang, decidido, onDecidir }: { m: Msg; lang: 'es' | 'en'; decidido: { ranking: number; decision: 'aceptar' | 'ajustar' | 'descartar' } | null; onDecidir: (r: number, d: 'aceptar' | 'ajustar' | 'descartar') => void }) {
  const { t } = useTranslation();
  const { ir } = useSession();
  if (m.rol === 'sistema') return <div className="sistema revocada" role="status">{m.texto}</div>;
  if (m.rol === 'usuario') {
    return (
      <div className="msg usuario" data-testid="msg-usuario">
        <div className="burbuja">{m.via_voz && <small className="voz">🎙 </small>}{m.texto}</div>
      </div>
    );
  }
  return (
    <div className="msg asistente" data-testid="msg-asistente">
      <div className={`burbuja ${m.estado_respaldo === 'revocada' ? 'tachada' : ''}`}>
        <BadgeRespaldo estado={m.estado_respaldo} area={m.revision?.areas?.[0] ?? m.area} />
        <p>{m.texto}</p>
        {m.contenido.estrategias && m.estado_respaldo !== 'revocada' && (
          <Estrategias contenido={m.contenido} decidido={decidido} onDecidir={onDecidir} />
        )}
        {m.estado_respaldo === 'solo_ia' && m.area && <small className="nota cola">{t('chat.enCola', { area: t(`areas.${m.area}`) })}</small>}
        {m.revision?.texto_corregido && <div className="por"><b>{t('respaldo.correccion')}:</b> {m.revision.texto_corregido}</div>}
        {m.revision?.motivo && <div className="por"><b>{t('respaldo.motivo')}:</b> {m.revision.motivo}</div>}
        {m.revision && m.revision.fuentes.length > 0 && <small className="nota">{t('respaldo.fuentes')}: {m.revision.fuentes.join(' · ')}</small>}
        {m.estado_respaldo === 'con_respaldo' && <button className="enlace" onClick={() => ir('reportes')}>{t('respaldo.verReporte')}</button>}
        <button className="enlace" onClick={() => hablar(m.texto, lang)}>{t('chat.escuchar')}</button>
      </div>
    </div>
  );
}
