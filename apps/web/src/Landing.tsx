import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { LangToggle } from './comunes';
import MapaHero from './MapaHero';
import { useSession } from './store';

const AREAS = ['suelos', 'patogenos', 'agua', 'clima', 'mercado', 'cultivos'] as const;

/** Portada: satélite real de fondo y dos entradas iguales. Acceso simulado (sin correo ni contraseña). */
export default function Landing() {
  const { t, i18n } = useTranslation();
  const entrar = useSession((s) => s.entrar);
  const [area, setArea] = useState<(typeof AREAS)[number]>('suelos');
  const lang = i18n.language === 'en' ? 'en' : 'es';

  return (
    <div className="landing" data-testid="landing">
      <MapaHero lang={lang} />
      <header className="barra-sup landing-barra">
        <b className="logo">{t('app')}</b>
        <div className="der"><span className="tag aviso">{t('demo')}</span><LangToggle /></div>
      </header>
      <main className="landing-centro">
        <h1>{t('landing.titulo')}</h1>
        <p className="sub">{t('landing.sub')}</p>
        <div className="roles">
          <div className="card rol">
            <h2>{t('landing.productor')}</h2>
            <p>{t('landing.productorSub')}</p>
            <div className="rol-pie">
              <button className="big p" data-testid="entrar-productor" onClick={() => entrar('demo-agricultor', 'agricultor', [])}>{t('landing.entrar')}</button>
            </div>
          </div>
          <div className="card rol">
            <h2>{t('landing.experto')}</h2>
            <p>{t('landing.expertoSub')}</p>
            <div className="chips">
              {AREAS.map((a) => <button key={a} className="chip" aria-pressed={area === a} onClick={() => setArea(a)}>{t(`areas.${a}`)}</button>)}
            </div>
            <div className="rol-pie">
              <button className="big" data-testid="entrar-experto" onClick={() => entrar(`demo-experto-${area}`, 'extensionista', [area])}>{t('landing.entrar')}</button>
            </div>
          </div>
        </div>
        <p className="nota-demo">{t('demoNota')}</p>
      </main>
    </div>
  );
}
