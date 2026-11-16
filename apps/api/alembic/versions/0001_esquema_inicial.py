"""Esquema inicial.

Revision ID: 0001
Revises:
"""

from alembic import op

revision = "0001"
down_revision = None

TABLAS = [  # orden de creación; downgrade las borra al revés
    "user_account", "farm", "parcel", "parcel_soil", "climate_cell", "climate_daily",
    "drought_index", "parcel_cell", "vi_series", "land_cover", "crop", "model_version",
    "crop_param", "rotation_rule", "market_price", "market_balance", "historical_yield",
    "scenario", "recommendation_run", "recommendation_plan", "plan_step",
    "recommendation_factor", "farmer_decision", "producer_question", "benchmark_item",
    "benchmark_run", "benchmark_result", "audit_log",
]

UP = """
CREATE EXTENSION IF NOT EXISTS postgis;

-- Estatus de parámetros: validado | provisional
CREATE DOMAIN estatus_t AS text CHECK (VALUE IN ('validado','provisional'));

-- Demo: roles de PRUEBA sin correo ni contraseña (demo_login). firebase_uid queda para producción.
CREATE TABLE user_account (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firebase_uid text UNIQUE,
  demo_login text UNIQUE,
  es_demo boolean NOT NULL DEFAULT false,
  role text NOT NULL CHECK (role IN ('agricultor','extensionista','admin')),
  nombre text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (firebase_uid IS NOT NULL OR demo_login IS NOT NULL),
  CHECK (NOT es_demo OR demo_login IS NOT NULL)
);
CREATE TABLE farm (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
  nombre text NOT NULL,
  municipio_cve text,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE parcel (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  farm_id uuid NOT NULL REFERENCES farm(id) ON DELETE CASCADE,
  nombre text NOT NULL,
  geom geometry(MultiPolygon,4326) NOT NULL,
  area_ha numeric CHECK (area_ha > 0),
  riego boolean NOT NULL DEFAULT false,
  maquinaria text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX parcel_geom_gix ON parcel USING gist (geom);
CREATE INDEX parcel_farm_ix ON parcel (farm_id);

CREATE TABLE parcel_soil (
  parcel_id uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
  fuente text NOT NULL,
  fecha date NOT NULL,
  textura text, ph numeric, mo_pct numeric, n_ppm numeric, p_ppm numeric, k_ppm numeric,
  infiltracion_mm_h numeric, profundidad_cm numeric, pedregosidad_pct numeric,
  retencion_mm numeric, pendiente_pct numeric,
  erosion_riesgo numeric CHECK (erosion_riesgo BETWEEN 0 AND 1),
  incertidumbre jsonb NOT NULL DEFAULT '{}',
  sintetico boolean NOT NULL DEFAULT false,
  PRIMARY KEY (parcel_id, fuente, fecha)
);

CREATE TABLE climate_cell (
  cell_id integer PRIMARY KEY,
  geom geometry(Polygon,4326) NOT NULL,
  res_m integer NOT NULL
);
CREATE INDEX climate_cell_gix ON climate_cell USING gist (geom);
CREATE TABLE scenario (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  clave text NOT NULL UNIQUE,
  nombre text NOT NULL,
  tipo text NOT NULL CHECK (tipo IN ('base','canicula_prolongada','temporal_tardio','huracan')),
  parametros jsonb NOT NULL
);
CREATE TABLE climate_daily (
  cell_id integer NOT NULL REFERENCES climate_cell(cell_id),
  fecha date NOT NULL,
  precip_mm real, tmax real, tmin real, rad_mj real, et0_mm real,
  fuente text NOT NULL,
  escenario_id uuid REFERENCES scenario(id),
  sintetico boolean NOT NULL DEFAULT false
);
CREATE UNIQUE INDEX climate_daily_uq ON climate_daily
  (cell_id, fecha, fuente, COALESCE(escenario_id, '00000000-0000-0000-0000-000000000000'::uuid));
CREATE TABLE drought_index (
  cell_id integer NOT NULL REFERENCES climate_cell(cell_id),
  fecha date NOT NULL,
  indice text NOT NULL, valor real NOT NULL, fuente text NOT NULL,
  PRIMARY KEY (cell_id, fecha, indice, fuente)
);
CREATE TABLE parcel_cell (
  parcel_id uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
  cell_id integer NOT NULL REFERENCES climate_cell(cell_id),
  peso real NOT NULL CHECK (peso > 0 AND peso <= 1),
  PRIMARY KEY (parcel_id, cell_id)
);
CREATE TABLE vi_series (
  parcel_id uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
  fecha date NOT NULL,
  ndvi real, evi real,
  sensor text NOT NULL,
  nubosidad_pct real CHECK (nubosidad_pct BETWEEN 0 AND 100),
  PRIMARY KEY (parcel_id, fecha, sensor)
);
CREATE TABLE land_cover (
  parcel_id uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
  serie text NOT NULL, clase text NOT NULL, anio integer NOT NULL,
  PRIMARY KEY (parcel_id, serie, anio)
);

-- Base agronómica versionada. Valores desconocidos = NULL (nunca inventados).
CREATE TABLE crop (
  id text PRIMARY KEY,
  nombre text NOT NULL,
  familia_botanica text,
  familias text[] NOT NULL DEFAULT '{}',
  tipo text[] NOT NULL DEFAULT '{}',
  es_asociacion boolean NOT NULL DEFAULT false,
  es_barbecho boolean NOT NULL DEFAULT false,
  fija_n boolean, cobertura boolean, raiz_profunda boolean, forraje_valor integer
);
CREATE TABLE model_version (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre text NOT NULL,
  pesos jsonb NOT NULL,
  umbrales jsonb NOT NULL DEFAULT '{}',
  creado_por uuid REFERENCES user_account(id),
  validado_por uuid REFERENCES user_account(id),
  estado text NOT NULL CHECK (estado IN ('borrador','validado','archivado')),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (estado <> 'validado' OR validado_por IS NOT NULL)
);
CREATE TABLE crop_param (
  crop_id text NOT NULL REFERENCES crop(id) ON DELETE CASCADE,
  version_id uuid NOT NULL REFERENCES model_version(id),
  kc_ini real, kc_mid real, kc_fin real, ciclo_dias integer,
  agua_mm_ciclo numeric, tolerancia_sequia integer, etapas_sensibles jsonb,
  n_aporte_kg_ha numeric, mo_aporte numeric, rendimiento_ref_t_ha numeric,
  sensibilidad_canicula numeric, ingreso_ref_mxn_ha numeric,
  parametros jsonb NOT NULL,           -- todos los parámetros con valor/unidad/fuente/estatus
  fuente text NOT NULL CHECK (length(trim(fuente)) > 0),
  estatus estatus_t NOT NULL,
  PRIMARY KEY (crop_id, version_id)
);
CREATE TABLE rotation_rule (
  id text PRIMARY KEY,
  tipo text NOT NULL CHECK (tipo IN ('familia_consecutiva','intervalo_retorno','hospedante_comun','secuencia_favorable')),
  crop_a text NOT NULL, crop_b text NOT NULL,   -- selectores id:/fam:/host:
  anios_min integer NOT NULL CHECK (anios_min >= 0),
  severidad integer NOT NULL CHECK (severidad BETWEEN 1 AND 5),
  descripcion text,
  fuente text NOT NULL CHECK (length(trim(fuente)) > 0),
  estatus estatus_t NOT NULL
);

CREATE TABLE market_price (
  crop_id text NOT NULL REFERENCES crop(id), central text NOT NULL, fecha date NOT NULL,
  precio_min numeric, precio_max numeric, precio_frec numeric, fuente text NOT NULL,
  sintetico boolean NOT NULL DEFAULT false,
  PRIMARY KEY (crop_id, central, fecha)
);
CREATE TABLE market_balance (
  crop_id text NOT NULL REFERENCES crop(id), region text NOT NULL, anio integer NOT NULL,
  produccion_t numeric, consumo_t numeric, capacidad_absorcion_ha numeric,
  fuente text NOT NULL, sintetico boolean NOT NULL DEFAULT false,
  PRIMARY KEY (crop_id, region, anio)
);
CREATE TABLE historical_yield (
  crop_id text NOT NULL REFERENCES crop(id), municipio_cve text NOT NULL, anio integer NOT NULL,
  rendimiento_t_ha numeric, modalidad text NOT NULL, fuente text NOT NULL,
  PRIMARY KEY (crop_id, municipio_cve, anio, modalidad)
);

CREATE TABLE recommendation_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  parcel_id uuid NOT NULL REFERENCES parcel(id),
  user_id uuid NOT NULL REFERENCES user_account(id),
  model_version_id uuid NOT NULL REFERENCES model_version(id),
  scenario_id uuid NOT NULL REFERENCES scenario(id),
  prioridades jsonb NOT NULL, limites jsonb NOT NULL DEFAULT '{}',
  horizonte_anios integer NOT NULL CHECK (horizonte_anios BETWEEN 3 AND 5),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE recommendation_plan (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES recommendation_run(id) ON DELETE CASCADE,
  ranking integer NOT NULL CHECK (ranking BETWEEN 1 AND 3),
  score numeric NOT NULL, score_p10 numeric, score_p90 numeric,
  agua_total_mm numeric, ingreso_estimado numeric, delta_mo numeric, delta_n numeric,
  riesgo_plaga numeric,
  UNIQUE (run_id, ranking)
);
CREATE TABLE plan_step (
  plan_id uuid NOT NULL REFERENCES recommendation_plan(id) ON DELETE CASCADE,
  anio integer NOT NULL, ciclo text NOT NULL,
  crop_id text NOT NULL REFERENCES crop(id),
  es_barbecho boolean NOT NULL DEFAULT false,
  siembra_ventana daterange, notas text,
  PRIMARY KEY (plan_id, anio, ciclo)
);
CREATE TABLE recommendation_factor (
  plan_id uuid NOT NULL REFERENCES recommendation_plan(id) ON DELETE CASCADE,
  factor text NOT NULL, valor_norm real NOT NULL, peso real NOT NULL, contribucion real NOT NULL,
  explicacion text NOT NULL,
  PRIMARY KEY (plan_id, factor)
);
CREATE TABLE farmer_decision (
  run_id uuid NOT NULL REFERENCES recommendation_run(id) ON DELETE CASCADE,
  plan_id uuid REFERENCES recommendation_plan(id),
  decision text NOT NULL CHECK (decision IN ('aceptar','ajustar','descartar')),
  comentario text,
  decidido_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, decidido_at),
  CHECK (decision = 'descartar' OR plan_id IS NOT NULL)
);
CREATE TABLE audit_log (
  id bigserial PRIMARY KEY,
  user_id uuid REFERENCES user_account(id),
  accion text NOT NULL, entidad text NOT NULL, entidad_id text,
  detalle jsonb NOT NULL DEFAULT '{}',
  at timestamptz NOT NULL DEFAULT now()
);
-- Preguntas de productores = fuente del BENCHMARK agronómico (no solo de entrenamiento).
-- Reglas: solo con consentimiento; cada ítem cae en UN solo split (sin contaminación);
-- el benchmark se mide únicamente con ítems de split 'benchmark'.
CREATE TABLE producer_question (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES user_account(id),
  parcel_id uuid REFERENCES parcel(id),
  run_id uuid REFERENCES recommendation_run(id),
  escenario_id uuid REFERENCES scenario(id),
  idioma text NOT NULL DEFAULT 'es',
  texto text NOT NULL CHECK (length(trim(texto)) > 0),
  contexto jsonb NOT NULL DEFAULT '{}',
  origen text NOT NULL CHECK (origen IN ('app','entrevista','taller','demo')),
  consentimiento_uso boolean NOT NULL DEFAULT false,
  consentimiento_at timestamptz,
  anonimizada boolean NOT NULL DEFAULT false,
  sintetico boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (NOT consentimiento_uso OR consentimiento_at IS NOT NULL)
);
CREATE TABLE benchmark_item (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  question_id uuid UNIQUE REFERENCES producer_question(id),
  version integer NOT NULL DEFAULT 1,
  texto text NOT NULL,
  texto_hash text NOT NULL UNIQUE,          -- evita duplicados y fuga entre splits
  categoria text NOT NULL CHECK (categoria IN
    ('agua','suelo','plagas','mercado','calendario','canicula','milpa','saber_local','otra')),
  split text NOT NULL CHECK (split IN ('benchmark','entrenamiento','desarrollo')),
  respuesta_referencia text,
  rubrica jsonb NOT NULL DEFAULT '[]',      -- criterios de evaluación puntuables
  fuentes jsonb NOT NULL DEFAULT '[]',
  estatus estatus_t NOT NULL DEFAULT 'provisional',
  validado_por uuid REFERENCES user_account(id),
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (estatus <> 'validado' OR (validado_por IS NOT NULL AND respuesta_referencia IS NOT NULL))
);
CREATE FUNCTION benchmark_item_consentimiento() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.question_id IS NOT NULL AND NOT EXISTS
     (SELECT 1 FROM producer_question WHERE id = NEW.question_id AND consentimiento_uso) THEN
    RAISE EXCEPTION 'la pregunta no tiene consentimiento de uso';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER benchmark_item_consent BEFORE INSERT OR UPDATE ON benchmark_item
  FOR EACH ROW EXECUTE FUNCTION benchmark_item_consentimiento();
CREATE TABLE benchmark_run (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  nombre text NOT NULL,
  sistema text NOT NULL CHECK (sistema IN ('motor','llm','motor+llm')),
  modelo text,                               -- p. ej. id del modelo Claude evaluado
  model_version_id uuid REFERENCES model_version(id),
  config jsonb NOT NULL DEFAULT '{}',
  ejecutado_por uuid REFERENCES user_account(id),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE benchmark_result (
  run_id uuid NOT NULL REFERENCES benchmark_run(id) ON DELETE CASCADE,
  item_id uuid NOT NULL REFERENCES benchmark_item(id),
  respuesta text NOT NULL,
  puntaje numeric CHECK (puntaje BETWEEN 0 AND 1),
  desglose jsonb NOT NULL DEFAULT '{}',
  juez text,
  latencia_ms integer, tokens jsonb,
  PRIMARY KEY (run_id, item_id)
);
CREATE FUNCTION benchmark_result_split() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM benchmark_item WHERE id = NEW.item_id AND split = 'benchmark') THEN
    RAISE EXCEPTION 'solo ítems del split benchmark se evalúan';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER benchmark_result_solo_benchmark BEFORE INSERT OR UPDATE ON benchmark_result
  FOR EACH ROW EXECUTE FUNCTION benchmark_result_split();

-- Bitácora solo-anexar
CREATE FUNCTION audit_log_inmutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'audit_log es solo de anexado'; END $$;
CREATE TRIGGER audit_log_no_mod BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_inmutable();
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_mod ON audit_log")
    for t in reversed(TABLAS):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    for f in ("audit_log_inmutable", "benchmark_item_consentimiento", "benchmark_result_split"):
        op.execute(f"DROP FUNCTION IF EXISTS {f}()")
    op.execute("DROP DOMAIN IF EXISTS estatus_t")
