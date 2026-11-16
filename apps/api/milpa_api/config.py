from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "engine" / "src"))

from milpa_engine.knowledge import Conocimiento, cargar


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "postgresql://milpa:milpa_dev_only@localhost:5432/milpa")
    return url.replace("postgresql+psycopg", "postgresql")


def modo_demo() -> bool:
    """Roles de prueba sin correo. NUNCA activar en producción (MILPA_DEMO=0)."""
    return os.environ.get("MILPA_DEMO", "1") == "1"


@lru_cache
def conocimiento() -> Conocimiento:
    return cargar(ROOT / "knowledge")


@lru_cache
def llm_config() -> dict:
    return yaml.safe_load((ROOT / "config" / "llm.yaml").read_text(encoding="utf-8"))
