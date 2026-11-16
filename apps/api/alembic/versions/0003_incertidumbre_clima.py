"""Desviación por variable en climate_daily (salida de la fusión con incertidumbre).

Revision ID: 0003
Revises: 0002
"""

from alembic import op

revision = "0003"
down_revision = "0002"

COLS = ("precip_sd", "tmax_sd", "tmin_sd", "rad_sd", "et0_sd")


def upgrade() -> None:
    for c in COLS:
        op.execute(f"ALTER TABLE climate_daily ADD COLUMN {c} real")


def downgrade() -> None:
    for c in COLS:
        op.execute(f"ALTER TABLE climate_daily DROP COLUMN IF EXISTS {c}")
