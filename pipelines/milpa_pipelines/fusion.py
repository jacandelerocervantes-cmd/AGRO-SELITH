"""Fusión espacial con incertidumbre.

Qué hace con los datos que HAY hoy (honesto):
- Rejilla común de 100 m (UTM 16N para el cálculo, WGS84 para guardar) y pesos parcela↔celda por área.
- Clima: fusiona dos fuentes independientes (NASA POWER y ERA5); la desviación es la discrepancia entre
  fuentes (con piso provisional). Si se entregan estaciones (SMN/CONAGUA) aplica quantile mapping antes.
  SIN estaciones ni CEM el campo es constante en el espacio: no se inventa variación entre parcelas.
- Suelo: SoilGrids como prior con incertidumbre alta (kárstico); si hay INEGI, mezcla por varianza inversa.
- Vegetación: cuantifica cuántas escenas ópticas útiles hay (nubosidad) y cuándo hace falta SAR.
Los parámetros (pisos, umbrales) viven en knowledge/model/incertidumbre.yaml, con fuente y estatus.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import shapely
import yaml
from pyproj import Transformer
from shapely.geometry import Polygon, box, shape

RAIZ = Path(__file__).resolve().parents[2]
UTM = "EPSG:32616"  # UTM 16N (península de Yucatán oriental)
_A_UTM = Transformer.from_crs("EPSG:4326", UTM, always_xy=True)
_A_WGS = Transformer.from_crs(UTM, "EPSG:4326", always_xy=True)


def transform(tr: Transformer, geom: Any) -> Any:
    return shapely.transform(geom, lambda c: np.column_stack(tr.transform(c[:, 0], c[:, 1])))


@lru_cache
def parametros() -> dict[str, dict[str, Any]]:
    doc = yaml.safe_load((RAIZ / "knowledge" / "model" / "incertidumbre.yaml").read_text(encoding="utf-8"))
    return {i["id"]: {k: v["valor"] for k, v in i["parametros"].items()} for i in doc["incertidumbre"]}


# ---------------------------------------------------------------- rejilla
@dataclass(frozen=True)
class Celda:
    cell_id: int
    geom: Polygon  # WGS84
    res_m: int


def crear_rejilla(bbox_wgs84: tuple[float, float, float, float], res_m: int = 100) -> list[Celda]:
    """Celdas cuadradas de res_m metros alineadas a la rejilla UTM que cubren el bbox (lon0, lat0, lon1, lat1)."""
    x0, y0 = _A_UTM.transform(bbox_wgs84[0], bbox_wgs84[1])
    x1, y1 = _A_UTM.transform(bbox_wgs84[2], bbox_wgs84[3])
    i0, j0 = math.floor(x0 / res_m), math.floor(y0 / res_m)
    i1, j1 = math.ceil(x1 / res_m), math.ceil(y1 / res_m)
    celdas, n = [], 1
    for j in range(j0, j1):
        for i in range(i0, i1):
            utm = box(i * res_m, j * res_m, (i + 1) * res_m, (j + 1) * res_m)
            celdas.append(Celda(n, transform(_A_WGS, utm), res_m))
            n += 1
    return celdas


def pesos_parcela_celda(parcela_geojson: dict[str, Any], celdas: list[Celda]) -> dict[int, float]:
    """Fracción del área de la parcela que cae en cada celda (suman 1 si la rejilla cubre la parcela)."""
    p = transform(_A_UTM, shape(parcela_geojson))
    areas = {}
    for c in celdas:
        a = p.intersection(transform(_A_UTM, c.geom)).area
        if a > 0:
            areas[c.cell_id] = a
    total = sum(areas.values())
    if total == 0:
        raise ValueError("la rejilla no cubre la parcela")
    return {k: v / total for k, v in areas.items()}


# ---------------------------------------------------------------- clima
def quantile_mapping(modelo: np.ndarray, referencia: np.ndarray, n: int = 100) -> Callable[[np.ndarray], np.ndarray]:
    """Quantile mapping empírico: lleva la distribución del modelo a la de la referencia (estaciones)."""
    q = np.linspace(0.0, 1.0, n + 1)
    mq, rq = np.quantile(modelo, q), np.quantile(referencia, q)
    return lambda x: np.interp(np.asarray(x, dtype=float), mq, rq)


VARS = ("precip_mm", "tmax", "tmin", "rad_mj", "et0_mm")


def _piso(v: str) -> float:
    p = parametros()["pisos_clima"]
    return float(p["precip_mm"] if v == "precip_mm" else p["rad_mj"] if v == "rad_mj" else p["et0_mm"] if v == "et0_mm" else p["temp_c"])


def fusionar_clima(
    power: list[dict[str, Any]], era5: list[dict[str, Any]], estaciones: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """Serie diaria fusionada con media y desviación por variable (`<var>_sd`)."""
    a = {r["fecha"]: r for r in power}
    b = {r["fecha"]: r for r in era5}
    fechas = sorted(set(a) & set(b))
    corr: dict[str, tuple[Callable[..., Any], Callable[..., Any]]] = {}
    if estaciones:
        est = {r["fecha"]: r for r in estaciones}
        comunes = [f for f in fechas if f in est]
        for v in ("precip_mm", "tmax", "tmin", "rad_mj"):
            ref = np.array([est[f][v] for f in comunes if est[f].get(v) is not None], dtype=float)
            if len(ref) < 30:
                continue
            ma = np.array([a[f][v] for f in comunes if a[f].get(v) is not None], dtype=float)
            mb = np.array([b[f][v] for f in comunes if b[f].get(v) is not None], dtype=float)
            if len(ma) >= 30 and len(mb) >= 30:
                corr[v] = (quantile_mapping(ma, ref), quantile_mapping(mb, ref))
    out = []
    for f in fechas:
        fila: dict[str, Any] = {"fecha": f}
        for v in VARS:
            xa, xb = a[f].get(v), b[f].get(v)
            if v in corr:
                xa = float(corr[v][0](xa)) if xa is not None else None
                xb = float(corr[v][1](xb)) if xb is not None else None
            vals = [x for x in (xa, xb) if x is not None]
            if not vals:
                fila[v] = fila[f"{v}_sd"] = None
                continue
            media = sum(vals) / len(vals)
            disc = abs(vals[0] - vals[1]) / 2 if len(vals) == 2 else 0.0
            fila[v] = max(media, 0.0) if v == "precip_mm" else media
            fila[f"{v}_sd"] = max(disc, _piso(v))
        out.append(fila)
    return out


def racha_seca_max(serie: list[dict[str, Any]]) -> int:
    """Días secos consecutivos más largos dentro de la ventana de canícula (parámetros en knowledge)."""
    p = parametros()["canicula"]
    mejor = actual = 0
    for r in serie:
        mes = int(r["fecha"][5:7])
        if p["mes_inicio"] <= mes <= p["mes_fin"] and r["precip_mm"] is not None and r["precip_mm"] < p["dia_seco_mm"]:
            actual += 1
            mejor = max(mejor, actual)
        else:
            actual = 0
    return mejor


# ---------------------------------------------------------------- suelo
def fusionar_suelo(
    soilgrids: dict[str, Any], inegi: dict[str, tuple[float, float]] | None = None
) -> dict[str, dict[str, Any]]:
    """SoilGrids (prior, incertidumbre alta en karst) + INEGI opcional por varianza inversa."""
    cv = float(parametros()["suelo_karst"]["cv_relativo"])
    out: dict[str, dict[str, Any]] = {}
    for prop, val in soilgrids.items():
        if prop == "baja_confianza_karst":
            continue
        if val is None:
            out[prop] = {"valor": None, "sd": None, "fuente": "SoilGrids (sin dato)", "confianza": "sin dato"}
            continue
        sd = abs(val) * cv
        fila = {"valor": float(val), "sd": sd, "fuente": "SoilGrids", "confianza": "baja"}
        if inegi and prop in inegi and inegi[prop][1] > 0 and sd > 0:
            v2, s2 = inegi[prop]
            w1, w2 = 1 / sd**2, 1 / s2**2
            fila = {"valor": (val * w1 + v2 * w2) / (w1 + w2), "sd": math.sqrt(1 / (w1 + w2)),
                    "fuente": "SoilGrids+INEGI", "confianza": "media"}
        out[prop] = fila
    for prop, (v2, s2) in (inegi or {}).items():
        if prop not in out:
            out[prop] = {"valor": v2, "sd": s2, "fuente": "INEGI", "confianza": "media"}
    return out


# ---------------------------------------------------------------- vegetación
def disponibilidad_optica(escenas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Por mes: escenas totales, útiles (poca nube) y si hace falta SAR (Sentinel-1)."""
    p = parametros()["vegetacion"]
    meses: dict[str, list[float | None]] = defaultdict(list)
    for e in escenas:
        meses[e["fecha"][:7]].append(e["nubosidad_pct"])
    out = []
    for mes in sorted(meses):
        nubes = meses[mes]
        utiles = sum(1 for n in nubes if n is not None and n <= p["umbral_nubes_pct"])
        frac = utiles / len(nubes)
        out.append({"mes": mes, "escenas": len(nubes), "utiles": utiles, "fraccion_util": frac,
                    "requiere_sar": frac < p["fraccion_minima_optica"]})
    return out
