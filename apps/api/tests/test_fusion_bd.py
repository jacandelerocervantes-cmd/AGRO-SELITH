"""La fusión cargada a PostGIS y expuesta por la API."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API / "tests"))
sys.path.insert(0, str(API.parents[1] / "pipelines"))
from milpa_pipelines.cargar_bd import cargar_fusion  # noqa: E402
from test_api import AGR, EXT, cli, monkeypatch_module, needs_db  # noqa: E402, F401
from test_esquema import _conectar  # noqa: E402


@pytest.fixture(scope="module")
def carga(cli):  # type: ignore[no-untyped-def]  # noqa: F811
    with _conectar() as c:
        return cargar_fusion(c, modo="demo")


@needs_db
def test_carga_crea_celdas_pesos_y_clima_con_incertidumbre(carga) -> None:  # type: ignore[no-untyped-def]
    assert carga["dias"] == 184 and carga["celdas"] >= 16
    with _conectar() as c:
        pesos = c.execute("SELECT parcel_id, sum(peso) FROM parcel_cell GROUP BY parcel_id").fetchall()
        assert len(pesos) == 4 and all(abs(p[1] - 1) < 1e-6 for p in pesos)
        n = c.execute("SELECT count(*) FROM climate_daily WHERE precip_sd IS NOT NULL AND tmax_sd IS NOT NULL").fetchone()
        assert n == (carga["filas_clima"],)
        assert c.execute("SELECT count(*) FROM climate_cell WHERE res_m=100").fetchone() == (carga["celdas"],)


@needs_db
def test_carga_es_idempotente(carga) -> None:  # type: ignore[no-untyped-def]
    with _conectar() as c:
        otra = cargar_fusion(c, modo="demo")
        assert otra["filas_clima"] == carga["filas_clima"]
        assert c.execute("SELECT count(*) FROM climate_daily").fetchone() == (carga["filas_clima"],)


@needs_db
def test_suelo_sin_dato_queda_marcado_sintetico(carga) -> None:  # type: ignore[no-untyped-def]
    with _conectar() as c:
        assert c.execute("SELECT count(*) FROM parcel_soil WHERE sintetico").fetchone() == (4,)
        assert c.execute("SELECT count(*) FROM parcel_soil WHERE ph IS NOT NULL").fetchone() == (0,)


@needs_db
def test_api_contexto_de_parcela(cli, carga) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    pid = cli.get("/parcelas", headers=AGR).json()[0]["id"]
    d = cli.get(f"/parcelas/{pid}/contexto", headers=AGR).json()
    assert d["clima"]["dias"] == 184 and d["clima"]["precip_total_mm"] > 100
    assert d["clima"]["racha_seca_max_dias_jul_ago"] >= 0 and d["clima"]["precip_sd_medio_mm"] >= 0.5
    assert d["suelo"]["sintetico"] is True and d["suelo"]["ph"] is None
    assert d["vegetacion"]["disponibilidad_optica"]
    assert cli.get(f"/parcelas/{pid}/contexto", headers=EXT).status_code == 200
    assert cli.get("/parcelas/no-es-uuid/contexto", headers=AGR).status_code == 404
