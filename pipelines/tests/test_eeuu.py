"""Validación con datos REALES de EE. UU. (condado de Hidalgo, TX) recalculada desde los fixtures grabados, sin red."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from milpa_pipelines.validacion_eeuu import (
    a_rejilla,
    calcular,
    cargar_fixtures,
    comparar_ndvi,
    resumen_rotacion,
)

REPORTE = Path(__file__).resolve().parents[2] / "docs" / "validacion_eeuu.json"


@pytest.fixture(scope="module")
def res() -> dict:
    return calcular(cargar_fixtures())


def test_ssurgo_real_suelo_franco_arcillo_arenoso(res: dict) -> None:
    s = res["suelo_ssurgo"]
    assert "Hidalgo" in s["unidad_suelo"] and 0 < s["arcilla_pct"] < 60 and 0 < s["arena_pct"] < 100
    assert s["arcilla_pct"] + s["arena_pct"] + s["limo_pct"] == pytest.approx(100, abs=3)


def test_cdl_real_tiene_14_anios_y_rotacion(res: dict) -> None:
    r = res["rotacion_cdl"]
    assert r["anios"] == list(range(2008, 2022)) and r["transiciones_posibles"] == 13
    assert 0 < r["cambios_de_un_anio_al_siguiente"] <= 13


def test_ndvi_de_satelite_correlaciona_con_naip(res: dict) -> None:
    for k in ("ndvi_sentinel2_10m_vs_naip", "ndvi_landsat_30m_vs_naip"):
        assert res[k]["correlacion"] > 0.7 and res[k]["n_pixeles"] >= 20


def test_soilgrids_error_en_textura_es_menor_que_en_materia_organica(res: dict) -> None:
    s = res["soilgrids_vs_ssurgo"]
    assert s["arcilla_pct"]["error_relativo"] < s["materia_organica_pct"]["error_relativo"]


def test_reporte_guardado_coincide_con_el_recalculo(res: dict) -> None:
    g = json.loads(REPORTE.read_text(encoding="utf-8"))
    assert g["ndvi_sentinel2_10m_vs_naip"]["correlacion"] == pytest.approx(res["ndvi_sentinel2_10m_vs_naip"]["correlacion"])


def test_a_rejilla_promedia_por_bloques() -> None:
    o = np.arange(16, dtype=float).reshape(4, 4)
    assert a_rejilla(o, (2, 2)).tolist() == [[2.5, 4.5], [10.5, 12.5]]


def test_comparar_ndvi_exacto_da_error_cero() -> None:
    ref = np.linspace(0, 1, 100 * 100).reshape(100, 100)
    p = a_rejilla(ref, (10, 10))
    m = comparar_ndvi(ref, p)
    assert m["rmse"] == pytest.approx(0, abs=1e-12) and m["correlacion"] == pytest.approx(1)


def test_resumen_rotacion_cuenta_cambios() -> None:
    cdl = {"anios": [{"anio": 2000 + i, "distribucion": {c: 90.0}} for i, c in enumerate("AABA")]}
    r = resumen_rotacion(cdl)
    assert r["cambios_de_un_anio_al_siguiente"] == 2 and r["anios_por_cultivo"] == {"A": 3, "B": 1}


def test_nass_sin_llave_no_inventa_precios(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from milpa_pipelines.base import ConectorNoConfigurado
    from milpa_pipelines.eeuu import NassPrecios

    monkeypatch.delenv("NASS_API_KEY", raising=False)
    with pytest.raises(ConectorNoConfigurado), httpx.Client() as c:
        NassPrecios().fetch(c)
    c2 = NassPrecios()
    assert c2.parsear({"data": [{"year": "2024", "reference_period_desc": "JAN", "Value": "4.35", "unit_desc": "$ / BU"}, {"year": "2024", "reference_period_desc": "FEB", "Value": "(D)", "unit_desc": "$ / BU"}]}) == [
        {"periodo": "2024-JAN", "valor": 4.35, "unidad": "$ / BU"}]
