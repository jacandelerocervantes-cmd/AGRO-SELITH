export const CULT: Record<string, { ico: string; color: string }> = {
  mucuna_abono_verde: { ico: '🌿', color: '#4f7f33' },
  canavalia_cobertura: { ico: '🍃', color: '#356f5c' },
  acahual_descanso: { ico: '🌳', color: '#46623a' },
  barbecho_desnudo: { ico: '🟫', color: '#7a6a54' },
  frijol_xpelon: { ico: '🫘', color: '#9a5c28' },
  calabaza_pepita: { ico: '🎃', color: '#b8641f' },
  chile_habanero: { ico: '🌶️', color: '#b13b27' },
  maiz_monocultivo: { ico: '🌾', color: '#9a741f' },
  milpa_tradicional: { ico: '🌽', color: '#a77d17' },
  milpa_ciclo_corto_criollo: { ico: '🌽', color: '#9a6f10' },
};

export const NIVEL_COLOR = { ok: '#4f9a4a', mid: '#e0a42f', bad: '#c4452f' } as const;

export const FACTOR_ETIQUETA: Record<string, string> = {
  agua_eficiencia: 'Uso eficiente del agua',
  fijacion_n: 'Nitrógeno que deja',
  materia_organica: 'Materia orgánica',
  control_erosion: 'Protección contra erosión',
  infiltracion: 'Entrada de agua al suelo',
  ruptura_plagas: 'Corta el ciclo de plagas',
  valor_forrajero: 'Forraje',
  ingreso_neto: 'Ingreso',
  estabilidad_ingreso: 'Ingreso estable',
  proteccion_etapas: 'Protege floración de la canícula',
  barbecho_excesivo: 'Descanso sin cobertura',
  concentracion_riesgo: 'Riesgo concentrado',
  dependencia_monocultivo: 'Depender de un cultivo',
};
