"""Graba respuestas REALES de las fuentes abiertas como fixtures (pipelines/fixtures/*.json).

Uso: uv run python scripts/record_fixtures.py   (requiere red; reintenta SoilGrids, que es lenta)
Solo consulta coordenadas públicas del municipio piloto; no envía datos de usuarios.
"""

import json
import sys
import time
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipelines"))
from milpa_pipelines.conectores import NasaPower, OpenMeteoERA5, SoilGrids, StacSentinel

c = yaml.safe_load((ROOT / "config" / "region.yaml").read_text(encoding="utf-8"))["centro"]
lat, lon = c["lat"], c["lon"]
bbox = [lon - 0.04, lat - 0.04, lon + 0.04, lat + 0.04]
P = {"inicio": "2023-05-01", "fin": "2023-10-31"}

with httpx.Client(timeout=60, follow_redirects=True) as cl:
    jobs = [
        (NasaPower(), {"lat": lat, "lon": lon, **P}),
        (OpenMeteoERA5(), {"lat": lat, "lon": lon, **P}),
        (SoilGrids(), {"lat": lat, "lon": lon}),
        (StacSentinel(), {"bbox": bbox, "inicio": "2023-06-01", "fin": "2023-08-31", "limite": 25}),
    ]
    for con, p in jobs:
        for intento in range(4):
            try:
                crudo = con.fetch(cl, **p)
                (ROOT / "pipelines" / "fixtures" / f"{con.nombre}.json").write_text(
                    json.dumps(crudo, ensure_ascii=False), encoding="utf-8")
                print("OK", con.nombre)
                break
            except Exception as e:
                print("fallo", con.nombre, intento, repr(e)[:100])
                time.sleep(3)
