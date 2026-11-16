"""Pruebas de conectores con respuestas REALES grabadas (cassettes en pipelines/fixtures)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from milpa_pipelines import conectores as c
from milpa_pipelines.base import FIXTURES

LAT, LON = 21.1427, -88.1503
CASOS: list[tuple[type, dict[str, Any]]] = [
    (c.NasaPower, {"lat": LAT, "lon": LON, "inicio": "2023-05-01", "fin": "2023-10-31"}),
    (c.OpenMeteoERA5, {"lat": LAT, "lon": LON, "inicio": "2023-05-01", "fin": "2023-10-31"}),
    (c.StacSentinel, {"bbox": [-88.19, 21.10, -88.11, 21.18], "inicio": "2023-06-01", "fin": "2023-08-31"}),
]


def _cassette(nombre: str) -> Any:
    return json.loads((FIXTURES / f"{nombre}.json").read_text(encoding="utf-8"))


def _cliente(respuesta: Any) -> httpx.Client:
    def h(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=respuesta) if not isinstance(respuesta, str) else httpx.Response(200, text=respuesta)

    return httpx.Client(transport=httpx.MockTransport(h))


def _caido() -> httpx.Client:
    def h(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("sin red")

    return httpx.Client(transport=httpx.MockTransport(h))


@pytest.mark.parametrize(("cls", "p"), CASOS)
def test_fetch_vivo_parsea_y_guarda_cache(cls: type, p: dict[str, Any], tmp_path: Path) -> None:
    con = cls(cache_dir=tmp_path, client=_cliente(_cassette(cls.nombre)), espera_s=0)
    r = con.obtener(**p)
    assert r.origen == "vivo" and not r.sintetico and len(r.datos) > 10
    # mismo parámetro en modo demo: sale de la caché, sin red
    demo = cls(modo="demo", cache_dir=tmp_path, client=_caido())
    assert demo.obtener(**p).origen == "cache"


@pytest.mark.parametrize(("cls", "p"), CASOS)
def test_red_caida_usa_fixture_real(cls: type, p: dict[str, Any], tmp_path: Path) -> None:
    r = cls(cache_dir=tmp_path, client=_caido(), espera_s=0).obtener(**p)
    assert r.origen == "fixture" and not r.sintetico and len(r.datos) > 10


@pytest.mark.parametrize(("cls", "p"), CASOS)
def test_modo_demo_nunca_toca_la_red(cls: type, p: dict[str, Any], tmp_path: Path) -> None:
    def prohibido(req: httpx.Request) -> httpx.Response:
        raise AssertionError("modo demo hizo una petición")

    cli = httpx.Client(transport=httpx.MockTransport(prohibido))
    assert cls(modo="demo", cache_dir=tmp_path, client=cli).obtener(**p).origen == "fixture"


def test_reintenta_una_vez_antes_de_caer(tmp_path: Path) -> None:
    llamadas = []

    def h(req: httpx.Request) -> httpx.Response:
        llamadas.append(1)
        return httpx.Response(503) if len(llamadas) == 1 else httpx.Response(200, json=_cassette("nasa_power"))

    con = c.NasaPower(cache_dir=tmp_path, client=httpx.Client(transport=httpx.MockTransport(h)), espera_s=0)
    assert con.obtener(**CASOS[0][1]).origen == "vivo" and len(llamadas) == 2


def test_power_trata_999_como_dato_faltante(tmp_path: Path) -> None:
    crudo = {"properties": {"parameter": {k: {"20230501": -999.0} for k in
             ("PRECTOTCORR", "T2M_MAX", "T2M_MIN", "ALLSKY_SFC_SW_DWN")}}}
    fila = c.NasaPower(cache_dir=tmp_path).parsear(crudo)[0]
    assert fila["precip_mm"] is None and fila["fecha"] == "2023-05-01"


def test_datos_reales_son_plausibles_para_yucatan() -> None:
    filas = c.OpenMeteoERA5().parsear(_cassette("open_meteo_era5"))
    assert len(filas) == 184  # mayo-octubre 2023
    assert all(15 < f["tmin"] < 40 and 20 < f["tmax"] < 50 for f in filas if f["tmax"] is not None)
    assert sum(f["precip_mm"] or 0 for f in filas) > 100  # hay temporada de lluvias


def test_soilgrids_cae_a_sintetico_sin_valores_inventados(tmp_path: Path) -> None:
    con = c.SoilGrids(cache_dir=tmp_path, fixtures_dir=tmp_path, client=_caido(), espera_s=0)
    r = con.obtener(lat=LAT, lon=LON)
    assert r.sintetico and r.origen == "fixture"
    assert r.datos["phh2o"] is None and r.datos["baja_confianza_karst"] is True


def test_soilgrids_parsea_respuesta_real_y_escala(tmp_path: Path) -> None:
    crudo = {"properties": {"layers": [
        {"name": "phh2o", "unit_measure": {"d_factor": 10}, "depths": [{"values": {"mean": 71}}]}]}}
    assert c.SoilGrids(cache_dir=tmp_path).parsear(crudo)["phh2o"] == 7.1


@pytest.mark.parametrize("cls", [c.Siap, c.Sniim, c.MonitorSequia])
def test_csv_sin_url_usa_fallback_sintetico_etiquetado(cls: type, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(cls.env, raising=False)
    r = cls(cache_dir=tmp_path, client=_caido(), espera_s=0).obtener()
    assert r.sintetico and r.origen == "fixture" and len(r.datos) > 0


def test_siap_con_url_configurada_parsea_y_filtra(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIAP_CSV_URL", "https://ejemplo.invalid/siap.csv")
    csv_ = "Anio,Nommunicipio,Nomcultivo,Rendimiento\n2022,Tizimín,Maíz grano,0.9\n2022,Mérida,Maíz grano,1.1\n"
    r = c.Siap(cache_dir=tmp_path, client=_cliente(csv_)).obtener(municipio="Tizimín")
    assert r.origen == "vivo" and [f["rendimiento_t_ha"] for f in r.datos] == [0.9]


def test_modo_invalido() -> None:
    with pytest.raises(ValueError):
        c.NasaPower(modo="otro")
