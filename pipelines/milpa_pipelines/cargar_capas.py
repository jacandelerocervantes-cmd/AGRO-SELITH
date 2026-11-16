"""Carga a PostGIS las capas NASA armonizadas a la rejilla de 100 m y el índice de vulnerabilidad por celda."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict
from typing import Any

import numpy as np
import psycopg
from shapely import wkt
from shapely.ops import unary_union

from .armonizar import compuesto_ndvi, pendiente_pct, raster_a_celdas, serie_a_celdas
from .fusion import Celda
from .indices import vulnerabilidad
from .nasa import CAPAS_NASA

log = logging.getLogger("milpa.capas")
PERIODO = ("2023-05-01", "2023-10-31")


def _celdas(cur: psycopg.Cursor) -> list[Celda]:
    return [Celda(cid, wkt.loads(g), res) for cid, g, res in cur.execute(
        "SELECT cell_id, ST_AsText(geom), res_m FROM climate_cell ORDER BY cell_id").fetchall()]


def cargar_capas(conn: psycopg.Connection, modo: str = "demo", periodo: tuple[str, str] = PERIODO) -> dict[str, Any]:
    cur = conn.cursor()
    celdas = _celdas(cur)
    if not celdas:
        raise RuntimeError("no hay rejilla: corra primero la fusión (scripts/cargar_fusion.py)")
    x0, y0, x1, y1 = unary_union([c.geom for c in celdas]).bounds
    bbox = [x0, y0, x1, y1]
    lat, lon = (y0 + y1) / 2, (x0 + x1) / 2
    conn.commit()  # cierra la transacción de lectura: las descargas tardan minutos y Neon corta conexiones inactivas en transacción
    ini, fin = periodo
    filas: list[tuple[Any, ...]] = []
    estado: dict[str, dict[str, Any]] = {}

    excluir = {c.strip() for c in os.environ.get("MILPA_EXCLUIR", "").split(",") if c.strip()}
    solo = {c.strip() for c in os.environ.get("MILPA_CAPAS", "").split(",") if c.strip()}
    for capa, cls in CAPAS_NASA.items():
        if (solo and capa not in solo) or capa in excluir:
            continue
        t0 = time.monotonic()
        print(f"[{capa}] consultando...", flush=True)
        try:
            r = cls(modo=modo).obtener(lat=lat, lon=lon, bbox=bbox, inicio=ini, fin=fin)
            print(f"[{capa}] listo en {time.monotonic() - t0:.0f} s (origen: {r.origen})", flush=True)
        except Exception as e:  # noqa: BLE001 - una capa caída no tumba las demás
            print(f"[{capa}] NO disponible tras {time.monotonic() - t0:.0f} s: {str(e)[:120]}", flush=True)
            log.warning("capa %s no disponible: %s", capa, e)
            estado[capa] = {"disponible": False, "fuente": cls.fuente, "sintetico": False}
            continue
        d, sint = r.datos, r.sintetico or bool(r.datos.get("sintetico"))
        estado[capa] = {"disponible": True, "fuente": r.fuente, "sintetico": sint, "origen": r.origen}
        if capa in ("ndvi_landsat", "ndvi_s2") and d.get("escenas"):
            comp, fecha = compuesto_ndvi(d["escenas"])
            filas += raster_a_celdas({**d, "bbox": d["escenas"][0]["bbox"]}, celdas, capa, r.fuente, sint, fecha, comp)
        elif capa == "srtm" and d.get("valores"):
            filas += raster_a_celdas(d, celdas, "srtm_elevacion", r.fuente, sint, fin)
            filas += raster_a_celdas({**d, "unidad": "%"}, celdas, "srtm_pendiente_pct", r.fuente, sint, fin, pendiente_pct(d))
        elif d.get("serie"):
            nombre = "lst" if capa == "ecostress" else capa
            filas += serie_a_celdas(d, celdas, nombre, r.fuente, sint)
            if d.get("serie_et"):
                filas += serie_a_celdas({**d, "unidad": "kg/m²/s"}, celdas, "gldas_et", r.fuente, sint, "serie_et")

    if solo:  # diagnóstico por capa: no escribe en la base (el índice de vulnerabilidad necesita todas las capas juntas)
        print("Modo diagnóstico (MILPA_CAPAS): no se escribió nada en la base.", flush=True)
        return {"celdas": len(celdas), "filas": 0, "vulnerabilidad": 0, "capas": estado}

    filas = [f for f in filas if f[3] is not None]  # una capa sin ningún valor no cuenta como disponible
    capas_db = sorted({f[1] for f in filas})
    cur.execute("DELETE FROM layer_value WHERE capa = ANY(%s) OR capa='vulnerabilidad'", (capas_db,))
    cur.executemany(
        """INSERT INTO layer_value(cell_id,capa,fecha,valor,sd,unidad,fuente,resolucion_nativa_m,sintetico)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
        [(f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8]) for f in filas],
    )

    por_celda: dict[int, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    sint_celda: dict[int, bool] = defaultdict(bool)
    for cid, capa, _f, v, *_ in filas:
        if v is not None and np.isfinite(v):
            por_celda[cid][capa].append(float(v))
        sint_celda[cid] |= bool(_[-1])
    vul = []
    for c in celdas:
        v = vulnerabilidad(dict(por_celda[c.cell_id]))
        if v["indice"] is not None:
            vul.append((c.cell_id, "vulnerabilidad", fin, v["indice"], None, "índice 0-1", "derivada (NASA)", c.res_m, sint_celda[c.cell_id]))
    cur.executemany(
        """INSERT INTO layer_value(cell_id,capa,fecha,valor,sd,unidad,fuente,resolucion_nativa_m,sintetico)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""", vul)
    conn.commit()
    return {"celdas": len(celdas), "filas": len(filas), "vulnerabilidad": len(vul), "capas": estado}
