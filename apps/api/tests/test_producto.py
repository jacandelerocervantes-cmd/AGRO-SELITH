"""El producto de punta a punta contra PostGIS: parcela dibujada, capas NASA, chat, respaldo y cola de expertos."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

API = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API / "tests"))
from test_api import AGR, EXT, cli, monkeypatch_module, needs_db  # noqa: E402, F401, F811
from test_esquema import _conectar  # noqa: E402


def exp(area: str) -> dict[str, str]:
    return {"X-Demo-Login": f"demo-experto-{area}"}


SINT = {"X-Demo-Login": "demo-productor-sintetico"}
ADMIN = {"X-Demo-Login": "demo-admin"}
CUADRADO = {"type": "Polygon", "coordinates": [[[-88.1500, 21.1400], [-88.1490, 21.1400], [-88.1490, 21.1410], [-88.1500, 21.1410], [-88.1500, 21.1400]]]}
CORBATA = {"type": "Polygon", "coordinates": [[[-88.15, 21.14], [-88.149, 21.141], [-88.149, 21.14], [-88.15, 21.141], [-88.15, 21.14]]]}
DIMINUTA = {"type": "Polygon", "coordinates": [[[-88.15, 21.14], [-88.14999, 21.14], [-88.14999, 21.14001], [-88.15, 21.14001], [-88.15, 21.14]]]}


@pytest.fixture(scope="module")
def pid(cli) -> str:  # type: ignore[no-untyped-def]  # noqa: F811
    r = cli.post("/mis-parcelas", headers=AGR, json={"nombre": "Mi milpa dibujada", "geojson": CUADRADO})
    assert r.status_code == 200, r.text
    capas = cli.post(f"/mis-parcelas/{r.json()['id']}/capas", headers=AGR)
    assert capas.status_code == 200, capas.text
    return str(r.json()["id"])


def _uid(login: str) -> str:
    with _conectar() as c:
        r = c.execute("SELECT id FROM user_account WHERE demo_login=%s", (login,)).fetchone()
    assert r is not None
    return str(r[0])


def _asignar(message_id: str, area: str) -> str:
    """Pone la solicitud de un mensaje en manos del experto del área (el reparto al azar se prueba aparte)."""
    with _conectar() as c:
        r = c.execute(
            "UPDATE review_request SET estado='asignada', asignada_a=%s, asignada_at=now() WHERE message_id=%s RETURNING id",
            (_uid(f"demo-experto-{area}"), message_id),
        ).fetchone()
        c.commit()
    assert r is not None
    return str(r[0])


def _chat(cli: Any, pid: str,  # noqa: F811
           texto: str, idioma: str = "es", **kw: Any) -> dict[str, Any]:
    r = cli.post("/chat/mensajes", headers=AGR, json={"texto": texto, "parcel_id": pid, "idioma": idioma, **kw})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- parcela dibujada
@needs_db
def test_parcela_dibujada_mide_metros_cuadrados(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    ps = {p["id"]: p for p in cli.get("/mis-parcelas", headers=AGR).json()}
    assert 11_000 < ps[pid]["area_m2"] < 12_000 and ps[pid]["dibujada"] is True
    assert ps[pid]["area_ha"] == pytest.approx(ps[pid]["area_m2"] / 10_000)
    sembradas = [p for p in ps.values() if not p["dibujada"]]
    assert len(sembradas) == 4 and all(p["area_m2"] and p["area_m2"] > 100_000 for p in sembradas)


@needs_db
def test_parcela_invalida_se_rechaza(cli) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    assert cli.post("/mis-parcelas", headers=AGR, json={"nombre": "x", "geojson": CORBATA}).status_code == 422
    assert cli.post("/mis-parcelas", headers=AGR, json={"nombre": "x", "geojson": DIMINUTA}).status_code == 422
    assert cli.post("/mis-parcelas", headers=AGR, json={"nombre": "x", "geojson": {"type": "Point", "coordinates": [0, 0]}}).status_code == 422
    assert cli.post("/mis-parcelas", headers=AGR, json={"nombre": "x", "geojson": {"nada": 1}}).status_code == 422
    assert cli.post("/mis-parcelas", headers=EXT, json={"nombre": "x", "geojson": CUADRADO}).status_code == 403


@needs_db
def test_otro_productor_no_ve_ni_borra_mi_parcela(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    assert pid not in {p["id"] for p in cli.get("/mis-parcelas", headers=SINT).json()}
    assert cli.delete(f"/mis-parcelas/{pid}", headers=SINT).status_code == 404
    assert cli.get(f"/capas/vulnerabilidad?parcel_id={pid}", headers=SINT).status_code == 404


# ---------------------------------------------------------------- capas NASA armonizadas
@needs_db
def test_catalogo_de_capas_marca_nasa_y_ejemplos(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    cat = {c["id"]: c for c in cli.get("/capas", headers=AGR).json()}
    assert {"imerg", "smap", "ndvi_landsat", "ndvi_modis", "lst", "srtm_pendiente_pct", "grace", "vulnerabilidad"} <= set(cat)
    for k in ("imerg", "smap", "lst", "vulnerabilidad"):  # sin cuenta Earthdata: ejemplo rotulado (la vulnerabilidad mezcla)
        assert cat[k]["disponible"] and cat[k]["nasa"] and cat[k]["sintetico"]
    for k in ("ndvi_landsat", "ndvi_modis", "srtm_pendiente_pct", "srtm_elevacion"):  # datos reales grabados de la NASA
        assert cat[k]["disponible"] and cat[k]["nasa"] and cat[k]["sintetico"] is False
    for k in ("ndvi_s2", "lst_modis", "et_modis"):  # también reales; Sentinel-2 es de la ESA (agencia socia)
        assert cat[k]["disponible"] and cat[k]["sintetico"] is False
    assert cat["ndvi_s2"]["nasa"] is False and cat["ndvi_s2"]["resolucion_nativa_m"] == 10
    assert cat["gedi"]["disponible"] is False  # su ejemplo no trae ningún valor: no se carga
    assert cat["smap"]["nombre"]["en"] == "Soil moisture (SMAP)" and cat["smap"]["resolucion_nativa_m"] == 9000


@needs_db
def test_capas_por_celda_de_100_m_para_pintar_en_el_mapa(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    v = cli.get(f"/capas/vulnerabilidad?parcel_id={pid}", headers=AGR).json()
    assert v["type"] == "FeatureCollection" and len(v["features"]) >= 4
    assert all(0 <= f["properties"]["valor"] <= 1 for f in v["features"]) and v["sintetico"]
    n = cli.get(f"/capas/ndvi_landsat?parcel_id={pid}", headers=AGR).json()
    vals = [f["properties"]["valor"] for f in n["features"]]
    assert max(vals) > min(vals) and n["min"] == pytest.approx(min(vals)) and n["resolucion_nativa_m"] == 30
    assert cli.get("/capas/no_existe", headers=AGR).status_code == 404


@needs_db
def test_la_capa_de_alta_resolucion_varia_entre_celdas_y_la_gruesa_no(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    pend = [f["properties"]["valor"] for f in cli.get(f"/capas/srtm_pendiente_pct?parcel_id={pid}", headers=AGR).json()["features"]]
    humedad = {round(f["properties"]["valor"], 9) for f in cli.get(f"/capas/smap?parcel_id={pid}", headers=AGR).json()["features"]}
    assert len({round(p, 6) for p in pend}) > 1 and len(humedad) == 1


@needs_db
def test_serie_en_el_tiempo_de_una_capa(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    s = cli.get(f"/capas/imerg/serie?parcel_id={pid}", headers=AGR).json()["serie"]
    fechas = [x["fecha"] for x in s]
    assert len(s) > 150 and fechas == sorted(fechas) and all(x["valor"] is None or x["valor"] >= 0 for x in s)


# ---------------------------------------------------------------- chat: tres estrategias
@needs_db
def test_pregunta_de_plan_devuelve_tres_estrategias_solo_ia_y_entra_a_la_cola(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    r = _chat(cli, pid, "¿Qué siembro si la canícula se alarga?")
    u, a = r["mensajes"]
    assert u["rol"] == "usuario" and u["area"] == "agua" and a["rol"] == "asistente"
    assert a["estado_respaldo"] == "solo_ia" and a["contenido"]["generado_por"] == "determinista"
    est = a["contenido"]["estrategias"]
    assert [e["etiqueta"] for e in est] == ["actual", "opcion_1", "opcion_2"]
    assert a["contenido"]["escenario"] == "canicula_prolongada" and 11_000 < a["contenido"]["area_m2"] < 12_000
    for e in est:
        assert len(e["pasos"]) == 4 and all(e["explicacion"][k] for k in ("por_que", "beneficios", "evidencia", "vacios", "riesgos"))
        assert e["agua_base_mm"] == pytest.approx(est[0]["agua_total_mm"])
    assert est[0]["pasos"][0]["crop_id"] == "milpa_tradicional"
    with _conectar() as c:
        assert c.execute("SELECT area, estado FROM review_request WHERE message_id=%s", (a["id"],)).fetchone() == ("agua", "pendiente")


@needs_db
def test_la_evidencia_distingue_capa_real_ejemplo_y_no_disponible(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    e = _chat(cli, pid, "¿Qué siembro este año?")["mensajes"][1]["contenido"]["estrategias"][1]["explicacion"]
    assert any("POWER" in x for x in e["evidencia"]) and any("SMAP" in x and "ejemplo" in x for x in e["evidencia"])
    assert any("GEDI" in x for x in e["vacios"]) and any("INEGI" in x for x in e["vacios"])


@needs_db
def test_respuesta_en_ingles(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    a = _chat(cli, pid, "What should I plant if there is a dry spell?", "en")["mensajes"][1]
    assert a["texto"].startswith("I compared three strategies") and a["idioma"] == "en"
    est = a["contenido"]["estrategias"]
    assert est[1]["explicacion"]["por_que"].startswith("It contributes")
    assert all("Abono" not in p["nombre"] and "Cobertura" not in p["nombre"] for e in est for p in e["pasos"])
    assert any("Engine rules" in x for x in est[0]["explicacion"]["evidencia"])


@needs_db
def test_pregunta_general_no_necesita_plan_y_se_clasifica_por_area(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    a = _chat(cli, pid, "How do I improve my soil organic matter?", "en")["mensajes"][1]
    assert a["area"] == "suelos" and "estrategias" not in a["contenido"] and "reviewed by an expert" in a["texto"]
    sin_parcela = cli.post("/chat/mensajes", headers=AGR, json={"texto": "¿Qué siembro este año?"}).json()["mensajes"][1]
    assert "estrategias" not in sin_parcela["contenido"]  # sin parcela dibujada no hay plan


@needs_db
def test_chat_valida_y_respeta_roles(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    assert cli.post("/chat/mensajes", headers=AGR, json={"texto": "x"}).status_code == 422
    assert cli.post("/chat/mensajes", headers=exp("suelos"), json={"texto": "hola amigos"}).status_code == 403
    assert cli.post("/chat/mensajes", headers=AGR, json={"texto": "hola amigos", "conversation_id": "00000000-0000-0000-0000-000000000000"}).status_code == 404
    assert cli.post("/chat/mensajes", headers=SINT, json={"texto": "hola amigos", "parcel_id": pid}).status_code == 404


@needs_db
def test_conversaciones_se_guardan_y_son_privadas(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    r = _chat(cli, pid, "¿Cómo cuido el suelo de mi milpa?")
    cid = r["conversation_id"]
    r2 = _chat(cli, pid, "¿Y el agua?", conversation_id=cid)
    assert r2["conversation_id"] == cid
    conv = cli.get(f"/chat/conversaciones/{cid}", headers=AGR).json()
    assert [m["rol"] for m in conv["mensajes"]] == ["usuario", "asistente", "usuario", "asistente"]
    assert cid in {c["id"] for c in cli.get("/chat/conversaciones", headers=AGR).json()}
    assert cli.get(f"/chat/conversaciones/{cid}", headers=SINT).status_code == 404


@needs_db
def test_el_agricultor_decide_y_queda_registrado(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    mid = _chat(cli, pid, "¿Qué siembro este año?")["mensajes"][1]["id"]
    assert cli.post(f"/chat/mensajes/{mid}/decision", headers=AGR, json={"decision": "aceptar"}).status_code == 422
    assert cli.post(f"/chat/mensajes/{mid}/decision", headers=SINT, json={"decision": "descartar"}).status_code == 404
    assert cli.post(f"/chat/mensajes/{mid}/decision", headers=exp("suelos"), json={"decision": "descartar"}).status_code == 403
    assert cli.post(f"/chat/mensajes/{mid}/decision", headers=AGR, json={"decision": "aceptar", "ranking": 1}).status_code == 200
    assert cli.post(f"/chat/mensajes/{mid}/decision", headers=AGR, json={"decision": "descartar"}).status_code == 200
    with _conectar() as c:
        assert c.execute("SELECT count(*) FROM chat_decision WHERE message_id=%s", (mid,)).fetchone() == (2,)
    assert any(b["accion"] == "decidir" and b["detalle"].get("ranking") == 1 for b in cli.get("/experto/bitacora", headers=EXT).json())


# ---------------------------------------------------------------- cola de expertos por área
@needs_db
def test_la_cola_se_subdivide_por_area_y_cada_experto_ve_solo_la_suya(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    _chat(cli, pid, "¿Cómo mejoro el suelo?")  # asegura al menos una solicitud de suelos
    c = cli.get("/experto/cola", headers=exp("suelos")).json()
    assert set(c["areas_totales"]) == {"suelos", "patogenos", "agua", "clima", "mercado", "cultivos"}
    assert c["mis_areas"] == ["suelos"] and c["pendientes_mis_areas"] == c["areas_totales"]["suelos"]
    assert c["pendientes_mis_areas"] > 0
    assert cli.get("/experto/cola", headers=AGR).status_code == 403
    assert cli.post("/experto/cola/siguiente", headers=ADMIN).status_code == 403  # el admin no tiene áreas


@needs_db
def test_asignacion_aleatoria_solo_de_mi_area_y_la_misma_hasta_revisarla(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    h = exp("patogenos")
    actual = cli.post("/experto/cola/siguiente", headers=h).json()
    assert actual["area"] == "patogenos" and actual["estado"] == "asignada" and actual["pregunta"]
    assert cli.post("/experto/cola/siguiente", headers=h).json()["id"] == actual["id"]  # no toma otra sin revisar
    assert cli.get(f"/experto/solicitudes/{actual['id']}", headers=exp("agua")).status_code == 403
    assert cli.get("/experto/cola", headers=h).json()["asignadas_a_mi"] == [actual["id"]]
    vistas = {actual["id"]}
    for _ in range(3):
        assert cli.post(f"/experto/solicitudes/{actual['id']}/revision", headers=h, json={"decision": "confirmar"}).status_code == 200
        sig = cli.post("/experto/cola/siguiente", headers=h).json()
        if sig.get("vacia"):
            break
        assert sig["area"] == "patogenos" and sig["id"] not in vistas
        vistas.add(sig["id"])
        actual = sig
    assert len(vistas) >= 2


@needs_db
def test_cuando_no_quedan_solicitudes_en_mi_area_la_cola_responde_vacia(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    h = exp("mercado")
    s: dict[str, Any] = {}
    for _ in range(30):
        s = cli.post("/experto/cola/siguiente", headers=h).json()
        if s.get("vacia"):
            break
        assert cli.post(f"/experto/solicitudes/{s['id']}/revision", headers=h, json={"decision": "confirmar"}).status_code == 200
    assert s == {"vacia": True} and cli.get("/experto/cola", headers=h).json()["pendientes_mis_areas"] == 0


# ---------------------------------------------------------------- respaldo: solo IA -> con respaldo / revocada
@needs_db
def test_confirmar_pasa_la_respuesta_a_con_respaldo_y_aparece_en_reportes(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    r = _chat(cli, pid, "¿Cómo mejoro un suelo pedregoso?")
    cid, mid = r["conversation_id"], r["mensajes"][1]["id"]
    assert r["mensajes"][1]["area"] == "suelos"
    rid = _asignar(mid, "suelos")
    ok = cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("suelos"), json={"decision": "confirmar", "fuentes": ["INIFAP, guía del milpero"]})
    assert ok.status_code == 200 and ok.json()["estado_respaldo"] == "con_respaldo"
    assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("suelos"), json={"decision": "confirmar"}).status_code == 409
    m = next(x for x in cli.get(f"/chat/conversaciones/{cid}", headers=AGR).json()["mensajes"] if x["id"] == mid)
    assert m["estado_respaldo"] == "con_respaldo" and m["revision"]["fuentes"] == ["INIFAP, guía del milpero"]
    rep = [x for x in cli.get("/chat/reportes", headers=AGR).json() if x["id"] == mid]
    assert rep and rep[0]["decision"] == "confirmar" and rep[0]["pregunta"] == "¿Cómo mejoro un suelo pedregoso?" and rep[0]["area"] == "suelos"


@needs_db
def test_corregir_exige_texto_y_lo_muestra_al_productor(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    r = _chat(cli, pid, "¿Cuánto abono verde necesito en suelo pobre?")
    cid, mid = r["conversation_id"], r["mensajes"][1]["id"]
    rid = _asignar(mid, "suelos")
    assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("suelos"), json={"decision": "corregir"}).status_code == 422
    assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("agua"), json={"decision": "confirmar"}).status_code == 403
    assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("suelos"), json={"decision": "corregir", "texto_corregido": "Siembre mucuna al inicio de lluvias."}).status_code == 200
    m = next(x for x in cli.get(f"/chat/conversaciones/{cid}", headers=AGR).json()["mensajes"] if x["id"] == mid)
    assert m["estado_respaldo"] == "con_respaldo" and m["revision"]["texto_corregido"] == "Siembre mucuna al inicio de lluvias."
    assert next(x for x in cli.get("/chat/reportes", headers=AGR).json() if x["id"] == mid)["texto_corregido"].startswith("Siembre")


@needs_db
def test_revocar_exige_motivo_marca_revocada_y_avisa_en_la_conversacion(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    r = _chat(cli, pid, "Mi frijol tiene una plaga de gusano, ¿qué hago?")
    cid, mid = r["conversation_id"], r["mensajes"][1]["id"]
    assert r["mensajes"][1]["area"] == "patogenos"
    rid = _asignar(mid, "patogenos")
    assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("patogenos"), json={"decision": "revocar"}).status_code == 422
    assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("patogenos"), json={"decision": "revocar", "motivo": "No aplica a su zona."}).status_code == 200
    msgs = cli.get(f"/chat/conversaciones/{cid}", headers=AGR).json()["mensajes"]
    assert next(x for x in msgs if x["id"] == mid)["estado_respaldo"] == "revocada"
    assert msgs[-1]["rol"] == "sistema" and "No aplica a su zona." in msgs[-1]["texto"]
    rep = next(x for x in cli.get("/chat/reportes", headers=AGR).json() if x["id"] == mid)
    assert rep["estado_respaldo"] == "revocada" and rep["motivo"] == "No aplica a su zona."


@needs_db
def test_corpus_incluye_solo_preguntas_con_consentimiento_o_sinteticas(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    si = _chat(cli, pid, "¿El abono verde sirve en suelo rojo?", consentimiento_uso=True)["mensajes"][1]["id"]
    no = _chat(cli, pid, "¿Y el acahual de suelo rojo sirve?", consentimiento_uso=False)["mensajes"][1]["id"]
    for mid in (si, no):
        rid = _asignar(mid, "suelos")
        assert cli.post(f"/experto/solicitudes/{rid}/revision", headers=exp("suelos"), json={"decision": "confirmar"}).status_code == 200
    textos = {f["pregunta"] for f in cli.get("/experto/corpus", headers=exp("suelos")).json()}
    assert "¿El abono verde sirve en suelo rojo?" in textos and "¿Y el acahual de suelo rojo sirve?" not in textos
    assert cli.get("/experto/corpus", headers=AGR).status_code == 403


# ---------------------------------------------------------------- FAO GAEZ
@needs_db
def test_gaez_por_parcela_con_datos_reales_de_la_fao(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    g = cli.get(f"/mis-parcelas/{pid}/gaez", headers=AGR).json()
    assert g["sintetico"] is False and "FAO GAEZ" in g["fuente"]
    maiz = g["cultivos"]["Maize"]
    assert set(maiz) == {"hist_bajo", "hist_alto", "fut45", "fut85"}
    assert maiz["hist_bajo"]["indice"] == pytest.approx(16.7, abs=0.2) and maiz["hist_bajo"]["rendimiento"] == pytest.approx(610)
    assert maiz["hist_alto"]["rendimiento"] > maiz["fut85"]["rendimiento"] > 0  # el clima futuro baja el rendimiento alcanzable
    assert cli.get(f"/mis-parcelas/{pid}/gaez", headers=EXT).status_code == 200
    assert cli.get(f"/mis-parcelas/{pid}/gaez", headers=SINT).status_code == 404


@needs_db
def test_la_evidencia_de_las_estrategias_cita_gaez_y_su_riesgo(cli, pid) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    e = _chat(cli, pid, "¿Qué siembro este año?")["mensajes"][1]["contenido"]["estrategias"][0]["explicacion"]
    assert any("FAO GAEZ" in x and "17/100" in x for x in e["evidencia"])
    assert any("GAEZ" in r for r in e["riesgos"])


def test_validacion_eeuu_se_expone_con_numeros_reales(cli) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    r = cli.get("/referencia/validacion")
    assert r.status_code == 200
    d = r.json()
    assert d["ndvi_sentinel2_10m_vs_naip"]["correlacion"] > 0.7 and "Hidalgo" in d["lugar"]["condado"]
