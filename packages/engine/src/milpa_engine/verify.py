"""Verificador independiente de restricciones duras (implementación distinta a la del motor)."""

from __future__ import annotations

from .engine import Problema, coincide


def violaciones(p: Problema, secuencia: tuple[str, ...]) -> list[str]:
    por_id = {o.id: o for o in p.opciones}
    cpy, esc = p.ciclos_por_anio, p.escenario
    out: list[str] = []
    if len(secuencia) != p.n_slots:
        return ["longitud incorrecta"]
    ops = [por_id[s] for s in secuencia]
    base = [por_id[s] for s in p.plan_base]
    # Agua: por slot, por año y total
    ag = [o.agua_mm * esc.factor_demanda_agua for o in ops]
    ab = [o.agua_mm * esc.factor_demanda_agua for o in base]
    for t, (a, b) in enumerate(zip(ag, ab, strict=True)):
        if a > b + 1e-6:
            out.append(f"agua slot {t}: {a} > {b}")
    for y in range(p.horizonte_anios):
        if sum(ag[y * cpy : (y + 1) * cpy]) > sum(ab[y * cpy : (y + 1) * cpy]) + 1e-6:
            out.append(f"agua año {y}")
    if sum(ag) > sum(ab) + 1e-6:
        out.append("agua total")
    # Fitosanidad (solo reglas duras)
    for j in range(len(ops)):
        for i in range(j):
            for r in p.reglas:
                if (
                    r.dura
                    and 0 < j - i <= r.anios_min * cpy
                    and coincide(r.selector_a, ops[i])
                    and coincide(r.selector_b, ops[j])
                ):
                    out.append(f"regla {r.id} entre slots {i} y {j}")
    # Mercado y tolerancia a sequía
    for t, o in enumerate(ops):
        if o.capacidad_absorcion_ha is not None and (
            p.area_ha > o.capacidad_absorcion_ha * p.cuota_max + 1e-6
        ):
            out.append(f"mercado {o.id}")
        if not o.es_barbecho and o.tolerancia_sequia < esc.tolerancia_minima:
            out.append(f"tolerancia a sequía {o.id} en slot {t}")
    return out
