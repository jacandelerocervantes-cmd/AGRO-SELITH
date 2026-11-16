"""Corre los conectores y carga la fusión a la base. Uso: uv run python scripts/cargar_fusion.py [auto|demo]"""

import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipelines"))
from milpa_pipelines.cargar_bd import cargar_fusion  # noqa: E402

url = os.environ.get("DATABASE_URL", "postgresql://milpa:milpa_dev_only@localhost:5432/milpa").replace(
    "postgresql+psycopg", "postgresql"
)
with psycopg.connect(url) as conn:
    print(cargar_fusion(conn, sys.argv[1] if len(sys.argv) > 1 else "demo"))
