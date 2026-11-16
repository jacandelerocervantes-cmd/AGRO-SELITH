import { useCallback, useEffect, useRef, useState } from 'react';
import type { Lang } from './i18n';

// Dictado (voz a texto) y lectura (texto a voz) con las APIs del navegador; sin servicios externos.
type Reconocimiento = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
  start: () => void;
  stop: () => void;
};
type Ctor = new () => Reconocimiento;

const ctor = (): Ctor | null => {
  const w = window as unknown as { SpeechRecognition?: Ctor; webkitSpeechRecognition?: Ctor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
};

const LOCALE: Record<Lang, string> = { es: 'es-MX', en: 'en-US' };

export function useDictado(lang: Lang, alTexto: (t: string) => void) {
  const [escuchando, setEscuchando] = useState(false);
  const rec = useRef<Reconocimiento | null>(null);
  const soporta = ctor() !== null;

  useEffect(() => () => rec.current?.stop(), []);

  const iniciar = useCallback(() => {
    const C = ctor();
    if (!C) return;
    const r = new C();
    r.lang = LOCALE[lang];
    r.interimResults = false;
    r.continuous = false;
    r.onresult = (e) => {
      const t = Array.from(e.results).map((x) => x[0].transcript).join(' ');
      alTexto(t.trim());
    };
    r.onend = () => setEscuchando(false);
    r.onerror = () => setEscuchando(false);
    rec.current = r;
    setEscuchando(true);
    r.start();
  }, [lang, alTexto]);

  const detener = useCallback(() => rec.current?.stop(), []);
  return { escuchando, soporta, iniciar, detener };
}

export function hablar(texto: string, lang: Lang) {
  if (!('speechSynthesis' in window)) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(texto);
  u.lang = LOCALE[lang];
  window.speechSynthesis.speak(u);
}
