"""Utilidades compartidas por los routers."""

from __future__ import annotations

import json
from typing import Any

import psycopg
from fastapi import HTTPException

from .auth import Usuario


def audit(db: Any, u: Usuario, accion: str, entidad: str, entidad_id: str, detalle: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO audit_log(user_id,accion,entidad,entidad_id,detalle) VALUES (%s,%s,%s,%s,%s)",
        (u.id, accion, entidad, entidad_id, json.dumps(detalle, default=str)),
    )


def parcela_accesible(db: Any, u: Usuario, parcel_id: str) -> dict[str, Any]:
    """Una parcela solo la ve su dueño; los expertos y el admin ven las de todos."""
    try:
        r = db.execute(
            """SELECT p.id, p.nombre, p.area_m2::float AS area_m2, p.area_ha::float AS area_ha, f.owner_id
               FROM parcel p JOIN farm f ON f.id=p.farm_id WHERE p.id=%s""",
            (parcel_id,),
        ).fetchone()
    except psycopg.errors.InvalidTextRepresentation:
        db.rollback()
        r = None
    if r is None or (u.role == "agricultor" and str(r["owner_id"]) != u.id):
        raise HTTPException(404, "Parcela no encontrada")
    return r
