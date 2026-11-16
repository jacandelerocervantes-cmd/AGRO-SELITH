"""Validación con datos de EE. UU. (condado de Hidalgo, Texas): mide el error de los productos globales que usamos en Tizimín.

Uso: uv run python -m milpa_pipelines.validacion_eeuu   (necesita red; escribe docs/validacion_eeuu.json y fixtures)
Las pruebas recalculan las métricas desde los fixtures, sin red.
"""

from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from .eeuu import CdlRotacion, Naip, Ssurgo
from .nasa import LandsatNdvi, Sentinel2Ndvi

RAIZ = Path(__file__).resolve().parents[2]
FIX = RAIZ / "pipelines" / "fixtures" / "eeuu"
LAT, LON = 26.28, -97.93  # cultivos de algodón, sorgo y caña cerca de La Villa, condado de Hidalgo (FIPS 48215)
BBOX = [LON - 0.006, LAT - 0.006, LON + 0.006, LAT + 0.006]


def _arr(v: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if x is None else x for x in f] for f in v], dtype=float)


def a_rejilla(origen: np.ndarray, forma: tuple[int, int]) -> np.ndarray:
    """Promedia `origen` (más fino) hasta la rejilla `forma` (más gruesa) por bloques que cubren la misma zona."""
    h, w = forma
    H, W = origen.shape
    out = np.full(forma, np.nan)
    for i in range(h):
        for j in range(w):
            blq = origen[i * H // h:max((i + 1) * H // h, i * H // h + 1), j * W // w:max((j + 1) * W // w, j * W // w + 1)]
            if np.isfinite(blq).any():
                out[i, j] = np.nanmean(blq)
    return out


def comparar_ndvi(referencia: np.ndarray, producto: np.ndarray) -> dict[str, float | int]:
    """Métricas del NDVI de un satélite contra la referencia de 1 m (NAIP) llevada a su misma rejilla."""
    ref = a_rejilla(referencia, producto.shape)
    m = np.isfinite(ref) & np.isfinite(producto)
    if m.sum() < 20:
        raise ValueError("muy pocos píxeles en común")
    d = producto[m] - ref[m]
    return {"n_pixeles": int(m.sum()), "correlacion": float(np.corrcoef(ref[m], producto[m])[0, 1]),
            "sesgo": float(d.mean()), "rmse": float(np.sqrt((d**2).mean())), "ndvi_ref_medio": float(ref[m].mean())}


def mejor_escena(escenas: list[dict[str, Any]]) -> dict[str, Any]:
    return max(escenas, key=lambda e: np.isfinite(_arr(e["valores"])).mean())


def resumen_rotacion(cdl: dict[str, Any]) -> dict[str, Any]:
    """Cultivo dominante por año, cuántas veces cambia de un año a otro y el reparto de cultivos."""
    dom = [(a["anio"], next(iter(a["distribucion"])), next(iter(a["distribucion"].values()))) for a in cdl["anios"]]
    cambios = sum(1 for (_, c0, _), (_, c1, _) in zip(dom, dom[1:], strict=False) if c0 != c1)
    cuenta: dict[str, int] = {}
    for _, c, _ in dom:
        cuenta[c] = cuenta.get(c, 0) + 1
    return {"anios": [d[0] for d in dom], "dominante_por_anio": {d[0]: d[1] for d in dom}, "cambios_de_un_anio_al_siguiente": cambios,
            "transiciones_posibles": len(dom) - 1, "anios_por_cultivo": dict(sorted(cuenta.items(), key=lambda x: -x[1]))}


def comparar_suelo(ssurgo: dict[str, Any], soilgrids: dict[str, Any]) -> dict[str, Any]:
    """SoilGrids (global) contra SSURGO (medido). SoilGrids: arcilla/arena/limo en g/kg, soc en dg/kg, pH x10 (ya escalados por el conector)."""
    pares = {
        "arcilla_pct": (ssurgo["arcilla_pct"], soilgrids.get("clay")),
        "arena_pct": (ssurgo["arena_pct"], soilgrids.get("sand")),
        "materia_organica_pct": (ssurgo["materia_organica_pct"], None if soilgrids.get("soc") is None else soilgrids["soc"] / 10 * 1.724),
        "ph": (ssurgo["ph"], soilgrids.get("phh2o")),
    }
    out: dict[str, Any] = {}
    for k, (ref, sg) in pares.items():
        if ref in (None, 0) or sg is None:
            continue
        out[k] = {"ssurgo": ref, "soilgrids": sg, "error_relativo": abs(sg - ref) / abs(ref)}
    if out:
        out["cv_relativo_medio"] = float(np.mean([v["error_relativo"] for v in out.values() if isinstance(v, dict)]))
    return out


def calcular(fx: dict[str, Any]) -> dict[str, Any]:
    """Todas las métricas a partir de las respuestas crudas (se usa igual en vivo y en las pruebas)."""
    res: dict[str, Any] = {"lugar": {"condado": "Hidalgo, Texas (FIPS 48215)", "lat": LAT, "lon": LON}}
    suelo = Ssurgo().parsear(fx["ssurgo"])
    res["suelo_ssurgo"] = suelo
    if fx.get("soilgrids"):
        from .conectores import SoilGrids

        res["soilgrids_vs_ssurgo"] = comparar_suelo(suelo, SoilGrids().parsear(fx["soilgrids"]))
    res["rotacion_cdl"] = resumen_rotacion(fx["cdl"])
    naip = _arr(fx["naip"]["valores"])
    res["naip"] = {"fecha": fx["naip"]["fecha"], "resolucion_m": fx["naip"]["resolucion_m"], "ndvi_medio": float(np.nanmean(naip))}
    for clave, nombre in (("sentinel2", "sentinel2_10m"), ("landsat", "landsat_30m")):
        if fx.get(clave) and fx[clave].get("escenas"):
            e = mejor_escena(fx[clave]["escenas"])
            res[f"ndvi_{nombre}_vs_naip"] = {"fecha_escena": e["fecha"], **comparar_ndvi(naip, _arr(e["valores"]))}
    return res


def ejecutar() -> dict[str, Any]:
    FIX.mkdir(parents=True, exist_ok=True)
    fx: dict[str, Any] = {}
    p = {"lat": LAT, "lon": LON, "bbox": BBOX}
    with httpx.Client() as c:
        fx["ssurgo"] = Ssurgo().fetch(c, **p)
        fx["cdl"] = CdlRotacion().fetch(c, **p, inicio="2008-01-01", fin="2023-12-31")
        fx["naip"] = Naip().fetch(c, **p, inicio="2018-01-01", fin="2023-12-31")
        f = date.fromisoformat(fx["naip"]["fecha"])
        ventana = {"inicio": (f - timedelta(days=45)).isoformat(), "fin": (f + timedelta(days=45)).isoformat()}
        for clave, cls in (("sentinel2", Sentinel2Ndvi), ("landsat", LandsatNdvi)):
            try:
                fx[clave] = cls().fetch(c, **p, **ventana)
            except Exception as e:  # noqa: BLE001
                print("sin", clave, "en la ventana de NAIP:", e, file=sys.stderr)
        try:
            from .conectores import SoilGrids

            fx["soilgrids"] = SoilGrids().fetch(c, **p)
        except Exception as e:  # noqa: BLE001
            print("SoilGrids no respondió:", e, file=sys.stderr)
    for k, v in fx.items():
        (FIX / f"{k}.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    res = calcular(fx)
    (RAIZ / "docs" / "validacion_eeuu.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    return res


def cargar_fixtures() -> dict[str, Any]:
    return {f.stem: json.loads(f.read_text(encoding="utf-8")) for f in FIX.glob("*.json")}


if __name__ == "__main__":
    print(json.dumps(ejecutar(), ensure_ascii=False, indent=1, default=float))
