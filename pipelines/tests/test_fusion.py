"""Pruebas de la fusión con datos conocidos y con las respuestas reales grabadas."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest
from milpa_pipelines import backtest, fusion
from milpa_pipelines.base import FIXTURES
from milpa_pipelines.conectores import NasaPower, OpenMeteoERA5, StacSentinel

LON, LAT = -88.1503, 21.1427


def _cargar(nombre: str):  # type: ignore[no-untyped-def]
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


# ---- rejilla y pesos ----
def test_rejilla_de_100_m_tiene_celdas_de_100_m() -> None:
    celdas = fusion.crear_rejilla((LON, LAT, LON + 0.01, LAT + 0.01), 100)
    assert 100 <= len(celdas) <= 150
    for c in celdas[:20]:
        area = fusion.transform(fusion._A_UTM, c.geom).area
        assert area == pytest.approx(10_000, rel=1e-3)


def test_pesos_de_parcela_suman_uno_y_son_proporcionales() -> None:
    celdas = fusion.crear_rejilla((LON - 0.002, LAT - 0.002, LON + 0.012, LAT + 0.012), 100)
    parcela = {"type": "MultiPolygon", "coordinates": [[[[LON, LAT], [LON + 0.004, LAT], [LON + 0.004, LAT + 0.004], [LON, LAT + 0.004], [LON, LAT]]]]}
    w = fusion.pesos_parcela_celda(parcela, celdas)
    assert sum(w.values()) == pytest.approx(1.0)
    assert len(w) >= 16 and all(0 < v <= 1 for v in w.values())


def test_pesos_fallan_si_la_rejilla_no_cubre() -> None:
    celdas = fusion.crear_rejilla((LON, LAT, LON + 0.001, LAT + 0.001), 100)
    lejos = {"type": "Polygon", "coordinates": [[[LON + 1, LAT], [LON + 1.001, LAT], [LON + 1.001, LAT + 0.001], [LON + 1, LAT]]]}
    with pytest.raises(ValueError):
        fusion.pesos_parcela_celda(lejos, celdas)


# ---- quantile mapping con datos conocidos ----
def test_quantile_mapping_lleva_el_modelo_a_la_referencia() -> None:
    rng = np.random.default_rng(1)
    ref = rng.gamma(2.0, 4.0, 5000)
    modelo = ref * 0.6 + 3.0 + rng.normal(0, 0.2, 5000)  # sesgo conocido
    f = fusion.quantile_mapping(modelo, ref)
    for q in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert np.quantile(f(modelo), q) == pytest.approx(np.quantile(ref, q), rel=0.03)
    assert abs(np.mean(f(modelo)) - np.mean(ref)) < abs(np.mean(modelo) - np.mean(ref))


# ---- clima real fusionado ----
@pytest.fixture(scope="module")
def serie() -> list[dict]:
    p = NasaPower(modo="demo").parsear(_cargar("nasa_power"))
    e = OpenMeteoERA5(modo="demo").parsear(_cargar("open_meteo_era5"))
    return fusion.fusionar_clima(p, e)


def test_fusion_real_184_dias_con_incertidumbre(serie: list[dict]) -> None:
    assert len(serie) == 184
    pisos = fusion.parametros()["pisos_clima"]
    for r in serie:
        assert r["precip_mm"] >= 0 and r["precip_mm_sd"] >= pisos["precip_mm"]
        assert r["tmax_sd"] >= pisos["temp_c"] and r["tmax"] > r["tmin"]
        assert r["et0_mm_sd"] >= pisos["et0_mm"]  # ET0 solo viene de ERA5: queda el piso


def test_la_incertidumbre_crece_si_las_fuentes_discrepan() -> None:
    a = [{"fecha": "2023-06-01", "precip_mm": 0.0, "tmax": 30.0, "tmin": 20.0, "rad_mj": 20.0, "et0_mm": None}]
    b = [{"fecha": "2023-06-01", "precip_mm": 10.0, "tmax": 31.0, "tmin": 20.0, "rad_mj": 20.0, "et0_mm": 5.0}]
    r = fusion.fusionar_clima(a, b)[0]
    assert r["precip_mm"] == pytest.approx(5.0) and r["precip_mm_sd"] == pytest.approx(5.0)
    assert r["tmax_sd"] == pytest.approx(0.5)  # discrepancia 0.5 °C = piso


def test_con_estaciones_se_aplica_quantile_mapping() -> None:
    rng = np.random.default_rng(3)
    fechas = [f"2023-{1 + i // 28:02d}-{1 + i % 28:02d}" for i in range(200)]
    real = rng.gamma(2, 3, 200)
    est = [{"fecha": f, "precip_mm": float(v), "tmax": 30.0, "tmin": 20.0, "rad_mj": 20.0} for f, v in zip(fechas, real, strict=True)]
    sesgada = [{"fecha": f, "precip_mm": float(v * 0.5), "tmax": 30.0, "tmin": 20.0, "rad_mj": 20.0, "et0_mm": 4.0} for f, v in zip(fechas, real, strict=True)]
    sin = fusion.fusionar_clima(sesgada, sesgada)
    con = fusion.fusionar_clima(sesgada, sesgada, estaciones=est)
    err = lambda s: abs(np.mean([r["precip_mm"] for r in s]) - real.mean())  # noqa: E731
    assert err(con) < err(sin) * 0.2


def test_racha_seca_en_ventana_de_canicula(serie: list[dict]) -> None:
    r = fusion.racha_seca_max(serie)
    assert 0 <= r <= 62  # julio-agosto = 62 días como máximo
    sintetica = [{"fecha": f"2023-07-{d:02d}", "precip_mm": 0.0 if d != 10 else 20.0} for d in range(1, 31)]
    assert fusion.racha_seca_max(sintetica) == 20  # del 11 al 30
    fuera = [{"fecha": f"2023-05-{d:02d}", "precip_mm": 0.0} for d in range(1, 31)]
    assert fusion.racha_seca_max(fuera) == 0


# ---- suelo ----
def test_suelo_sin_dato_no_inventa_valores() -> None:
    s = fusion.fusionar_suelo({"phh2o": None, "clay": None, "baja_confianza_karst": True})
    assert s["phh2o"]["valor"] is None and s["phh2o"]["confianza"] == "sin dato"


def test_suelo_soilgrids_tiene_incertidumbre_alta_y_inegi_la_reduce() -> None:
    solo = fusion.fusionar_suelo({"phh2o": 7.0})["phh2o"]
    assert solo["sd"] == pytest.approx(3.5) and solo["confianza"] == "baja"
    mezcla = fusion.fusionar_suelo({"phh2o": 7.0}, inegi={"phh2o": (7.6, 0.3)})["phh2o"]
    assert mezcla["sd"] < 0.3 and 7.5 < mezcla["valor"] < 7.6 and mezcla["fuente"] == "SoilGrids+INEGI"
    assert math.isclose(mezcla["sd"], math.sqrt(1 / (1 / 3.5**2 + 1 / 0.3**2)))


# ---- vegetación (metadatos STAC reales) ----
def test_disponibilidad_optica_con_escenas_reales() -> None:
    esc = StacSentinel(modo="demo").parsear(_cargar("stac_planetary"))
    d = fusion.disponibilidad_optica(esc)
    assert d and sum(m["escenas"] for m in d) == len(esc)
    assert all(0 <= m["fraccion_util"] <= 1 and m["utiles"] <= m["escenas"] for m in d)
    assert all(m["requiere_sar"] == (m["fraccion_util"] < 0.5) for m in d)


def test_disponibilidad_marca_sar_si_todo_esta_nublado() -> None:
    d = fusion.disponibilidad_optica([{"fecha": "2023-07-01", "nubosidad_pct": 90}, {"fecha": "2023-07-06", "nubosidad_pct": 60}])
    assert d[0]["utiles"] == 0 and d[0]["requiere_sar"]


# ---- backtest (arnés) ----
def test_metricas_con_valores_conocidos() -> None:
    m = backtest.metricas([1, 2, 3, 4], [2, 3, 4, 5])
    assert m["mae"] == 1.0 and m["correlacion"] == pytest.approx(1.0)
    assert backtest.metricas([1, 1, 1], [1, 2, 3])["correlacion"] is None


def test_reporte_no_declara_validado_con_datos_sinteticos() -> None:
    r = backtest.reporte([1, 2, 3], [1, 2, 4], observado_sintetico=True, hay_modelo_rendimiento=False)
    assert r["validado"] is False and len(r["motivo_no_validado"]) == 2
    ok = backtest.reporte([1, 2, 3], [1, 2, 4], observado_sintetico=False, hay_modelo_rendimiento=True)
    assert ok["validado"] is True
