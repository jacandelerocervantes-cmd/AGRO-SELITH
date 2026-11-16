"""Carga a PostGIS la rejilla, los pesos parcela↔celda, el clima fusionado y el suelo por parcela.

Idempotente: reemplaza lo anterior. Usa los conectores (modo "demo" = caché/fixtures reales; "auto" = vivo).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import yaml
from shapely.geometry import shape
from shapely.ops import unary_union

from .conectores import NasaPower, OpenMeteoERA5, SoilGrids
from .fusion import crear_rejilla, fusionar_clima, fusionar_suelo, pesos_parcela_celda

FUENTE_CLIMA = "fusion(POWER,ERA5)"
PERIODO = ("2023-05-01", "2023-10-31")  # periodo de los fixtures reales grabados
RAIZ = Path(__file__).resolve().parents[2]


def centro_region() -> tuple[float, float]:
    c = yaml.safe_load((RAIZ / "config" / "region.yaml").read_text(encoding="utf-8"))["centro"]
    return c["lat"], c["lon"]


def cargar_fusion(conn: psycopg.Connection, modo: str = "demo", res_m: int = 100) -> dict[str, Any]:
    cur = conn.cursor()
    parcelas = cur.execute("SELECT id, ST_AsGeoJSON(geom) FROM parcel ORDER BY nombre").fetchall()
    if not parcelas:
        raise RuntimeError("no hay parcelas: corra primero make seed")
    geoms = {pid: json.loads(g) for pid, g in parcelas}
    x0, y0, x1, y1 = unary_union([shape(g) for g in geoms.values()]).buffer(0.002).bounds
    celdas = crear_rejilla((x0, y0, x1, y1), res_m)
    pesos = {pid: pesos_parcela_celda(g, celdas) for pid, g in geoms.items()}
    usadas = sorted({c for w in pesos.values() for c in w})

    cur.execute("DELETE FROM parcel_cell")
    cur.execute("DELETE FROM climate_daily WHERE fuente=%s", (FUENTE_CLIMA,))
    cur.execute("DELETE FROM climate_cell WHERE cell_id NOT IN (SELECT cell_id FROM climate_daily)")
    por_id = {c.cell_id: c for c in celdas}
    for cid in usadas:
        cur.execute(
            "INSERT INTO climate_cell(cell_id,geom,res_m) VALUES (%s,ST_GeomFromText(%s,4326),%s) "
            "ON CONFLICT (cell_id) DO UPDATE SET geom=EXCLUDED.geom, res_m=EXCLUDED.res_m",
            (cid, por_id[cid].geom.wkt, res_m),
        )
    for pid, w in pesos.items():
        cur.executemany(
            "INSERT INTO parcel_cell(parcel_id,cell_id,peso) VALUES (%s,%s,%s)", [(pid, c, p) for c, p in w.items()]
        )

    lat, lon = centro_region()
    ini, fin = PERIODO
    p = NasaPower(modo=modo).obtener(lat=lat, lon=lon, inicio=ini, fin=fin)
    e = OpenMeteoERA5(modo=modo).obtener(lat=lat, lon=lon, inicio=ini, fin=fin)
    serie = fusionar_clima(p.datos, e.datos)
    filas = [
        (cid, r["fecha"], r["precip_mm"], r["tmax"], r["tmin"], r["rad_mj"], r["et0_mm"], FUENTE_CLIMA,
         r["precip_mm_sd"], r["tmax_sd"], r["tmin_sd"], r["rad_mj_sd"], r["et0_mm_sd"])
        for cid in usadas
        for r in serie
    ]
    cur.executemany(
        """INSERT INTO climate_daily(cell_id,fecha,precip_mm,tmax,tmin,rad_mj,et0_mm,fuente,
             precip_sd,tmax_sd,tmin_sd,rad_sd,et0_sd) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        filas,
    )

    suelos = 0
    for pid, g in geoms.items():
        c = shape(g).centroid
        s = SoilGrids(modo=modo).obtener(lat=round(c.y, 5), lon=round(c.x, 5))
        f = fusionar_suelo(s.datos)
        sin_dato = all(v["valor"] is None for v in f.values())
        cur.execute(
            """INSERT INTO parcel_soil(parcel_id,fuente,fecha,ph,incertidumbre,sintetico) VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (parcel_id,fuente,fecha) DO UPDATE SET ph=EXCLUDED.ph,
                 incertidumbre=EXCLUDED.incertidumbre, sintetico=EXCLUDED.sintetico""",
            (pid, "SoilGrids", date.today(), f.get("phh2o", {}).get("valor"), json.dumps(f), sin_dato),
        )
        suelos += 1
    conn.commit()
    return {
        "celdas": len(usadas), "dias": len(serie), "filas_clima": len(filas), "suelos": suelos,
        "origen_clima": {"power": p.origen, "era5": e.origen},
    }
