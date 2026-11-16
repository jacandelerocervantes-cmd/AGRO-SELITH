"""Comparación mínima de tres estrategias (rotación actual + 2) y su explicación (reto Field Shift)."""

from pathlib import Path

import pytest
from milpa_engine import Motor, violaciones
from milpa_engine.explicacion import explicar
from milpa_engine.knowledge import cargar, construir_problema

K = cargar(Path(__file__).resolve().parents[3] / "knowledge")
CAPAS_OK = {"imerg": {"disponible": True, "sintetico": False, "fuente": "NASA GPM IMERG"},
            "smap": {"disponible": True, "sintetico": True, "fuente": "NASA SMAP"},
            "gedi": {"disponible": False, "sintetico": False, "fuente": ""}}


def _comparar(esc: str = "normal", area: float = 1.24):
    prob = construir_problema(K, esc, 4, "milpa_tradicional", area)
    return prob, Motor(prob).comparar()


@pytest.mark.parametrize("esc", sorted(K.escenarios))
def test_siempre_hay_tres_estrategias_y_la_primera_es_la_actual(esc: str) -> None:
    prob, planes = _comparar(esc)
    assert [p.ranking for p in planes] == [0, 1, 2]
    assert planes[0].secuencia == prob.plan_base
    assert planes[1].secuencia != planes[0].secuencia and planes[2].secuencia != planes[0].secuencia
    assert planes[1].secuencia != planes[2].secuencia
    for p in planes[1:]:
        assert violaciones(prob, p.secuencia) == []  # las alternativas respetan las restricciones duras


def test_la_actual_se_evalua_con_el_mismo_puntaje() -> None:
    prob, planes = _comparar()
    m = Motor(prob)
    assert m.evaluar_ids(prob.plan_base, ranking=0).score == pytest.approx(planes[0].score)
    assert abs(sum(f.contribucion for f in planes[0].factores) - planes[0].score) < 1e-9


def test_evaluar_ids_rechaza_secuencias_invalidas() -> None:
    prob, _ = _comparar()
    with pytest.raises(ValueError):
        Motor(prob).evaluar_ids(("milpa_tradicional",))
    with pytest.raises(ValueError):
        Motor(prob).evaluar_ids(("no_existe",) * 4)


def test_la_mejor_alternativa_no_puntua_menos_que_la_actual_si_cumple_restricciones() -> None:
    _, planes = _comparar()
    assert planes[1].score >= planes[0].score - 1e-9


@pytest.mark.parametrize("idioma", ["es", "en"])
def test_explicacion_completa_y_bilingue(idioma: str) -> None:
    _, planes = _comparar("canicula_prolongada")
    ctx = {"capas": CAPAS_OK, "estatus_parametros": "provisional", "suelo_sin_medicion": True, "hay_estaciones": False}
    base = planes[0]
    for p in planes:
        e = explicar(p, base, ctx, idioma)
        assert all(e[k] for k in ("por_que", "beneficios", "evidencia", "vacios", "riesgos"))
    alt = explicar(planes[1], base, ctx, idioma)
    assert any("IMERG" in x for x in alt["evidencia"])               # capa real = evidencia
    assert any("SMAP" in x for x in alt["vacios"])                    # capa de ejemplo = vacío
    assert any("GEDI" in x for x in alt["vacios"])                    # capa no disponible = vacío
    assert len(alt["vacios"]) >= 4 and len(alt["riesgos"]) >= 2


def test_los_idiomas_difieren_y_la_actual_se_describe_como_punto_de_comparacion() -> None:
    _, planes = _comparar()
    ctx = {"capas": {}, "estatus_parametros": "provisional"}
    es, en = explicar(planes[0], planes[0], ctx, "es"), explicar(planes[0], planes[0], ctx, "en")
    assert es["por_que"] != en["por_que"] and "hoy" in es["por_que"] and "today" in en["por_que"]
    assert explicar(planes[0], planes[0], ctx, "fr")["por_que"] == es["por_que"]  # idioma desconocido -> español


def test_no_inventa_cifras_los_numeros_salen_del_plan() -> None:
    _, planes = _comparar()
    ctx = {"capas": {}, "estatus_parametros": "provisional"}
    e = explicar(planes[1], planes[0], ctx, "es")
    ahorro = planes[0].agua_total_mm - planes[1].agua_total_mm
    if ahorro > 1:
        assert f"{ahorro:.0f} mm" in " ".join(e["beneficios"])
    assert f"{planes[1].ingreso_estimado:,.0f}" in " ".join(e["beneficios"])


def test_gaez_aparece_como_evidencia_y_riesgo_con_cifras_reales_del_contexto() -> None:
    _, planes = _comparar()
    gaez = {"Maize": {"hist_bajo": {"indice": 16.7, "rend": 610.0}, "hist_alto": {"indice": 33.2, "rend": 2458.0},
                      "fut45": {"indice": 20.0, "rend": 1765.6}, "fut85": {"indice": 16.6, "rend": 1417.0}}}
    ctx = {"capas": {}, "estatus_parametros": "provisional", "gaez": gaez}
    e = explicar(planes[0], planes[0], ctx, "es")  # la rotación actual es milpa (maíz)
    linea = next(x for x in e["evidencia"] if "GAEZ" in x)
    assert "17/100" in linea and "610" in linea and "2458" in linea and "1766" in linea and "1417" in linea
    assert any("idoneidad baja" in r for r in e["riesgos"]) and any("42 %" in r for r in e["riesgos"])  # 1417/2458 = -42 %
    en = explicar(planes[0], planes[0], ctx, "en")
    assert any("FAO GAEZ" in x and "maize" in x for x in en["evidencia"]) and any("low suitability" in r for r in en["riesgos"])
    sin = explicar(planes[0], planes[0], {"capas": {}, "estatus_parametros": "provisional"}, "es")
    assert not any("GAEZ" in x for x in sin["evidencia"])  # sin datos GAEZ no se inventa nada
