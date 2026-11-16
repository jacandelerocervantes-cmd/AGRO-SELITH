import { useSession } from './store';

export type Geom = GeoJSON.Polygon | GeoJSON.MultiPolygon;
export type Parcela = { id: string; nombre: string; area_m2: number | null; area_ha: number | null; dibujada?: boolean; geom: Geom };

export type CapaInfo = {
  id: string;
  nombre: { es: string; en: string };
  dataset: string;
  nasa: boolean;
  disponible: boolean;
  sintetico: boolean;
  unidad: string | null;
  fuente: string;
  resolucion_nativa_m: number | null;
};
export type CapaValores = {
  capa: string;
  min: number | null;
  max: number | null;
  unidad: string | null;
  fuente: string | null;
  sintetico: boolean;
  resolucion_nativa_m: number | null;
  features: GeoJSON.Feature<GeoJSON.Polygon, { cell_id: number; valor: number | null; sd: number | null }>[];
};

export type Paso = { anio: number; crop_id: string; nombre: string };
export type Explicacion = { por_que: string; beneficios: string[]; evidencia: string[]; vacios: string[]; riesgos: string[] };
export type Estrategia = {
  ranking: number;
  etiqueta: string;
  pasos: Paso[];
  score: number;
  p10: number | null;
  p90: number | null;
  agua_total_mm: number;
  agua_base_mm: number;
  ingreso_estimado: number;
  explicacion: Explicacion;
};
export type Comparacion = { tipo: 'comparacion'; escenario: string; area_m2: number; estrategias: Estrategia[]; provisional: boolean };
export type Revision = { decision: string; texto_corregido: string | null; motivo: string | null; fuentes: string[]; areas: string[] | null };
export type Msg = {
  id: string;
  rol: 'usuario' | 'asistente' | 'sistema';
  texto: string;
  contenido: Partial<Comparacion> & { generado_por?: string };
  idioma: string;
  via_voz: boolean;
  estado_respaldo: 'no_aplica' | 'solo_ia' | 'con_respaldo' | 'revocada';
  area: string | null;
  sintetico: boolean;
  created_at: string;
  revision?: Revision;
};
export type DemoUsuario = { demo_login: string; role: 'agricultor' | 'extensionista' | 'admin'; nombre: string; areas: string[] };
export type Conversacion = { id: string; titulo: string; updated_at: string };
export type Reporte = {
  id: string;
  pregunta: string | null;
  respuesta: string;
  estado_respaldo: string;
  area: string;
  decision: string;
  texto_corregido: string | null;
  motivo: string | null;
  fuentes: string[];
  revisado_at: string;
};
export type Solicitud = {
  id?: string;
  vacia?: boolean;
  area: string;
  pregunta: string | null;
  via_voz: boolean | null;
  respuesta: string;
  contenido: Partial<Comparacion>;
  parcela: string | null;
  area_m2: number | null;
  idioma: string;
};
export type Cola = { areas_totales: Record<string, number>; mis_areas: string[]; pendientes_mis_areas: number; asignadas_a_mi: string[] };

export class ErrorApi extends Error {
  constructor(public status: number, mensaje: string) {
    super(mensaje);
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const login = useSession.getState().login;
  const r = await fetch(`/api${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(login ? { 'X-Demo-Login': login } : {}) },
  });
  if (!r.ok) {
    let detalle = `Error ${r.status}`;
    try {
      const j = (await r.json()) as { detail?: string };
      if (typeof j.detail === 'string') detalle = j.detail;
    } catch {
      /* sin cuerpo */
    }
    throw new ErrorApi(r.status, detalle);
  }
  return (await r.json()) as T;
}

export const post = <T>(path: string, body: unknown) => api<T>(path, { method: 'POST', body: JSON.stringify(body) });
