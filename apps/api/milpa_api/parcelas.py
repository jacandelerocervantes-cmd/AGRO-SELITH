"""Parcelas dibujadas por el productor en el mapa; la superficie se calcula en metros cuadrados en PostGIS."""

from __future__ import annotations

import json
import os
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from shapely.geometry import shape

from .auth import Usuario, get_db, requiere, usuario_actual
from .config import database_url
from .deps import audit, parcela_accesible
from .seguridad import limitar

router = APIRouter(prefix="/mis-parcelas", tags=["parcelas"])
AREA_MIN_M2, AREA_MAX_M2 = 100.0, 5_000_000.0


class ParcelaIn(BaseModel):
    nombre: str = Field(min_length=1, max_length=80)
    geojson: dict[str, Any]  # Polygon o MultiPolygon en WGS84 (lon, lat)

    @field_validator("geojson")
    @classmethod
    def _no_enorme(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v)) > 50_000:  # una parcela dibujada a mano no pasa de unos cientos de vértices
            raise ValueError("El polígono es demasiado grande")
        return v


@router.get("")
def listar(u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id::text AS id, p.nombre, p.area_m2::float AS area_m2, p.area_ha::float AS area_ha, "
        "p.dibujada, ST_AsGeoJSON(p.geom)::json AS geom FROM parcel p JOIN farm f ON f.id=p.farm_id"
    )
    if u.role == "agricultor":
        return db.execute(sql + " WHERE f.owner_id=%s ORDER BY p.created_at", (u.id,)).fetchall()
    return db.execute(sql + " ORDER BY p.created_at").fetchall()


@router.post("", dependencies=[Depends(limitar("parcelas", 30, 3600))])
def crear(body: ParcelaIn, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> dict[str, Any]:
    try:
        g = shape(body.geojson)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, "Geometría inválida") from e
    if g.geom_type not in ("Polygon", "MultiPolygon") or not g.is_valid or g.is_empty:
        raise HTTPException(422, "Dibuje un polígono válido (sin cruzar sus propios lados)")
    finca = db.execute("SELECT id FROM farm WHERE owner_id=%s ORDER BY created_at LIMIT 1", (u.id,)).fetchone() or \
        db.execute("INSERT INTO farm(owner_id,nombre) VALUES (%s,'Mi finca') RETURNING id", (u.id,)).fetchone()
    r = db.execute(
        """WITH g AS (SELECT ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(%s),4326)) AS geom)
           INSERT INTO parcel(farm_id,nombre,geom,area_m2,area_ha,dibujada)
           SELECT %s,%s,geom,ST_Area(geom::geography),ST_Area(geom::geography)/10000,true FROM g
           RETURNING id::text AS id, area_m2::float AS area_m2, area_ha::float AS area_ha""",
        (json.dumps(body.geojson), finca["id"], body.nombre),
    ).fetchone()
    if not AREA_MIN_M2 <= r["area_m2"] <= AREA_MAX_M2:
        db.rollback()
        raise HTTPException(422, f"La parcela debe medir entre {AREA_MIN_M2:.0f} y {AREA_MAX_M2:.0f} m²")
    audit(db, u, "crear_parcela", "parcel", r["id"], {"area_m2": r["area_m2"]})
    db.commit()
    return {**r, "nombre": body.nombre, "geom": body.geojson}


@router.delete("/{parcel_id}")
def borrar(parcel_id: str, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> dict[str, bool]:
    parcela_accesible(db, u, parcel_id)
    db.execute("DELETE FROM parcel WHERE id=%s", (parcel_id,))
    audit(db, u, "borrar_parcela", "parcel", parcel_id, {})
    db.commit()
    return {"ok": True}


@router.post("/{parcel_id}/capas", dependencies=[Depends(limitar("capas", 6, 3600))])
def preparar_capas(parcel_id: str, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> dict[str, Any]:
    """Arma la rejilla de 100 m y carga las capas NASA para las parcelas (modo demo = caché/fixtures)."""
    from milpa_pipelines.cargar_bd import cargar_fusion
    from milpa_pipelines.cargar_capas import cargar_capas
    from milpa_pipelines.gaez import cargar_gaez

    parcela_accesible(db, u, parcel_id)
    # Los cargadores usan filas en tupla; la conexión de la API entrega diccionarios: se abre una propia.
    modo = os.environ.get("MILPA_MODO_DATOS", "demo")  # "auto" en producción: consulta los servicios en vivo
    with psycopg.connect(database_url()) as conn:
        a = cargar_fusion(conn, modo=modo)
        b = cargar_capas(conn, modo=modo)
        g = cargar_gaez(conn, modo=modo)
    return {"fusion": a, "capas": b["capas"], "gaez": g}


@router.get("/{parcel_id}/gaez")
def gaez(parcel_id: str, u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> dict[str, Any]:
    """Idoneidad (0-100) y rendimiento alcanzable (kg de materia seca/ha) de FAO GAEZ, hoy y a 2041-2070."""
    parcela_accesible(db, u, parcel_id)
    filas = db.execute(
        """SELECT cultivo, escenario, indice::float, indice_min::float, indice_max::float,
                  rendimiento_kg_ms_ha::float AS rendimiento, n_modelos, fuente, sintetico
           FROM parcel_gaez WHERE parcel_id=%s ORDER BY cultivo, escenario""", (parcel_id,)).fetchall()
    cultivos: dict[str, dict[str, Any]] = {}
    for f in filas:
        cultivos.setdefault(f["cultivo"], {})[f["escenario"]] = {k: f[k] for k in ("indice", "indice_min", "indice_max", "rendimiento", "n_modelos")}
    return {"cultivos": cultivos, "fuente": filas[0]["fuente"] if filas else None, "sintetico": any(f["sintetico"] for f in filas),
            "nota": "Rejilla de ~9 km: describe la zona, no la parcela. Futuro: insumos altos, promedio de 5 modelos climáticos."}
