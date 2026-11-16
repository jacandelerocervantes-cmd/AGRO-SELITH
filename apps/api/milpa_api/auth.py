"""Autenticación por rol. Demo: cabecera X-Demo-Login (usuarios de prueba, sin correo ni contraseña).
Producción: verificación de token Firebase con custom claims (pendiente)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg
from fastapi import Depends, Header, HTTPException
from psycopg.rows import dict_row

from .config import database_url, modo_demo


def get_db():  # type: ignore[no-untyped-def]
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        yield conn


@dataclass(frozen=True)
class Usuario:
    id: str
    role: str
    nombre: str
    areas: tuple[str, ...] = ()


def usuario_actual(
    x_demo_login: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
    db: Any = Depends(get_db),
) -> Usuario:
    if authorization:
        raise HTTPException(501, "Autenticación Firebase aún no implementada")
    if not modo_demo():
        raise HTTPException(401, "Modo demo desactivado")
    if not x_demo_login:
        raise HTTPException(401, "Falta la cabecera X-Demo-Login")
    r = db.execute(
        "SELECT id, role, nombre, areas FROM user_account WHERE demo_login=%s AND es_demo", (x_demo_login,)
    ).fetchone()
    if r is None:
        raise HTTPException(401, "Usuario de prueba desconocido")
    return Usuario(str(r["id"]), r["role"], r["nombre"], tuple(r["areas"] or ()))


def requiere(*roles: str) -> Callable[[Usuario], Usuario]:
    def dep(u: Usuario = Depends(usuario_actual)) -> Usuario:
        if u.role not in roles:
            raise HTTPException(403, f"El rol '{u.role}' no puede hacer esto")
        return u

    return dep
