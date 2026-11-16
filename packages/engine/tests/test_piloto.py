"""Pruebas con la base de conocimiento real del piloto (valores provisionales)."""

import itertools
from pathlib import Path

import pytest
from milpa_engine import Motor, violaciones
from milpa_engine.knowledge import cargar, construir_problema

RAIZ = Path(__file__).resolve().parents[3] / "knowledge"
K = cargar(RAIZ)


@pytest.mark.parametrize("esc", sorted(K.escenarios))
def test_planes_validos_en_todos_los_escenarios(esc: str) -> None:
    p = construir_problema(K, esc)
    planes = Motor(p).recomendar()
    assert 1 <= len(planes) <= 3
    for pl in planes:
        assert violaciones(p, pl.secuencia) == []
        base = sum(o.agua_mm for o in K.opciones if o.id == "milpa_tradicional") * 4
        assert pl.agua_total_mm <= base * p.escenario.factor_demanda_agua + 1e-6
    scores = [pl.score for pl in planes]
    assert all(a >= b - 1e-9 for a, b in itertools.pairwise(scores))


def test_canicula_cambia_el_plan_sin_subir_agua() -> None:
    normal = Motor(construir_problema(K, "normal")).recomendar(k=1)[0]
    seca = Motor(construir_problema(K, "canicula_prolongada")).recomendar(k=1)[0]
    assert seca.secuencia != normal.secuencia
    assert seca.agua_total_mm <= 500 * 4 + 1e-6  # la práctica actual (milpa) demanda 500 mm/ciclo


def test_mercado_bloquea_cultivo_si_la_parcela_supera_la_cuota() -> None:
    # chile: capacidad 20 ha * 0.15 = 3 ha; con 5 ha no puede aparecer
    p = construir_problema(K, "normal", area_ha=5.0)
    for pl in Motor(p).recomendar():
        assert "chile_habanero" not in pl.secuencia


def test_monte_carlo_exige_200_replicas() -> None:
    with pytest.raises(ValueError):
        Motor(construir_problema(K)).recomendar(replicas=100)
