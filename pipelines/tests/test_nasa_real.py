"""Respuestas REALES grabadas de Landsat, MODIS y SRTM/NASADEM (Planetary Computer, Tizimín) procesadas por el pipeline."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
from milpa_pipelines import indices
from milpa_pipelines.armonizar import compuesto_ndvi, pendiente_pct, raster_por_celda
from milpa_pipelines.base import FIXTURES
from milpa_pipelines.fusion import crear_rejilla
from milpa_pipelines.nasa import LandsatNdvi, ModisNdvi, SrtmRelieve

LON, LAT = -88.1503, 21.1427


def _f(nombre: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


def test_landsat_real_tiene_escenas_con_ndvi_plausible() -> None:
    d = _f("landsat_ndvi")
    assert d["resolucion_m"] == 30 and len(d["escenas"]) >= 10
    fechas = [e["fecha"] for e in d["escenas"]]
    assert fechas == sorted(fechas) and fechas[0] >= "2023-05-01" and fechas[-1] <= "2023-10-31"
    vals = np.array([v for e in d["escenas"] for fila in e["valores"] for v in fila if v is not None])
    assert vals.size > 1000 and vals.min() >= -1 and vals.max() <= 1
    assert 0.2 < np.median(vals) < 0.95  # vegetación verde en temporada de lluvias


def test_modo_demo_usa_los_fixtures_reales_y_no_los_marca_como_ejemplo(tmp_path) -> None:  # type: ignore[no-untyped-def]
    for cls in (LandsatNdvi, ModisNdvi, SrtmRelieve):
        r = cls(modo="demo", cache_dir=tmp_path).obtener(lat=LAT, lon=LON, bbox=[LON - 0.006, LAT - 0.006, LON + 0.006, LAT + 0.006], inicio="2023-05-01", fin="2023-10-31")
        assert r.origen == "fixture" and r.sintetico is False and not r.datos.get("sintetico")


def test_modis_real_serie_de_16_dias() -> None:
    d = _f("modis_ndvi")
    s = [x for x in d["serie"] if x["valor"] is not None]
    assert d["resolucion_m"] == 250 and len(s) >= 10
    assert all(-0.2 <= x["valor"] <= 1 for x in s)
    assert max(x["valor"] for x in s) > min(x["valor"] for x in s)  # hay estacionalidad


def test_srtm_real_es_llano_como_la_peninsula() -> None:
    d = _f("srtm_relieve")
    z = np.array([[np.nan if v is None else v for v in fila] for fila in d["valores"]])
    assert z.size > 400 and np.nanmin(z) >= 0 and np.nanmax(z) < 150  # Yucatán: decenas de metros
    pend = pendiente_pct(d)
    assert np.nanmedian(pend) < 6  # pendiente baja: el riesgo de erosión viene más del suelo desnudo que del relieve


def test_compuesto_y_agregacion_por_celda_con_datos_reales() -> None:
    d = _f("landsat_ndvi")
    comp, fecha = compuesto_ndvi(d["escenas"])
    assert fecha == d["escenas"][-1]["fecha"] and np.isfinite(comp).mean() > 0.9
    celdas = crear_rejilla(tuple(d["escenas"][0]["bbox"]), 100)  # type: ignore[arg-type]
    por_celda = raster_por_celda(comp, d["escenas"][0]["bbox"], celdas)
    assert len(por_celda) == len(celdas)
    medias = [m for m, _ in por_celda.values()]
    assert 0.2 < np.mean(medias) < 0.95 and max(medias) > min(medias)  # sí hay variación entre celdas


def test_indice_de_vulnerabilidad_con_solo_datos_reales_de_landsat_y_srtm() -> None:
    d, dem = _f("landsat_ndvi"), _f("srtm_relieve")
    comp, _ = compuesto_ndvi(d["escenas"])
    v = indices.vulnerabilidad({"ndvi_landsat": [float(np.nanmean(comp))], "srtm_pendiente_pct": [float(np.nanmedian(pendiente_pct(dem)))]})
    assert v["evidencia"] == ["erosion", "vegetacion"] and 0 <= v["indice"] <= 1
    assert v["nivel"] in ("poco", "cuidado", "mucho")
    assert v["componentes"]["agua"] is None and v["componentes"]["calor"] is None  # sin SMAP/ECOSTRESS no se inventan


@pytest.mark.parametrize("nombre", ["landsat_ndvi", "modis_ndvi", "srtm_relieve"])
def test_los_fixtures_no_traen_la_marca_de_sinteticos(nombre: str) -> None:
    assert "sintetico" not in _f(nombre)


def test_sentinel2_real_de_10_m_con_ndvi_valido() -> None:
    d = _f("sentinel2_ndvi")
    assert d["resolucion_m"] == 10 and len(d["escenas"]) >= 10
    vals = np.array([v for e in d["escenas"] for fila in e["valores"] for v in fila if v is not None])
    assert vals.size > 10_000 and vals.min() >= -1 and vals.max() <= 1 and -0.1 < np.median(vals) < 0.9
    assert len(d["escenas"][0]["valores"]) > len(_f("landsat_ndvi")["escenas"][0]["valores"])  # más píxeles = más detalle


def test_modis_lst_real_temperaturas_de_yucatan() -> None:
    s = [x["valor"] for x in _f("modis_lst")["serie"] if x["valor"] is not None]
    assert len(s) >= 20 and all(15 < v < 55 for v in s) and max(s) - min(s) > 4  # varía con la estación


def test_modis_et_real_anual_en_mm() -> None:
    d = _f("modis_et")
    s = [x["valor"] for x in d["serie"] if x["valor"] is not None]
    assert d["unidad"] == "mm/año" and len(s) >= 3 and all(200 < v < 2500 for v in s)


def test_el_indice_prefiere_sentinel2_y_acepta_lst_de_modis() -> None:
    con_s2 = indices.vulnerabilidad({"ndvi_s2": [0.7], "ndvi_landsat": [0.3], "lst_modis": [30.0]})
    solo_landsat = indices.vulnerabilidad({"ndvi_landsat": [0.3], "lst_modis": [30.0]})
    assert con_s2["componentes"]["vegetacion"] < solo_landsat["componentes"]["vegetacion"]  # usó el NDVI de 10 m
    assert con_s2["componentes"]["calor"] == 0.0 and "calor" in con_s2["evidencia"]  # LST de MODIS cuenta como evidencia


def test_gaez_real_de_tizimin_tiene_los_cuatro_escenarios_para_cada_cultivo() -> None:
    from milpa_pipelines.gaez import Gaez

    d = Gaez().parsear(_f("gaez"))
    assert {"Maize", "Phaseolus bean", "Cowpea", "Sweet potato", "Cassava"} <= set(d)
    for crop, esc in d.items():
        assert set(esc) == {"hist_bajo", "hist_alto", "fut45", "fut85"}, crop
        assert all(0 <= v["indice"] <= 100 and v["rendimiento_kg_ms_ha"] >= 0 for v in esc.values())
        assert esc["fut45"]["n_modelos"] == 5 and esc["fut45"]["indice_min"] <= esc["fut45"]["indice"] <= esc["fut45"]["indice_max"]
    maiz = d["Maize"]
    assert maiz["hist_alto"]["rendimiento_kg_ms_ha"] > maiz["hist_bajo"]["rendimiento_kg_ms_ha"]  # más insumos, más rendimiento
    assert maiz["fut85"]["rendimiento_kg_ms_ha"] < maiz["hist_alto"]["rendimiento_kg_ms_ha"]  # el clima futuro lo reduce
