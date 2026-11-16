import { Component, type ReactNode } from 'react';
import i18n from './i18n';

/** Si algo falla al dibujar, se muestra un mensaje claro en vez de una pantalla en blanco. */
export default class ErrorBoundary extends Component<{ children: ReactNode }, { fallo: boolean }> {
  state = { fallo: false };
  static getDerivedStateFromError() {
    return { fallo: true };
  }
  componentDidCatch(e: unknown) {
    console.error('Error de la app', e);
  }
  render() {
    if (!this.state.fallo) return this.props.children;
    return (
      <div role="alert" className="login" style={{ margin: '12vh auto', maxWidth: 480, padding: 16 }}>
        <h1 style={{ fontSize: 30 }}>{i18n.t('error.titulo')}</h1>
        <p>{i18n.t('error.texto')}</p>
        <button className="big p" onClick={() => location.reload()}>{i18n.t('error.reintentar')}</button>
      </div>
    );
  }
}
