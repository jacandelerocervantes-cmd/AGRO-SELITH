"""Idempotencia de la sincronización offline: client_id en decisiones y preguntas.

Revision ID: 0002
Revises: 0001
"""

from alembic import op

revision = "0002"
down_revision = "0001"


def upgrade() -> None:
    for t in ("farmer_decision", "producer_question"):
        op.execute(f"ALTER TABLE {t} ADD COLUMN client_id uuid UNIQUE")
        op.execute(f"ALTER TABLE {t} ADD COLUMN offline boolean NOT NULL DEFAULT false")


def downgrade() -> None:
    for t in ("farmer_decision", "producer_question"):
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS offline")
        op.execute(f"ALTER TABLE {t} DROP COLUMN IF EXISTS client_id")
