"""Arnés de backtest contra rendimientos históricos (SIAP)

Calcula MAE y correlación entre rendimiento estimado y observado. NO declara validado nada que se haya
corrido con datos sintéticos o sin modelo de rendimiento.
"""

from __future__ import annotations

import math
from typing import Any


def metricas(predicho: list[float], observado: list[float]) -> dict[str, Any]:
    if len(predicho) != len(observado) or len(predicho) < 2:
        raise ValueError("se necesitan al menos 2 pares predicho/observado")
    n = len(predicho)
    mae = sum(abs(p - o) for p, o in zip(predicho, observado, strict=True)) / n
    mp, mo = sum(predicho) / n, sum(observado) / n
    sp = math.sqrt(sum((p - mp) ** 2 for p in predicho))
    so = math.sqrt(sum((o - mo) ** 2 for o in observado))
    corr = None if sp == 0 or so == 0 else sum((p - mp) * (o - mo) for p, o in zip(predicho, observado, strict=True)) / (sp * so)
    return {"n": n, "mae": mae, "correlacion": corr}


def reporte(predicho: list[float], observado: list[float], *, observado_sintetico: bool, hay_modelo_rendimiento: bool) -> dict[str, Any]:
    m = metricas(predicho, observado)
    motivo = []
    if observado_sintetico:
        motivo.append("rendimientos observados sintéticos")
    if not hay_modelo_rendimiento:
        motivo.append("el motor aún no estima rendimiento")
    return {**m, "validado": not motivo, "motivo_no_validado": motivo}
