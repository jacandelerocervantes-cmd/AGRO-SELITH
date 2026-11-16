"""Chat del productor, cola de revisión por áreas, capas armonizadas y parcela dibujada.

Revision ID: 0004
Revises: 0003
"""

from alembic import op

revision = "0004"
down_revision = "0003"

AREAS = "('suelos','patogenos','agua','clima','mercado','cultivos')"
TABLAS = ["review", "review_request", "chat_decision", "chat_message", "chat_conversation", "layer_value"]

UP = f"""
ALTER TABLE parcel ADD COLUMN area_m2 numeric;
ALTER TABLE parcel ADD COLUMN dibujada boolean NOT NULL DEFAULT false;

-- Áreas de agronomía en las que un experto puede revisar (vacío = no es experto)
ALTER TABLE user_account ADD COLUMN areas text[] NOT NULL DEFAULT '{{}}';

CREATE TABLE chat_conversation (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES user_account(id) ON DELETE CASCADE,
  parcel_id uuid REFERENCES parcel(id),
  titulo text NOT NULL DEFAULT '',
  idioma text NOT NULL DEFAULT 'es' CHECK (idioma IN ('es','en')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE chat_message (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id uuid NOT NULL REFERENCES chat_conversation(id) ON DELETE CASCADE,
  rol text NOT NULL CHECK (rol IN ('usuario','asistente','sistema')),
  texto text NOT NULL,
  contenido jsonb NOT NULL DEFAULT '{{}}',      -- p. ej. comparación de rotaciones, evidencia, vacíos
  via_voz boolean NOT NULL DEFAULT false,
  idioma text NOT NULL DEFAULT 'es',
  -- estado del respaldo académico de una respuesta del asistente
  estado_respaldo text NOT NULL DEFAULT 'no_aplica'
    CHECK (estado_respaldo IN ('no_aplica','solo_ia','con_respaldo','revocada')),
  area text CHECK (area IN {AREAS}),
  sintetico boolean NOT NULL DEFAULT false,
  consentimiento_uso boolean NOT NULL DEFAULT false,
  -- clock_timestamp(): pregunta y respuesta se guardan en la misma transacción y deben quedar en orden
  created_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX chat_message_conv_ix ON chat_message (conversation_id, created_at);

CREATE TABLE chat_decision (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid NOT NULL REFERENCES chat_message(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES user_account(id),
  decision text NOT NULL CHECK (decision IN ('aceptar','ajustar','descartar')),
  ranking integer CHECK (ranking BETWEEN 0 AND 3),
  comentario text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (decision = 'descartar' OR ranking IS NOT NULL)
);

-- Cola total de solicitudes de revisión; se subdivide por área y se reparte al azar
CREATE TABLE review_request (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id uuid NOT NULL UNIQUE REFERENCES chat_message(id) ON DELETE CASCADE,
  area text NOT NULL CHECK (area IN {AREAS}),
  estado text NOT NULL DEFAULT 'pendiente' CHECK (estado IN ('pendiente','asignada','revisada')),
  asignada_a uuid REFERENCES user_account(id),
  asignada_at timestamptz,
  orden_aleatorio double precision NOT NULL DEFAULT random(),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX review_request_cola_ix ON review_request (area, estado, orden_aleatorio);

CREATE TABLE review (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  request_id uuid NOT NULL UNIQUE REFERENCES review_request(id) ON DELETE CASCADE,
  experto_id uuid NOT NULL REFERENCES user_account(id),
  decision text NOT NULL CHECK (decision IN ('confirmar','corregir','revocar')),
  texto_corregido text,
  motivo text,
  fuentes jsonb NOT NULL DEFAULT '[]',
  created_at timestamptz NOT NULL DEFAULT now(),
  CHECK (decision <> 'corregir' OR texto_corregido IS NOT NULL),
  CHECK (decision <> 'revocar' OR motivo IS NOT NULL)
);

-- Capas de observación (NASA y socios) armonizadas a la rejilla común de 100 m
CREATE TABLE layer_value (
  cell_id integer NOT NULL REFERENCES climate_cell(cell_id) ON DELETE CASCADE,
  capa text NOT NULL,
  fecha date NOT NULL,
  valor double precision,
  sd double precision,
  unidad text NOT NULL,
  fuente text NOT NULL,
  resolucion_nativa_m integer,
  sintetico boolean NOT NULL DEFAULT false,
  PRIMARY KEY (cell_id, capa, fecha, fuente)
);
CREATE INDEX layer_value_capa_ix ON layer_value (capa, fecha);
"""


def upgrade() -> None:
    op.execute(UP)


def downgrade() -> None:
    for t in TABLAS:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("ALTER TABLE user_account DROP COLUMN IF EXISTS areas")
    op.execute("ALTER TABLE parcel DROP COLUMN IF EXISTS dibujada")
    op.execute("ALTER TABLE parcel DROP COLUMN IF EXISTS area_m2")
