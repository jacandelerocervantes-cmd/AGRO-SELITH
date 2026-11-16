"""Las 4 propiedades del motor con hypothesis."""

from __future__ import annotations

from dataclasses import replace

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from milpa_engine import CRITERIOS, PENALIZACIONES, Escenario, Motor, Opcion, Problema, Regla
from milpa_engine.verify import violaciones

FAM = ["f1", "f2", "f3"]
HOST = ["h1", "h2"]
unit = st.floats(0.0, 1.0)


@st.composite
def opciones(draw: st.DrawFn) -> Opcion:
    i = draw(st.integers(0, 10**6))
    return Opcion(
        id=f"o{i}",
        nombre="x",
        familias=frozenset(draw(st.lists(st.sampled_from(FAM), max_size=2))),
        hospedantes=frozenset(draw(st.lists(st.sampled_from(HOST), max_size=1))),
        es_barbecho=False,
        agua_mm=draw(st.floats(100, 600)),
        tolerancia_sequia=draw(st.integers(1, 5)),
        sensibilidad_canicula=draw(unit),
        ingreso_mxn_ha=draw(st.floats(0, 40000)),
        utilidades={k: draw(unit) for k in CRITERIOS},
        capacidad_absorcion_ha=draw(st.one_of(st.none(), st.floats(1, 60))),
    )


@st.composite
def problemas(draw: st.DrawFn) -> Problema:
    ops = draw(st.lists(opciones(), min_size=2, max_size=5, unique_by=lambda o: o.id))
    ops.append(Opcion(id="descanso", nombre="d", es_barbecho=True, tolerancia_sequia=5))
    ids = [o.id for o in ops]
    reglas = tuple(
        Regla(
            f"r{j}",
            "x",
            draw(st.sampled_from(["fam:f1", "fam:f2", "fam:f3", "host:h1"])),
            draw(st.sampled_from(["fam:f1", "fam:f2", "fam:f3", "host:h1"])),
            draw(st.integers(1, 2)),
            draw(st.integers(1, 4)),
        )
        for j in range(draw(st.integers(0, 3)))
    )
    anios = draw(st.integers(2, 4))
    cpy = draw(st.integers(1, 2))
    n = anios * cpy
    return Problema(
        opciones=tuple(ops),
        reglas=reglas,
        escenario=Escenario(
            "e",
            draw(unit),
            draw(st.floats(0.8, 1.2)),
            draw(unit),
            draw(st.integers(1, 3)),
        ),
        horizonte_anios=anios,
        plan_base=tuple(draw(st.sampled_from(ids)) for _ in range(n)),
        pesos={k: draw(st.floats(0, 2)) for k in CRITERIOS},
        lambdas={k: draw(st.floats(0, 2)) for k in PENALIZACIONES},
        ciclos_por_anio=cpy,
        area_ha=draw(st.floats(0.5, 5)),
    )


cfg = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@cfg
@given(problemas())
def test_ningun_plan_viola_restricciones_duras(p: Problema) -> None:
    for plan in Motor(p).recomendar():
        assert violaciones(p, plan.secuencia) == []


@cfg
@given(problemas())
def test_determinismo(p: Problema) -> None:
    assert Motor(p).recomendar() == Motor(p).recomendar()


@cfg
@given(problemas(), st.sampled_from(CRITERIOS), st.floats(0.05, 3.0))
def test_monotonicidad_de_pesos(p: Problema, criterio: str, delta: float) -> None:
    def util_ganador(prob: Problema) -> float | None:
        planes = Motor(prob).recomendar(k=1)
        if not planes:
            return None
        return next(f.valor_norm for f in planes[0].factores if f.factor == criterio)

    antes = util_ganador(p)
    p2 = replace(p, pesos={**p.pesos, criterio: p.pesos[criterio] + delta})
    despues = util_ganador(p2)
    if antes is not None and despues is not None:
        assert despues >= antes - 1e-9


@cfg
@given(problemas())
def test_factores_suman_al_score(p: Problema) -> None:
    m = Motor(p)
    for (suma_dp, _), plan in zip(m._buscar(3), m.recomendar(), strict=True):
        assert abs(sum(f.contribucion for f in plan.factores) - plan.score) < 1e-9
        assert abs(plan.score - suma_dp / m.n) < 1e-9
        assert plan.score_p10 <= plan.score_p50 <= plan.score_p90
