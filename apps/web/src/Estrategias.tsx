import type { TFunction } from 'i18next';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { Comparacion, Estrategia } from './api';
import { CULT } from './crops';
import { idiomaActual } from './i18n';
import { hablar } from './voz';

type Decision = 'aceptar' | 'ajustar' | 'descartar';
type Props = {
  contenido: Partial<Comparacion>;
  onDecidir?: (ranking: number, d: Decision) => void;
  decidido?: { ranking: number; decision: Decision } | null;
};

const etiqueta = (e: Estrategia, t: TFunction) => (e.ranking === 0 ? t('est.actual') : t('est.opcion', { n: e.ranking }));

/** Tres estrategias (la actual + dos alternativas): línea de años, agua, por qué, evidencia, vacíos y riesgos. */
export default function Estrategias({ contenido, onDecidir, decidido }: Props) {
  const { t } = useTranslation();
  const lang = idiomaActual();
  const est = contenido.estrategias ?? [];
  const [sel, setSel] = useState(est.length > 1 ? 1 : 0);
  const e = est[sel];
  if (!e) return null;
  const max = Math.max(e.agua_base_mm, e.agua_total_mm) * 1.1 || 1;
  const resumen = `${etiqueta(e, t)}. ${e.pasos.map((p) => `${t('est.anio', { n: p.anio })}: ${p.nombre}`).join('. ')}. ${e.explicacion.por_que}`;
  const escenario = contenido.escenario ? t(`est.escenario.${contenido.escenario}`) : '';

  return (
    <div className="estrategias" data-testid="estrategias">
      <div className="chips" role="tablist">
        {est.map((x, i) => (
          <button key={x.ranking} role="tab" className="chip" aria-selected={i === sel} aria-pressed={i === sel} onClick={() => setSel(i)}>
            {etiqueta(x, t)}
          </button>
        ))}
        {escenario && <span className="tag">{escenario}</span>}
      </div>

      <div className="linea" data-testid="linea">
        {e.pasos.map((p) => (
          <div key={p.anio} className="ciclo" data-crop={p.crop_id} style={{ background: (CULT[p.crop_id] ?? { color: '#4f7f33' }).color }}>
            <small>{t('est.anio', { n: p.anio })}</small>
            {p.nombre}
          </div>
        ))}
      </div>

      <div className="agua">
        <div className="fila-agua"><span>{t('est.agua')}</span><span data-testid="agua-txt">{t('est.aguaDe', { a: Math.round(e.agua_total_mm), b: Math.round(e.agua_base_mm) })}</span></div>
        <div className="barra"><b style={{ width: `${(e.agua_total_mm / max) * 100}%` }} /><u style={{ left: `${(e.agua_base_mm / max) * 100}%` }} /></div>
        <small className="nota">{t('est.aguaNota')}</small>
      </div>

      <p className="por"><b>{t('est.porQue')}</b> {e.explicacion.por_que}</p>
      {e.p10 !== null && e.p90 !== null && <small className="nota">{t('est.puntaje', { s: e.score.toFixed(2), p10: e.p10.toFixed(2), p90: e.p90.toFixed(2) })}</small>}

      <details open><summary>{t('est.beneficios')}</summary><ul>{e.explicacion.beneficios.map((b) => <li key={b}>{b}</li>)}</ul></details>
      <details><summary>{t('est.evidencia')}</summary><ul>{e.explicacion.evidencia.map((b) => <li key={b}>{b}</li>)}</ul></details>
      <details><summary>{t('est.vacios')}</summary><ul>{e.explicacion.vacios.map((b) => <li key={b}>{b}</li>)}</ul></details>
      <details><summary>{t('est.riesgos')}</summary><ul>{e.explicacion.riesgos.map((b) => <li key={b}>{b}</li>)}</ul></details>
      {contenido.provisional && <small className="nota">{t('est.datosEjemplo')}</small>}

      {onDecidir && (
        <div className="acc" data-testid="decisiones">
          {(['aceptar', 'ajustar', 'descartar'] as const).map((d) => (
            <button key={d} className={d === 'aceptar' ? 'big p' : 'big'} aria-pressed={decidido?.decision === d && decidido.ranking === e.ranking}
              onClick={() => onDecidir(e.ranking, d)}>{t(`est.${d}`)}</button>
          ))}
          <button className="big" onClick={() => hablar(resumen, lang)}>{t('chat.escuchar')}</button>
        </div>
      )}
      {decidido && <small className="nota" role="status">{t('est.decidido', { d: t(`est.${decidido.decision}`) })}</small>}
    </div>
  );
}
