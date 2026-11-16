"""Exporta la base de conocimiento y casos de oro del motor Python para el motor TypeScript del cliente.

Uso: uv run python tools/export_engine_data.py          (escribe apps/web/src/engine/*.json)
El test tests/knowledge/test_export_engine.py falla si los archivos quedan desactualizados.
"""

from __future__ import annotations

import json
import sys
from itertools import product
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "packages" / "engine" / "src"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from milpa_api.main import BASE, GRUPOS, Prioridades, pesos_desde  # noqa: E402
from milpa_engine import Motor  # noqa: E402
from milpa_engine.knowledge import LAMBDAS_DEFECTO, PESOS_DEFECTO, cargar, construir_problema  # noqa: E402

DESTINO = ROOT / "apps" / "web" / "src" / "engine"
PRIORIDADES = [(3, 3, 3, 3), (5, 0, 0, 0), (0, 0, 5, 5), (1, 4, 2, 5)]
AREAS = [2.0, 18.0]


def datos() -> dict[str, Any]:
    k = cargar(ROOT / "knowledge")
    return {
        "baseId": BASE,
        "cuotaMax": 0.15,
        "pesosDefecto": PESOS_DEFECTO,
        "lambdas": LAMBDAS_DEFECTO,
        "grupos": {g: list(c) for g, c in GRUPOS.items()},
        "opciones": [
            {
                "id": o.id, "nombre": o.nombre, "familias": sorted(o.familias),
                "hospedantes": sorted(o.hospedantes), "esBarbecho": o.es_barbecho,
                "esBarbechoDesnudo": o.es_barbecho_desnudo, "aguaMm": o.agua_mm,
                "toleranciaSequia": o.tolerancia_sequia, "sensibilidadCanicula": o.sensibilidad_canicula,
                "ingresoMxnHa": o.ingreso_mxn_ha, "nAporteKgHa": o.n_aporte_kg_ha, "moAporte": o.mo_aporte,
                "utilidades": o.utilidades, "capacidadAbsorcionHa": o.capacidad_absorcion_ha,
                "sintetico": o.sintetico,
            }
            for o in k.opciones
        ],
        "reglas": [
            {"id": r.id, "tipo": r.tipo, "selectorA": r.selector_a, "selectorB": r.selector_b,
             "aniosMin": r.anios_min, "severidad": r.severidad}
            for r in k.reglas
        ],
        "escenarios": {
            e.id: {"id": e.id, "severidadCanicula": e.severidad_canicula,
                   "factorDemandaAgua": e.factor_demanda_agua,
                   "factorEstresIngreso": e.factor_estres_ingreso, "toleranciaMinima": e.tolerancia_minima}
            for e in k.escenarios.values()
        },
    }


def casos_de_oro() -> list[dict[str, Any]]:
    k = cargar(ROOT / "knowledge")
    casos = []
    for esc, prio, area in product(sorted(k.escenarios), PRIORIDADES, AREAS):
        p = Prioridades(agua=prio[0], forraje=prio[1], suelo=prio[2], ingreso=prio[3])
        prob = construir_problema(k, esc, 4, BASE, area, pesos_desde(p))
        planes = Motor(prob).recomendar()
        casos.append({
            "escenario": esc, "prioridades": dict(zip(("agua", "forraje", "suelo", "ingreso"), prio, strict=True)),
            "areaHa": area,
            "planes": [
                {"secuencia": list(pl.secuencia), "score": pl.score, "aguaTotalMm": pl.agua_total_mm,
                 "ingresoEstimado": pl.ingreso_estimado, "deltaMo": pl.delta_mo, "deltaN": pl.delta_n,
                 "riesgoPlaga": pl.riesgo_plaga,
                 "factores": {f.factor: f.contribucion for f in pl.factores}}
                for pl in planes
            ],
        })
    return casos


def generar() -> dict[str, str]:
    return {
        "data.json": json.dumps(datos(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        "golden.json": json.dumps(casos_de_oro(), ensure_ascii=False, indent=1, sort_keys=True) + "\n",
    }


if __name__ == "__main__":
    DESTINO.mkdir(parents=True, exist_ok=True)
    for nombre, texto in generar().items():
        (DESTINO / nombre).write_text(texto, encoding="utf-8", newline="\n")
        print("escrito", DESTINO / nombre)
