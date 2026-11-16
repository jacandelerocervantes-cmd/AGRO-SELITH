import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LangToggle } from './comunes';
import { useSession } from './store';

const AREAS = ['suelos', 'patogenos', 'agua', 'clima', 'mercado', 'cultivos'] as const;

/** Página 1: portada con acceso simulado (sin correo ni contraseña). */
export default function Landing() {
  const { t } = useTranslation();
  const entrar = useSession((s) => s.entrar);
  const [area, setArea] = useState<(typeof AREAS)[number]>('suelos');

  return (
    <div className="landing" data-testid="landing">
      <header className="barra-sup">
        <b className="logo">{t('app')}</b>
        <div className="der"><span className="tag aviso">{t('demo')}</span><LangToggle /></div>
      </header>
      <main className="hero">
        <section>
          <h1>{t('landing.titulo')}</h1>
          <p className="sub">{t('landing.sub')}</p>
          <div className="roles">
            <div className="card rol principal">
              <h2>{t('landing.productor')}</h2>
              <p>{t('landing.productorSub')}</p>
              <button className="big p" data-testid="entrar-productor" onClick={() => entrar('demo-agricultor', 'agricultor', [])}>{t('landing.entrar')}</button>
            </div>
            <div className="card rol">
              <h2>{t('landing.experto')}</h2>
              <p>{t('landing.expertoSub')}</p>
              <div className="chips">
                {AREAS.map((a) => <button key={a} className="chip" aria-pressed={area === a} onClick={() => setArea(a)}>{t(`areas.${a}`)}</button>)}
              </div>
              <button className="big" data-testid="entrar-experto" onClick={() => entrar(`demo-experto-${area}`, 'extensionista', [area])}>{t('landing.entrar')}</button>
            </div>
          </div>
          <p className="nota">{t('demoNota')}</p>
          <p className="nota nasa-nota">{t('landing.nasa')}</p>
        </section>
        <section className="vista-previa" aria-hidden="true">
          <div className="card">
            <svg viewBox="0 0 400 220" className="mini-mapa">
              <rect width="400" height="220" fill="#8aa56a" /><rect y="120" width="400" height="100" fill="#a9b98a" />
              <path d="M0 150C120 130 260 175 400 140" stroke="#e9e4d2" strokeWidth="8" fill="none" />
              <polygon points="90,60 230,40 270,120 120,150" fill="#d8b04a" fillOpacity=".55" stroke="#fff" strokeWidth="3" />
              <text x="150" y="105" fontSize="16" fontWeight="700" fill="#23301f">12,400 m²</text>
            </svg>
            <div className="msg usuario"><div className="burbuja">{(t('chat.sugerencias', { returnObjects: true }) as unknown as string[])[0]}</div></div>
          </div>
        </section>
      </main>
    </div>
  );
}
