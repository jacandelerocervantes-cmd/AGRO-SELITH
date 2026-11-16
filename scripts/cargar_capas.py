"""Carga las capas NASA armonizadas a la rejilla de 100 m. Uso: uv run python scripts/cargar_capas.py [auto|demo]
Requiere la fusión previa (scripts/cargar_fusion.py). Sin cuenta Earthdata, las capas que la necesitan salen como ejemplo."""

import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipelines"))
from milpa_pipelines.cargar_capas import cargar_capas  # noqa: E402

url = os.environ.get("DATABASE_URL", "postgresql://milpa:milpa_dev_only@localhost:5432/milpa").replace("postgresql+psycopg", "postgresql")
with psycopg.connect(url) as conn:
    r = cargar_capas(conn, sys.argv[1] if len(sys.argv) > 1 else "demo")
    print({k: v for k, v in r.items() if k != "capas"})
    for capa, e in r["capas"].items():
        print(f"  {capa:13s} disponible={e['disponible']} sintetico={e['sintetico']} {e.get('origen', '')}")
