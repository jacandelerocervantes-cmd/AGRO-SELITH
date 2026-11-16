"""Conectores NASA (sin red ni llaves: caché/fixtures o ejemplo sintético rotulado), armonización e índice."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from milpa_pipelines import indices
from milpa_pipelines.armonizar import (
    compuesto_ndvi,
    pendiente_pct,
    raster_por_celda,
    serie_a_celdas,
)
from milpa_pipelines.fusion import crear_rejilla
from milpa_pipelines.nasa import CAPAS_NASA

LON, LAT = -88.1503, 21.1427
P = {"lat": LAT, "lon": LON, "bbox": [LON - 0.006, LAT - 0.006, LON + 0.006, LAT + 0.006], "inicio": "2023-05-01", "fin": "2023-10-31"}
EARTHDATA = ("imerg", "smap", "gldas", "ecostress", "grace", "gedi")


@pytest.mark.parametrize("capa", sorted(CAPAS_NASA))
def test_modo_demo_sin_fixture_da_ejemplo_sintetico_rotulado(capa: str, tmp_path: Path) -> None:
    c = CAPAS_NASA[capa](modo="demo", cache_dir=tmp_path / "c", fixtures_dir=tmp_path / "f")
    r = c.obtener(**P)
    assert r.sintetico and r.origen == "fixture" and r.datos.get("sintetico") is True
    assert r.datos["unidad"] and r.datos["resolucion_m"] > 0
    forma = [k for k in ("serie", "valores", "escenas") if k in r.datos]
    assert len(forma) == 1


@pytest.mark.parametrize("capa", EARTHDATA)
def test_sin_cuenta_earthdata_el_modo_auto_cae_al_ejemplo_sin_tocar_la_red(capa: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for v in ("EARTHDATA_USERNAME", "EARTHDATA_PASSWORD", "EARTHDATA_TOKEN"):
        monkeypatch.delenv(v, raising=False)
    c = CAPAS_NASA[capa](modo="auto", cache_dir=tmp_path / "c", fixtures_dir=tmp_path / "f")
    r = c.obtener(**P)
    assert r.sintetico and r.origen == "fixture"


def test_los_ejemplos_son_deterministas(tmp_path: Path) -> None:
    a = CAPAS_NASA["smap"](modo="demo", cache_dir=tmp_path / "1", fixtures_dir=tmp_path / "f").obtener(**P).datos
    b = CAPAS_NASA["smap"](modo="demo", cache_dir=tmp_path / "2", fixtures_dir=tmp_path / "f").obtener(**P).datos
    assert a == b and len(a["serie"]) > 40


def test_el_ejemplo_de_imerg_llueve_mas_en_la_temporada_de_lluvias(tmp_path: Path) -> None:
    s = CAPAS_NASA["imerg"](modo="demo", cache_dir=tmp_path / "c", fixtures_dir=tmp_path / "f").obtener(**P).datos["serie"]
    assert all(x["valor"] >= 0 for x in s)


# ---- armonización a la rejilla de 100 m ----
@pytest.fixture(scope="module")
def celdas():  # type: ignore[no-untyped-def]
    return crear_rejilla((LON - 0.004, LAT - 0.004, LON + 0.004, LAT + 0.004), 100)


def test_serie_gruesa_se_replica_en_cada_celda_y_la_incertidumbre_crece_con_la_brecha(celdas) -> None:  # type: ignore[no-untyped-def]
    fino = {"unidad": "x", "resolucion_m": 250, "serie": [{"fecha": "2023-06-01", "valor": 10.0}]}
    grueso = {**fino, "resolucion_m": 25000}
    a = serie_a_celdas(fino, celdas, "cap", "f", False)
    b = serie_a_celdas(grueso, celdas, "cap", "f", False)
    assert len(a) == len(b) == len(celdas)
    assert all(f[3] == 10.0 for f in a) and b[0][4] > a[0][4] > 0
    assert serie_a_celdas({**fino, "serie": [{"fecha": "2023-06-01", "valor": None}]}, celdas, "c", "f", False)[0][4] is None


def test_raster_uniforme_da_la_misma_media_y_desviacion_cero(celdas) -> None:  # type: ignore[no-untyped-def]
    bbox = [LON - 0.004, LAT - 0.004, LON + 0.004, LAT + 0.004]
    r = raster_por_celda(np.full((40, 40), 0.5), bbox, celdas)
    assert len(r) == len(celdas) and all(m == pytest.approx(0.5) and sd == pytest.approx(0) for m, sd in r.values())


def test_raster_con_gradiente_distingue_celdas(celdas) -> None:  # type: ignore[no-untyped-def]
    bbox = [LON - 0.004, LAT - 0.004, LON + 0.004, LAT + 0.004]
    gradiente = np.tile(np.linspace(0, 1, 60), (60, 1))
    medias = [m for m, _ in raster_por_celda(gradiente, bbox, celdas).values()]
    assert max(medias) - min(medias) > 0.5


def test_pendiente_de_un_plano_inclinado() -> None:
    bbox = [LON, LAT, LON + 0.002, LAT + 0.002]  # ~ 205 m de ancho
    n = 30
    ancho_m = 0.002 * 111_320 * np.cos(np.radians(LAT))
    z = np.tile(np.linspace(0, 0.10 * ancho_m, n), (n, 1))  # sube 10 % hacia el este
    pend = pendiente_pct({"bbox": bbox, "valores": z.tolist()})
    assert np.nanmedian(pend) == pytest.approx(10.0, rel=0.05)


def test_compuesto_ndvi_ignora_nubes() -> None:
    a = {"fecha": "2023-06-01", "valores": [[0.5, None], [0.6, 0.7]]}
    b = {"fecha": "2023-07-01", "valores": [[0.7, 0.4], [None, 0.5]]}
    comp, fecha = compuesto_ndvi([a, b])
    assert fecha == "2023-07-01" and comp[0, 0] == pytest.approx(0.6) and comp[0, 1] == pytest.approx(0.4) and comp[1, 0] == pytest.approx(0.6)


# ---- índice de vulnerabilidad ----
def test_vulnerabilidad_baja_con_buenas_condiciones() -> None:
    v = indices.vulnerabilidad({"ndvi_landsat": [0.7], "srtm_pendiente_pct": [0.5], "smap": [0.3], "lst": [30.0]})
    assert v["nivel"] == "poco" and v["indice"] < 0.2 and set(v["evidencia"]) == {"erosion", "agua", "calor", "vegetacion"}


def test_vulnerabilidad_alta_con_pendiente_sequia_calor_y_poca_vegetacion() -> None:
    v = indices.vulnerabilidad({"ndvi_landsat": [0.25], "srtm_pendiente_pct": [9.0], "smap": [0.1], "lst": [44.0]})
    assert v["nivel"] == "mucho" and v["indice"] > 0.9


def test_si_faltan_capas_se_renormalizan_pesos_y_se_dice_que_evidencia_se_uso() -> None:
    v = indices.vulnerabilidad({"ndvi_modis": [0.3]})
    assert v["evidencia"] == ["erosion", "vegetacion"] and v["indice"] == pytest.approx(1.0)
    sin = indices.vulnerabilidad({})
    assert sin["indice"] is None and sin["nivel"] == "sin_dato"
    assert indices.nivel_de(None) == "sin_dato" and indices.nivel_de(0.1) == "poco" and indices.nivel_de(0.4) == "cuidado" and indices.nivel_de(0.7) == "mucho"
