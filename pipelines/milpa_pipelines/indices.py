"""Índice de vulnerabilidad por celda a partir de capas NASA ya armonizadas.

Componentes (0 = sin problema, 1 = muy vulnerable): erosión (pendiente + suelo desnudo), agua (humedad baja y
déficit de lluvia), calor (temperatura superficial) y vegetación (NDVI bajo). Umbrales y pesos: provisionales.
Si falta una capa, su componente se omite y los pesos se renormalizan; el resultado dice qué evidencia usó.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

RAIZ = Path(__file__).resolve().parents[2]


@lru_cache
def _p() -> dict[str, dict[str, float]]:
    doc = yaml.safe_load((RAIZ / "knowledge" / "model" / "vulnerabilidad.yaml").read_text(encoding="utf-8"))
    return {i["id"]: {k: v["valor"] for k, v in i["parametros"].items()} for i in doc["incertidumbre"]}


def _norm(x: float, lo: float, hi: float) -> float:
    return 0.0 if hi == lo else min(1.0, max(0.0, (x - lo) / (hi - lo)))


def _media(v: list[float] | None) -> float | None:
    return None if not v else sum(v) / len(v)


def nivel_de(indice: float | None) -> str:
    """'poco' | 'cuidado' | 'mucho' | 'sin_dato' según los umbrales provisionales."""
    if indice is None:
        return "sin_dato"
    u = _p()["vulnerabilidad_umbrales"]
    return "mucho" if indice >= u["nivel_mucho"] else "cuidado" if indice >= u["nivel_cuidado"] else "poco"


def vulnerabilidad(capas: dict[str, list[float]]) -> dict[str, Any]:
    """`capas`: valores por nombre de capa para UNA celda: srtm_pendiente_pct, ndvi_landsat, ndvi_modis,
    smap, lst (ECOSTRESS), imerg (mm/día)."""
    u, w = _p()["vulnerabilidad_umbrales"], _p()["vulnerabilidad_pesos"]
    ndvi = _media(capas.get("ndvi_s2") or capas.get("ndvi_landsat") or capas.get("ndvi_modis"))  # la de mejor resolución
    pend = _media(capas.get("srtm_pendiente_pct"))
    hum = _media(capas.get("smap"))
    lst = _media(capas.get("lst") or capas.get("lst_modis"))  # ECOSTRESS si hay; si no, MODIS
    comp: dict[str, float | None] = {
        "erosion": None if pend is None and ndvi is None else _media(
            [x for x in (None if pend is None else _norm(pend, 0, u["pendiente_max_pct"]),
                         None if ndvi is None else 1 - _norm(ndvi, u["ndvi_bajo"], u["ndvi_alto"])) if x is not None]),
        "agua": None if hum is None else 1 - _norm(hum, u["humedad_seca"], u["humedad_humeda"]),
        "calor": None if lst is None else _norm(lst, u["lst_fresca_c"], u["lst_caliente_c"]),
        "vegetacion": None if ndvi is None else 1 - _norm(ndvi, u["ndvi_bajo"], u["ndvi_alto"]),
    }
    usados = {k: v for k, v in comp.items() if v is not None}
    if not usados:
        return {"indice": None, "nivel": "sin_dato", "componentes": comp, "evidencia": []}
    tot = sum(w[k] for k in usados)
    indice = sum(w[k] * v for k, v in usados.items()) / tot
    nivel = "mucho" if indice >= u["nivel_mucho"] else "cuidado" if indice >= u["nivel_cuidado"] else "poco"
    return {"indice": indice, "nivel": nivel, "componentes": comp, "evidencia": sorted(usados)}
