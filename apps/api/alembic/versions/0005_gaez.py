"""Idoneidad y rendimiento alcanzable de FAO GAEZ por parcela.

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE parcel_gaez (
          parcel_id uuid NOT NULL REFERENCES parcel(id) ON DELETE CASCADE,
          cultivo text NOT NULL,
          escenario text NOT NULL CHECK (escenario IN ('hist_bajo','hist_alto','fut45','fut85')),
          indice real, indice_min real, indice_max real,
          rendimiento_kg_ms_ha real,
          n_modelos integer NOT NULL DEFAULT 1,
          fuente text NOT NULL,
          sintetico boolean NOT NULL DEFAULT false,
          PRIMARY KEY (parcel_id, cultivo, escenario)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS parcel_gaez")
