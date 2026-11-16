"""Capas de visualización del mapa (NASA y socios) ya armonizadas a la rejilla de 100 m."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from .auth import Usuario, get_db, usuario_actual
from .deps import parcela_accesible

router = APIRouter(prefix="/capas", tags=["capas"])

# id -> (nombre es, nombre en, dataset, ¿es de la NASA?, color de rampa)
CATALOGO: dict[str, tuple[str, str, str, bool]] = {
    "vulnerabilidad": ("Riesgo de la parcela", "Parcel risk", "Índice derivado de las capas NASA", True),
    "imerg": ("Lluvia (GPM IMERG)", "Rainfall (GPM IMERG)", "NASA GPM IMERG", True),
    "smap": ("Humedad del suelo (SMAP)", "Soil moisture (SMAP)", "NASA SMAP", True),
    "gldas": ("Humedad GLDAS", "GLDAS moisture", "NASA GLDAS", True),
    "gldas_et": ("Evapotranspiración GLDAS", "GLDAS evapotranspiration", "NASA GLDAS", True),
    "ndvi_landsat": ("Salud del cultivo (Landsat)", "Crop health (Landsat)", "NASA/USGS Landsat", True),
    "ndvi_modis": ("Salud del cultivo (MODIS)", "Crop health (MODIS)", "NASA MODIS", True),
    "ndvi_s2": ("Salud del cultivo (Sentinel-2, 10 m)", "Crop health (Sentinel-2, 10 m)", "ESA Copernicus Sentinel-2", False),
    "lst_modis": ("Temperatura de la superficie (MODIS)", "Surface temperature (MODIS)", "NASA MODIS", True),
    "et_modis": ("Evapotranspiración anual (MODIS)", "Annual evapotranspiration (MODIS)", "NASA MODIS", True),
    "lst": ("Temperatura de la superficie (ECOSTRESS)", "Surface temperature (ECOSTRESS)", "NASA ECOSTRESS", True),
    "srtm_elevacion": ("Elevación (SRTM)", "Elevation (SRTM)", "NASA SRTM", True),
    "srtm_pendiente_pct": ("Pendiente y erosión (SRTM)", "Slope and erosion (SRTM)", "NASA SRTM", True),
    "grace": ("Agua almacenada (GRACE-FO)", "Stored water (GRACE-FO)", "NASA GRACE-FO", True),
    "gedi": ("Biomasa (GEDI)", "Biomass (GEDI)", "NASA GEDI", True),
}


@router.get("")
def catalogo(_: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    cargadas = {
        r["capa"]: r
        for r in db.execute(
            """SELECT capa, max(unidad) AS unidad, max(fuente) AS fuente, max(resolucion_nativa_m) AS res,
                      bool_or(sintetico) AS sintetico, count(*) AS n FROM layer_value GROUP BY capa"""
        ).fetchall()
    }
    out = []
    for cid, (es, en, ds, nasa) in CATALOGO.items():
        c = cargadas.get(cid)
        out.append({"id": cid, "nombre": {"es": es, "en": en}, "dataset": ds, "nasa": nasa,
                    "disponible": c is not None, "sintetico": bool(c and c["sintetico"]),
                    "unidad": c["unidad"] if c else None, "fuente": c["fuente"] if c else ds,
                    "resolucion_nativa_m": c["res"] if c else None})
    return out


@router.get("/{capa}")
def valores(capa: str, parcel_id: str | None = None, u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> dict[str, Any]:
    """Celdas de 100 m con el valor medio de la capa (GeoJSON) para pintar en el mapa."""
    if capa not in CATALOGO:
        raise HTTPException(404, "Capa desconocida")
    filtro, args = "", [capa]
    if parcel_id:
        parcela_accesible(db, u, parcel_id)
        filtro, args = " AND c.cell_id IN (SELECT cell_id FROM parcel_cell WHERE parcel_id=%s)", [capa, parcel_id]
    filas = db.execute(
        f"""SELECT c.cell_id, ST_AsGeoJSON(c.geom)::json AS geom, avg(v.valor) AS valor, avg(v.sd) AS sd,
                   max(v.unidad) AS unidad, max(v.fuente) AS fuente, bool_or(v.sintetico) AS sintetico,
                   max(v.resolucion_nativa_m) AS res
            FROM climate_cell c JOIN layer_value v ON v.cell_id=c.cell_id
            WHERE v.capa=%s{filtro} GROUP BY c.cell_id, c.geom ORDER BY c.cell_id""",
        args,
    ).fetchall()
    vals = [f["valor"] for f in filas if f["valor"] is not None]
    return {
        "capa": capa, "min": min(vals) if vals else None, "max": max(vals) if vals else None,
        "unidad": filas[0]["unidad"] if filas else None, "fuente": filas[0]["fuente"] if filas else None,
        "sintetico": any(f["sintetico"] for f in filas), "resolucion_nativa_m": filas[0]["res"] if filas else None,
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": f["geom"],
             "properties": {"cell_id": f["cell_id"], "valor": f["valor"], "sd": f["sd"]}}
            for f in filas
        ],
    }


@router.get("/{capa}/serie")
def serie(capa: str, parcel_id: str, u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> dict[str, Any]:
    """Serie en el tiempo de la capa para una parcela (línea de tiempo y tendencias)."""
    if capa not in CATALOGO:
        raise HTTPException(404, "Capa desconocida")
    parcela_accesible(db, u, parcel_id)
    filas = db.execute(
        """SELECT to_char(v.fecha,'YYYY-MM-DD') AS fecha, avg(v.valor) AS valor, avg(v.sd) AS sd, max(v.unidad) AS unidad,
                  bool_or(v.sintetico) AS sintetico
           FROM layer_value v WHERE v.capa=%s AND v.cell_id IN (SELECT cell_id FROM parcel_cell WHERE parcel_id=%s)
           GROUP BY v.fecha ORDER BY v.fecha""",
        (capa, parcel_id),
    ).fetchall()
    return {"capa": capa, "serie": filas, "sintetico": any(f["sintetico"] for f in filas)}
