import { useLiveQuery } from 'dexie-react-hooks';
import { useEffect, useState } from 'react';
import { post } from '../api';
import { db } from './db';

export function useEnLinea(): boolean {
  const [on, setOn] = useState(navigator.onLine);
  useEffect(() => {
    const a = () => setOn(true);
    const b = () => setOn(false);
    window.addEventListener('online', a);
    window.addEventListener('offline', b);
    return () => {
      window.removeEventListener('online', a);
      window.removeEventListener('offline', b);
    };
  }, []);
  return on;
}

let enviando = false;
/** Envía en orden lo escrito sin señal; devuelve cuántos se enviaron. */
export async function vaciarOutbox(): Promise<number> {
  if (enviando || !navigator.onLine) return 0;
  enviando = true;
  let n = 0;
  try {
    for (const p of await db.outbox.orderBy('creadoAt').toArray()) {
      await post('/chat/mensajes', {
        texto: p.texto, idioma: p.idioma, parcel_id: p.parcelId, conversation_id: p.conversationId,
        via_voz: p.viaVoz, consentimiento_uso: p.consentimientoUso,
      });
      if (p.id !== undefined) await db.outbox.delete(p.id);
      n++;
    }
  } catch {
    /* se reintenta al volver la señal */
  } finally {
    enviando = false;
  }
  return n;
}

/** Punto de estado de la conexión (y mensajes por enviar). Reintenta solo al volver la red. */
export function RedEstado({ etiqueta }: { etiqueta: { con: string; sin: string; porEnviar: string } }) {
  const on = useEnLinea();
  const n = useLiveQuery(() => db.outbox.count(), [], 0);
  useEffect(() => {
    if (on) void vaciarOutbox();
  }, [on]);
  return (
    <span className="net" data-testid="red" data-online={on} data-por-enviar={n}>
      <i style={{ background: on ? '#2f7a2c' : '#c4452f' }} />
      {on ? etiqueta.con : etiqueta.sin}
      {n > 0 && <b> · {n} {etiqueta.porEnviar}</b>}
    </span>
  );
}
