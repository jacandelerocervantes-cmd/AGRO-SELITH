"""Pruebas de API: autorización por rol y flujos completos contra PostGIS real."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import anthropic
import httpx
import psycopg
import pytest
from alembic import command
from fastapi.testclient import TestClient

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API))
sys.path.insert(0, str(API / "tests"))
import seed
from milpa_api.llm import Asistente
from milpa_api.main import Prioridades, app, pesos_desde
from test_esquema import HAY_DB, ROOT, URL, _cfg, _conectar

needs_db = pytest.mark.skipif(not HAY_DB, reason="sin PostGIS (make up)")
AGR, EXT, ADM = ({"X-Demo-Login": x} for x in ("demo-agricultor", "demo-extensionista", "demo-admin"))


@pytest.fixture(scope="module")
def cli(monkeypatch_module: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch_module.setenv("DATABASE_URL", URL)
    monkeypatch_module.delenv("ANTHROPIC_API_KEY", raising=False)
    command.downgrade(_cfg(), "base")
    command.upgrade(_cfg(), "head")
    with _conectar() as c:
        seed.sembrar(c, ROOT / "knowledge")
    with TestClient(app) as t:
        yield t


@pytest.fixture(scope="module")
def monkeypatch_module() -> Iterator[pytest.MonkeyPatch]:
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def _parcela(cli: TestClient) -> str:
    return cli.get("/parcelas", headers=AGR).json()[0]["id"]


def _rec(cli: TestClient, esc: str = "normal", **kw: Any) -> dict[str, Any]:
    r = cli.post("/recomendaciones", headers=AGR, json={"parcel_id": _parcela(cli), "escenario": esc, **kw})
    assert r.status_code == 200, r.text
    return r.json()


@needs_db
def test_sin_credenciales_o_usuario_falso_es_401(cli: TestClient) -> None:
    assert cli.get("/parcelas").status_code == 401
    assert cli.get("/parcelas", headers={"X-Demo-Login": "nadie"}).status_code == 401


@needs_db
def test_demo_lista_los_tres_roles_sin_correo(cli: TestClient) -> None:
    r = cli.get("/demo/usuarios").json()
    assert {x["role"] for x in r} == {"admin", "agricultor", "extensionista"}
    assert len(r) == 9 and all("@" not in x["demo_login"] for x in r)
    assert {tuple(x["areas"]) for x in r if x["demo_login"].startswith("demo-experto")} >= {("suelos",), ("agua",), ("patogenos",)}


@needs_db
def test_modo_demo_desactivado_bloquea_todo(cli: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MILPA_DEMO", "0")
    assert cli.get("/demo/usuarios").status_code == 404
    assert cli.get("/parcelas", headers=AGR).status_code == 401


@needs_db
def test_parcelas_con_geojson(cli: TestClient) -> None:
    ps = cli.get("/parcelas", headers=AGR).json()
    assert len(ps) == 4 and ps[0]["geom"]["type"] == "MultiPolygon" and ps[0]["area_ha"] > 5
    assert len(cli.get("/parcelas", headers=EXT).json()) == 4


@needs_db
def test_vulnerabilidad_sube_con_la_canicula(cli: TestClient) -> None:
    n = cli.get("/vulnerabilidad?escenario=normal", headers=AGR).json()
    c = cli.get("/vulnerabilidad?escenario=canicula_prolongada", headers=AGR).json()
    assert (n["nivel"], c["nivel"]) == ("ok", "bad") and len(c["parcelas"]) == 4
    assert cli.get("/vulnerabilidad?escenario=x", headers=AGR).status_code == 404


@needs_db
def test_recomendacion_cumple_restricciones_y_se_persiste(cli: TestClient) -> None:
    d = _rec(cli)
    assert d["datos_provisionales"] and 1 <= len(d["planes"]) <= 3
    for p in d["planes"]:
        assert p["agua_total_mm"] <= p["agua_base_mm"] + 1e-6
        assert p["score_p10"] <= p["score_p90"] and len(p["pasos"]) == 4
        assert abs(sum(f["contribucion"] for f in p["factores"]) - p["score"]) < 1e-6
        assert "chile_habanero" not in [s["crop_id"] for s in p["pasos"]]  # mercado: parcela > cuota
    with _conectar() as c:
        n = c.execute(
            "SELECT count(*) FROM recommendation_plan WHERE run_id=%s", (d["run_id"],)
        ).fetchone()
    assert n == (len(d["planes"]),)


@needs_db
def test_canicula_reordena_sin_gastar_mas_agua(cli: TestClient) -> None:
    n, s = _rec(cli, "normal")["planes"][0], _rec(cli, "canicula_prolongada")["planes"][0]
    assert [x["crop_id"] for x in n["pasos"]] != [x["crop_id"] for x in s["pasos"]]
    assert s["agua_total_mm"] <= s["agua_base_mm"] + 1e-6


@needs_db
def test_prioridades_cambian_pesos_pero_default_equivale_a_defecto() -> None:
    from milpa_engine.knowledge import PESOS_DEFECTO

    assert pesos_desde(Prioridades()) == PESOS_DEFECTO
    assert pesos_desde(Prioridades(ingreso=0))["ingreso_neto"] == 0


@needs_db
def test_recomendacion_de_parcela_ajena_o_invalida_es_404(cli: TestClient) -> None:
    for pid in ("00000000-0000-0000-0000-000000000000", "no-es-uuid"):
        assert cli.post("/recomendaciones", headers=AGR, json={"parcel_id": pid}).status_code == 404


@needs_db
def test_agricultor_decide_y_queda_en_bitacora(cli: TestClient) -> None:
    d = _rec(cli)
    body = {"run_id": d["run_id"], "plan_id": d["planes"][0]["plan_id"], "decision": "aceptar"}
    assert cli.post("/decisiones", headers=EXT, json=body).status_code == 403  # solo decide el agricultor
    assert cli.post("/decisiones", headers=AGR, json={**body, "plan_id": None}).status_code == 422
    assert cli.post("/decisiones", headers=AGR, json=body).status_code == 200
    assert cli.post("/decisiones", headers=AGR, json={**body, "plan_id": None, "decision": "descartar"}).status_code == 200
    with _conectar() as c:
        assert c.execute("SELECT count(*) FROM farmer_decision WHERE run_id=%s", (d["run_id"],)).fetchone() == (2,)
    acciones = [b["accion"] for b in cli.get("/experto/bitacora", headers=EXT).json()]
    assert "decidir" in acciones and "recomendar" in acciones


@needs_db
def test_endpoints_de_experto_cerrados_al_agricultor(cli: TestClient) -> None:
    assert cli.get("/experto/parametros", headers=AGR).status_code == 403
    assert cli.get("/experto/bitacora", headers=AGR).status_code == 403
    p = cli.get("/experto/parametros", headers=EXT).json()
    assert len(p) == 10 and {x["estatus"] for x in p} == {"provisional"}
    assert cli.get("/experto/parametros", headers=ADM).status_code == 200


@needs_db
def test_pregunta_sin_llave_responde_demo_y_flujo_de_benchmark(cli: TestClient) -> None:
    d = _rec(cli)
    sin = cli.post("/preguntas", headers=AGR, json={"texto": "¿Qué siembro si no llueve?", "run_id": d["run_id"]}).json()
    con = cli.post("/preguntas", headers=AGR,
                   json={"texto": "¿Cuándo siembro con canícula larga?", "consentimiento_uso": True}).json()
    assert sin["respuesta"]["origen"] == "demo" and sin["respuesta"]["sintetico"]
    item = {"categoria": "canicula", "split": "benchmark"}
    assert cli.post("/experto/benchmark/items", headers=AGR, json={**item, "question_id": con["pregunta_id"]}).status_code == 403
    assert cli.post("/experto/benchmark/items", headers=EXT, json={**item, "question_id": sin["pregunta_id"]}).status_code == 409
    ok = cli.post("/experto/benchmark/items", headers=EXT, json={**item, "question_id": con["pregunta_id"]})
    assert ok.status_code == 200 and ok.json()["estatus"] == "provisional"
    assert cli.post("/experto/benchmark/items", headers=EXT, json={**item, "question_id": con["pregunta_id"]}).status_code == 409


def _item(parcela: str, tipo: str = "decision", **kw: Any) -> dict[str, Any]:
    import uuid

    return {"client_id": str(uuid.uuid4()), "tipo": tipo, "parcel_id": parcela,
            "creado_at": "2026-11-15T10:00:00Z", **kw}


@needs_db
def test_sincronizar_aplica_decisiones_offline_una_sola_vez(cli: TestClient) -> None:
    pid = _parcela(cli)
    it = _item(pid, escenario="canicula_prolongada", ranking=1, decision="aceptar")
    r1 = cli.post("/sincronizar", headers=AGR, json={"items": [it]}).json()["resultados"][0]
    r2 = cli.post("/sincronizar", headers=AGR, json={"items": [it]}).json()["resultados"][0]
    assert (r1["estado"], r2["estado"]) == ("ok", "duplicado")
    with _conectar() as c:
        row = c.execute(
            "SELECT offline, decidido_at, plan_id FROM farmer_decision WHERE client_id=%s", (it["client_id"],)
        ).fetchone()
    assert row is not None and row[0] is True and row[1].isoformat().startswith("2026-11-15T10:00") and row[2]
    assert any(b["detalle"].get("offline") for b in cli.get("/experto/bitacora", headers=EXT).json())


@needs_db
def test_sincronizar_valida_y_respeta_roles(cli: TestClient) -> None:
    pid = _parcela(cli)
    malo = _item(pid, ranking=None, decision="aceptar")
    falso = {**_item(pid, ranking=1, decision="aceptar"), "client_id": "no-uuid"}
    descartar = _item(pid, decision="descartar")
    r = cli.post("/sincronizar", headers=AGR, json={"items": [malo, falso, descartar]}).json()["resultados"]
    assert sorted(x["estado"] for x in r) == ["error", "error", "ok"]
    assert cli.post("/sincronizar", headers=EXT, json={"items": []}).status_code == 403


@needs_db
def test_sincronizar_preguntas_offline_devuelve_respuesta(cli: TestClient) -> None:
    it = _item(_parcela(cli), "pregunta", texto="¿Cuándo siembro?", consentimiento_uso=True)
    r = cli.post("/sincronizar", headers=AGR, json={"items": [it]}).json()["resultados"][0]
    assert r["estado"] == "ok" and r["respuesta"]["origen"] == "demo"
    with _conectar() as c:
        assert c.execute("SELECT offline, consentimiento_uso FROM producer_question WHERE client_id=%s",
                         (it["client_id"],)).fetchone() == (True, True)


# ---- Asistente Claude (sin red: cliente falso) ----
def _msg(texto: str, stop: str = "end_turn") -> Any:
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=texto)])


class FakeMessages:
    def __init__(self, fn: Any) -> None:
        self.fn, self.llamadas = fn, []

    def create(self, **kw: Any) -> Any:
        self.llamadas.append(kw)
        return self.fn(kw)


def _cliente(fn: Any) -> Any:
    m = FakeMessages(fn)
    return SimpleNamespace(messages=m, beta=SimpleNamespace(messages=m)), m


CFG = {"modelo_principal": "claude-sonnet-5-5", "modelo_respaldo": "claude-haiku-5-5",
       "esfuerzo": {"principal": "medium", "rapido": "low"}, "max_tokens": 256,
       "fallback_servidor_por_rechazo": True}


def test_asistente_usa_sonnet_sin_temperature_y_con_fallback_de_servidor() -> None:
    cl, m = _cliente(lambda kw: _msg("Siembre temprano."))
    r = Asistente(CFG, cl).responder("¿cuándo?", {"x": 1})
    kw = m.llamadas[0]
    assert (r.origen, r.modelo, r.texto) == ("claude", "claude-sonnet-5-5", "Siembre temprano.")
    assert "temperature" not in kw and kw["output_config"] == {"effort": "medium"}
    assert kw["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in kw["betas"]


def test_asistente_cae_a_haiku_y_luego_a_demo() -> None:
    err = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))

    def solo_haiku(kw: Any) -> Any:
        if kw["model"] == "claude-sonnet-5-5":
            raise err
        return _msg("Respuesta de Haiku.")

    cl, _ = _cliente(solo_haiku)
    assert Asistente(CFG, cl).responder("?", {}).modelo == "claude-haiku-5-5"

    def todo_falla(kw: Any) -> Any:
        raise err

    cl2, _ = _cliente(todo_falla)
    r = Asistente(CFG, cl2).responder("?", {})
    assert r.origen == "demo" and r.sintetico


def test_asistente_trata_rechazo_como_fallo() -> None:
    cl, _ = _cliente(lambda kw: _msg("", stop="refusal"))
    assert Asistente(CFG, cl).responder("?", {}).origen == "demo"


_ = psycopg  # (import usado por las pruebas con BD)
