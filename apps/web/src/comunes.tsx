import { useTranslation } from 'react-i18next';
import { cambiarIdioma, type Lang } from './i18n';

export function LangToggle() {
  const { i18n, t } = useTranslation();
  const l = (i18n.language === 'en' ? 'en' : 'es') as Lang;
  return (
    <div className="seg" role="group" aria-label={`${t('idioma')} / Language`}>
      {(['es', 'en'] as const).map((x) => (
        <button key={x} aria-pressed={l === x} onClick={() => cambiarIdioma(x)}>{x.toUpperCase()}</button>
      ))}
    </div>
  );
}

export function BadgeRespaldo({ estado, area }: { estado: 'solo_ia' | 'con_respaldo' | 'revocada' | 'no_aplica'; area?: string | null }) {
  const { t } = useTranslation();
  if (estado === 'no_aplica') return null;
  const nombreArea = area ? t(`areas.${area}`) : '';
  const texto = estado === 'con_respaldo' ? t('respaldo.con_respaldo', { area: nombreArea }) : t(`respaldo.${estado}`);
  return <span className={`badge ${estado}`} data-testid="badge-respaldo" data-estado={estado}>{estado === 'con_respaldo' ? '✓ ' : ''}{texto}</span>;
}

export const fecha = (iso: string, lang: string) =>
  new Date(iso).toLocaleDateString(lang === 'en' ? 'en-US' : 'es-MX', { day: 'numeric', month: 'short', year: 'numeric' });
