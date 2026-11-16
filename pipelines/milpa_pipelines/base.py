"""Base de conectores: fetch() real + caché + fallback a fixtures (modo demo sin llaves).

Orden en modo "auto": vivo (2 reintentos) -> caché -> fixture.  En modo "demo" no se toca la red:
caché -> fixture.  Cada resultado declara su origen y si es sintético.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("milpa.pipelines")
AQUI = Path(__file__).resolve().parent
FIXTURES = AQUI.parent / "fixtures"
CACHE = AQUI.parent / ".cache"


class ConectorNoConfigurado(RuntimeError):
    """Falta URL/llave del servicio: se usa el fallback."""


@dataclass(frozen=True)
class Resultado:
    datos: Any
    origen: str  # "vivo" | "cache" | "fixture"
    sintetico: bool
    fuente: str
    consultado_en: str


class Conector(ABC):
    nombre: str
    fuente: str

    def __init__(
        self,
        modo: str = "auto",
        cache_dir: Path = CACHE,
        fixtures_dir: Path = FIXTURES,
        client: httpx.Client | None = None,
        reintentos: int = 2,
        espera_s: float = 0.5,
    ) -> None:
        if modo not in ("auto", "demo"):
            raise ValueError("modo debe ser 'auto' o 'demo'")
        self.modo, self.cache_dir, self.fixtures_dir = modo, cache_dir, fixtures_dir
        self.client, self.reintentos, self.espera_s = client, reintentos, espera_s

    # ---- a implementar por cada conector ----
    @abstractmethod
    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        """Consulta real; devuelve la respuesta cruda (JSON/texto serializable)."""

    @abstractmethod
    def parsear(self, crudo: Any, **p: Any) -> Any:
        """Normaliza la respuesta cruda."""

    def fallback_sintetico(self, **p: Any) -> Any:
        """Respuesta cruda sintética (solo si no hay fixture real). Por defecto no hay."""
        raise FileNotFoundError(f"sin fixture sintético para {self.nombre}")

    # ---- infraestructura ----
    def _clave(self, p: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(p, sort_keys=True, default=str).encode()).hexdigest()[:16]

    def _ruta_cache(self, p: dict[str, Any]) -> Path:
        return self.cache_dir / self.nombre / f"{self._clave(p)}.json"

    def _res(self, crudo: Any, origen: str, sintetico: bool, p: dict[str, Any]) -> Resultado:
        return Resultado(
            self.parsear(crudo, **p), origen, sintetico, self.fuente, datetime.now(UTC).isoformat()
        )

    def obtener(self, **p: Any) -> Resultado:
        if self.modo == "auto":
            crudo = self._vivo(p)
            if crudo is not None:
                ruta = self._ruta_cache(p)
                ruta.parent.mkdir(parents=True, exist_ok=True)
                ruta.write_text(json.dumps(crudo, ensure_ascii=False), encoding="utf-8")
                return self._res(crudo, "vivo", False, p)
        ruta = self._ruta_cache(p)
        if ruta.exists():
            return self._res(json.loads(ruta.read_text(encoding="utf-8")), "cache", False, p)
        fx = self.fixtures_dir / f"{self.nombre}.json"
        if fx.exists():  # dato real grabado de la fuente
            return self._res(json.loads(fx.read_text(encoding="utf-8")), "fixture", False, p)
        return self._res(self.fallback_sintetico(**p), "fixture", True, p)

    def _vivo(self, p: dict[str, Any]) -> Any | None:
        propio = self.client is None
        client = self.client or httpx.Client(timeout=30.0, follow_redirects=True)
        try:
            for intento in range(1, self.reintentos + 1):
                try:
                    return self.fetch(client, **p)
                except ConectorNoConfigurado as e:
                    log.info("%s: %s; usando fallback", self.nombre, e)
                    return None
                except (httpx.HTTPError, ValueError, KeyError) as e:
                    log.warning("%s: intento %d/%d falló: %s", self.nombre, intento, self.reintentos, e)
                    if intento < self.reintentos:
                        time.sleep(self.espera_s)
            return None
        finally:
            if propio:
                client.close()
