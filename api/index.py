"""Punto de entrada de la API en Vercel (función Python). Las rutas públicas son /api/... (la web las llama así)."""

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
for ruta in ("apps/api", "packages/engine/src", "pipelines"):
    sys.path.insert(0, str(RAIZ / ruta))

from fastapi import FastAPI  # noqa: E402
from milpa_api.main import app as milpa  # noqa: E402

app = FastAPI(title="SELITH AGRO")
app.mount("/api", milpa)
