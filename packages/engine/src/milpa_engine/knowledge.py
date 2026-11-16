"""Carga la base agronómica YAML (knowledge/) hacia los objetos del motor."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from .engine import CRITERIOS, Escenario, Opcion, Problema, Regla

PESOS_DEFECTO = {
    "agua_eficiencia": 1.0,
    "fijacion_n": 1.0,
    "materia_organica": 1.0,
    "control_erosion": 0.5,
    "infiltracion": 0.5,
    "ruptura_plagas": 1.0,
    "valor_forrajero": 0.5,
    "ingreso_neto": 1.0,
    "estabilidad_ingreso": 0.5,
    "proteccion_etapas": 1.5,
}
LAMBDAS_DEFECTO = {
    "barbecho_excesivo": 3.0,
    "concentracion_riesgo": 0.5,
    "dependencia_monocultivo": 0.5,
}


def _yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _v(m: dict[str, Any], k: str) -> Any:
    return m[k]["valor"]


@dataclass(frozen=True)
class Conocimiento:
    opciones: tuple[Opcion, ...]
    reglas: tuple[Regla, ...]
    escenarios: dict[str, Escenario]


def cargar(raiz: Path) -> Conocimiento:
    mercado: dict[str, tuple[float, bool]] = {}
    for f in sorted((raiz / "market").glob("*.yaml")):
        for m in _yaml(f).get("mercado", []):
            mercado[m["opcion_id"]] = (_v(m["parametros"], "capacidad_absorcion_ha"), m["sintetico"])
    opciones: list[Opcion] = []
    for sub in ("crops", "milpa"):
        for f in sorted((raiz / sub).glob("*.yaml")):
            for o in _yaml(f).get("opciones", []):
                p = o["parametros"]
                cap, sint = mercado.get(o["id"], (None, False))
                opciones.append(
                    Opcion(
                        id=o["id"],
                        nombre=o["nombre"],
                        familias=frozenset(o.get("familias", [])),
                        hospedantes=frozenset(o.get("hospedantes", [])),
                        es_barbecho=o["es_barbecho"],
                        es_barbecho_desnudo=o["es_barbecho_desnudo"],
                        agua_mm=float(_v(p, "agua_mm_ciclo")),
                        tolerancia_sequia=int(_v(p, "tolerancia_sequia")),
                        sensibilidad_canicula=float(_v(p, "sensibilidad_canicula")),
                        ingreso_mxn_ha=float(_v(p, "ingreso_ref_mxn_ha")),
                        n_aporte_kg_ha=float(_v(p, "n_aporte_kg_ha")),
                        mo_aporte=float(_v(p, "mo_aporte")),
                        utilidades={k: float(v["valor"]) for k, v in o["utilidades"].items()},
                        capacidad_absorcion_ha=cap,
                        sintetico=sint,
                    )
                )
    reglas = tuple(
        Regla(r["id"], r["tipo"], r["selector_a"], r["selector_b"], int(r["anios_min"]), int(r["severidad"]))
        for f in sorted((raiz / "rules").glob("*.yaml"))
        for r in _yaml(f).get("rules", [])
    )
    escenarios: dict[str, Escenario] = {}
    for f in sorted((raiz / "scenarios").glob("*.yaml")):
        for e in _yaml(f).get("escenarios", []):
            p = e["parametros"]
            escenarios[e["id"]] = Escenario(
                e["id"],
                float(_v(p, "severidad_canicula")),
                float(_v(p, "factor_demanda_agua")),
                float(_v(p, "factor_estres_ingreso")),
                int(_v(p, "tolerancia_minima")),
            )
    return Conocimiento(tuple(opciones), reglas, escenarios)


def construir_problema(
    k: Conocimiento,
    escenario: str = "normal",
    horizonte_anios: int = 4,
    base: str = "milpa_tradicional",
    area_ha: float = 2.0,
    pesos: dict[str, float] | None = None,
    ciclos_por_anio: int = 1,
) -> Problema:
    n = horizonte_anios * ciclos_por_anio
    return Problema(
        opciones=k.opciones,
        reglas=k.reglas,
        escenario=k.escenarios[escenario],
        horizonte_anios=horizonte_anios,
        plan_base=(base,) * n,
        pesos=pesos or dict(PESOS_DEFECTO),
        lambdas=dict(LAMBDAS_DEFECTO),
        ciclos_por_anio=ciclos_por_anio,
        area_ha=area_ha,
    )


__all__ = ["CRITERIOS", "Conocimiento", "cargar", "construir_problema", "replace"]
