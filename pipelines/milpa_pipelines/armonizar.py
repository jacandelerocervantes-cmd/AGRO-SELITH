"""Armonización de capas con resoluciones distintas a la rejilla común de 100 m (reto Field Shift).

- Series de baja resolución (SMAP 9 km, IMERG 10 km, GLDAS 25 km, MODIS 250 m...): el valor se asigna a cada
  celda y su desviación crece con la brecha de resolución (parámetro provisional en knowledge/model).
- Rásteres de alta resolución (Landsat 30 m, SRTM 30 m): se agregan por celda (media y desviación de los píxeles),
  así que SÍ hay variación entre parcelas.
- Derivados: pendiente (%) desde la elevación; NDVI compuesto de Landsat.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from .fusion import Celda, parametros

Fila = tuple[int, str, str, float | None, float | None, str, str, int, bool]  # a layer_value


def _arr(valores: list[list[float | None]]) -> np.ndarray:
    return np.array([[np.nan if v is None else v for v in fila] for fila in valores], dtype=float)


def _sd_downscale(valor: float, res_nativa: int, res_celda: int, sd_base: float | None = None) -> float:
    p = parametros()["armonizacion"]
    decadas = max(0.0, math.log10(max(res_nativa, 1) / res_celda))
    sd = abs(valor) * float(p["factor_downscale"]) * decadas
    return max(sd, abs(valor) * float(p["sd_minimo_fraccion"]), sd_base or 0.0)


def serie_a_celdas(raw: dict[str, Any], celdas: list[Celda], capa: str, fuente: str, sintetico: bool, clave: str = "serie") -> list[Fila]:
    res = int(raw.get("resolucion_m", 100))
    out: list[Fila] = []
    for s in raw.get(clave, []):
        v = s["valor"]
        sd = None if v is None else _sd_downscale(float(v), res, celdas[0].res_m)
        for c in celdas:
            out.append((c.cell_id, capa, s["fecha"], v, sd, raw.get("unidad", ""), fuente, res, sintetico))
    return out


def raster_por_celda(valores: np.ndarray, bbox: list[float], celdas: list[Celda]) -> dict[int, tuple[float, float]]:
    """Media y desviación de los píxeles cuyo centro cae en cada celda; si ninguno, el píxel más cercano."""
    h, w = valores.shape
    w0, s0, e0, n0 = bbox
    lon = w0 + (np.arange(w) + 0.5) * (e0 - w0) / w
    lat = n0 - (np.arange(h) + 0.5) * (n0 - s0) / h
    LON, LAT = np.meshgrid(lon, lat)
    out: dict[int, tuple[float, float]] = {}
    for c in celdas:
        x0, y0, x1, y1 = c.geom.bounds
        m = (x0 <= LON) & (x1 >= LON) & (y0 <= LAT) & (y1 >= LAT) & np.isfinite(valores)
        if m.any():
            out[c.cell_id] = (float(valores[m].mean()), float(valores[m].std()))
            continue
        cx, cy = c.geom.centroid.x, c.geom.centroid.y
        d = np.where(np.isfinite(valores), (LON - cx) ** 2 + (LAT - cy) ** 2, np.inf)
        if np.isfinite(d).any() and d.min() < np.inf:
            i = np.unravel_index(d.argmin(), d.shape)
            out[c.cell_id] = (float(valores[i]), 0.0)
    return out


def raster_a_celdas(raw: dict[str, Any], celdas: list[Celda], capa: str, fuente: str, sintetico: bool, fecha: str, valores: np.ndarray | None = None) -> list[Fila]:
    v = _arr(raw["valores"]) if valores is None else valores
    res = int(raw.get("resolucion_m", 30))
    return [
        (cid, capa, fecha, m, sd, raw.get("unidad", ""), fuente, res, sintetico)
        for cid, (m, sd) in raster_por_celda(v, raw["bbox"], celdas).items()
    ]


def pendiente_pct(raw: dict[str, Any]) -> np.ndarray:
    """Pendiente en % a partir de una elevación (m) en cuadrícula lon/lat."""
    z = _arr(raw["valores"])
    w0, s0, e0, n0 = raw["bbox"]
    h, w = z.shape
    lat_med = math.radians((s0 + n0) / 2)
    dx = (e0 - w0) / w * 111_320 * math.cos(lat_med)
    dy = (n0 - s0) / h * 110_540
    gy, gx = np.gradient(z, dy, dx)
    return np.hypot(gx, gy) * 100.0


def compuesto_ndvi(escenas: list[dict[str, Any]]) -> tuple[np.ndarray, str]:
    """Compuesto de NDVI (mediana de las escenas sin nube) y la fecha más reciente."""
    pila = np.stack([_arr(e["valores"]) for e in escenas])
    with np.errstate(all="ignore"):
        return np.nanmedian(pila, axis=0), max(e["fecha"] for e in escenas)
