"""Conversación del productor con el asistente. Cada respuesta nace "solo IA, sin respaldo académico" y entra
a la cola de revisión de su área; un experto de esa área la confirma, corrige o revoca."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from milpa_engine import Motor
from milpa_engine.explicacion import explicar
from milpa_engine.knowledge import construir_problema
from pydantic import BaseModel, Field

from .areas import clasificar_area, detectar_escenario, nombre_cultivo, pide_plan
from .auth import Usuario, get_db, requiere
from .config import conocimiento, llm_config
from .deps import audit, parcela_accesible
from .llm import Asistente
from .seguridad import limitar, sanear_texto, tope_diario_chat

router = APIRouter(prefix="/chat", tags=["chat"])
BASE = "milpa_tradicional"

# capa de explicación -> capas de la base que la respaldan
MAPA_CAPAS = {
    "imerg": ("imerg",), "smap": ("smap",), "ndvi_s2": ("ndvi_s2",), "lst_modis": ("lst_modis",), "et_modis": ("et_modis",), "gldas": ("gldas", "gldas_et"), "ndvi_modis": ("ndvi_modis",),
    "ndvi_landsat": ("ndvi_landsat",), "srtm": ("srtm_elevacion", "srtm_pendiente_pct"), "ecostress": ("lst",),
    "grace": ("grace",), "gedi": ("gedi",),
}


class MensajeIn(BaseModel):
    texto: str = Field(min_length=2, max_length=2000)
    conversation_id: str | None = None
    parcel_id: str | None = None
    idioma: Literal["es", "en"] = "es"
    via_voz: bool = False
    consentimiento_uso: bool = False


class DecisionChatIn(BaseModel):
    decision: Literal["aceptar", "ajustar", "descartar"]
    ranking: int | None = Field(None, ge=0, le=3)
    comentario: str | None = Field(None, max_length=1000)


def contexto_capas(db: Any) -> dict[str, dict[str, Any]]:
    filas = {r["capa"]: r for r in db.execute(
        "SELECT capa, bool_or(sintetico) AS sintetico, max(fuente) AS fuente FROM layer_value GROUP BY capa").fetchall()}
    out: dict[str, dict[str, Any]] = {}
    for clave, capas in MAPA_CAPAS.items():
        hay = [filas[c] for c in capas if c in filas]
        out[clave] = ({"disponible": True, "sintetico": any(h["sintetico"] for h in hay), "fuente": hay[0]["fuente"]}
                      if hay else {"disponible": False, "sintetico": False, "fuente": ""})
    clima = db.execute("SELECT count(*) AS n FROM climate_daily WHERE fuente LIKE 'fusion%%'").fetchone()["n"] > 0
    for k, f in (("power", "NASA POWER"), ("era5", "ERA5")):
        out[k] = {"disponible": clima, "sintetico": False, "fuente": f}
    return out


def _pasos(secuencia: tuple[str, ...], idioma: str) -> list[dict[str, Any]]:
    return [{"anio": i + 1, "crop_id": c, "nombre": nombre_cultivo(c, idioma)} for i, c in enumerate(secuencia)]


def contexto_gaez(db: Any, parcel_id: str | None) -> dict[str, dict[str, Any]]:
    if not parcel_id:
        return {}
    out: dict[str, dict[str, Any]] = {}
    for f in db.execute("SELECT cultivo, escenario, indice::float, rendimiento_kg_ms_ha::float AS rend FROM parcel_gaez WHERE parcel_id=%s", (parcel_id,)).fetchall():
        out.setdefault(f["cultivo"], {})[f["escenario"]] = {"indice": f["indice"], "rend": f["rend"]}
    return out


def estrategias(db: Any, area_m2: float, escenario: str, idioma: str, parcel_id: str | None = None) -> dict[str, Any]:
    """Rotación actual + dos alternativas (mínimo tres), cada una con por qué, evidencia, vacíos y riesgos."""
    k = conocimiento()
    prob = construir_problema(k, escenario, 4, BASE, max(area_m2 / 10_000, 0.01))
    planes = Motor(prob).comparar(alternativas=2)
    base = planes[0]
    ctx = {"capas": contexto_capas(db), "estatus_parametros": "provisional", "suelo_sin_medicion": True, "hay_estaciones": False,
           "gaez": contexto_gaez(db, parcel_id)}
    est = []
    for pl in planes:
        est.append({
            "ranking": pl.ranking, "etiqueta": "actual" if pl.ranking == 0 else f"opcion_{pl.ranking}",
            "pasos": _pasos(pl.secuencia, idioma), "score": pl.score, "p10": pl.score_p10, "p50": pl.score_p50,
            "p90": pl.score_p90, "agua_total_mm": pl.agua_total_mm, "agua_base_mm": base.agua_total_mm,
            "ingreso_estimado": pl.ingreso_estimado, "delta_n": pl.delta_n, "delta_mo": pl.delta_mo,
            "riesgo_plaga": pl.riesgo_plaga, "explicacion": explicar(pl, base, ctx, idioma),
            "factores": [{"factor": f.factor, "peso": f.peso, "valor": f.valor_norm, "aporte": f.contribucion}
                         for f in pl.factores if f.peso],
        })
    return {"tipo": "comparacion", "escenario": escenario, "area_m2": area_m2, "estrategias": est,
            "capas": ctx["capas"], "provisional": True}


def resumen(c: dict[str, Any], idioma: str) -> str:
    est = c["estrategias"]
    nom = lambda e: " → ".join(p["nombre"] for p in e["pasos"])  # noqa: E731
    if idioma == "en":
        txt = f"I compared three strategies for your parcel ({c['area_m2']:,.0f} m²): the one you use today and two alternatives. "
        for e in est[1:]:
            txt += f"Option {e['ranking']}: {nom(e)}. {e['explicacion']['beneficios'][0]} "
        return txt + "Below you will find the evidence, what is still unknown and the risks. The decision is yours."
    txt = f"Comparé tres estrategias para su parcela ({c['area_m2']:,.0f} m²): la que usa hoy y dos alternativas. "
    for e in est[1:]:
        txt += f"Opción {e['ranking']}: {nom(e)}. {e['explicacion']['beneficios'][0]} "
    return txt + "Abajo están la evidencia, lo que aún no se sabe y los riesgos. La decisión es suya."


def _msg(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(r["id"]), "rol": r["rol"], "texto": r["texto"], "contenido": r["contenido"], "idioma": r["idioma"],
            "via_voz": r["via_voz"], "estado_respaldo": r["estado_respaldo"], "area": r["area"],
            "sintetico": r["sintetico"], "created_at": r["created_at"].isoformat()}


@router.post("/mensajes", dependencies=[Depends(limitar("chat", 10, 60)), Depends(tope_diario_chat)])
def enviar(body: MensajeIn, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> dict[str, Any]:
    body.texto = sanear_texto(body.texto)
    if len(body.texto) < 2:
        raise HTTPException(422, "Escriba su pregunta")
    parcela = parcela_accesible(db, u, body.parcel_id) if body.parcel_id else None
    if body.conversation_id:
        conv = db.execute("SELECT id FROM chat_conversation WHERE id=%s AND user_id=%s", (body.conversation_id, u.id)).fetchone()
        if conv is None:
            raise HTTPException(404, "Conversación no encontrada")
        conv_id = str(conv["id"])
    else:
        conv_id = str(db.execute(
            "INSERT INTO chat_conversation(user_id,parcel_id,titulo,idioma) VALUES (%s,%s,%s,%s) RETURNING id",
            (u.id, body.parcel_id, body.texto[:60], body.idioma)).fetchone()["id"])
    area = clasificar_area(body.texto)
    um = db.execute(
        """INSERT INTO chat_message(conversation_id,rol,texto,idioma,via_voz,area,consentimiento_uso)
           VALUES (%s,'usuario',%s,%s,%s,%s,%s) RETURNING *""",
        (conv_id, body.texto, body.idioma, body.via_voz, area, body.consentimiento_uso)).fetchone()

    contenido: dict[str, Any] = {}
    contexto: dict[str, Any] = {"datos_provisionales": True, "area_de_la_pregunta": area}
    if parcela and pide_plan(body.texto):
        contenido = estrategias(db, parcela["area_m2"] or (parcela["area_ha"] or 1) * 10_000,
                                detectar_escenario(body.texto), body.idioma, body.parcel_id)
        contexto["comparacion"] = [{"opcion": e["etiqueta"], "pasos": [p["nombre"] for p in e["pasos"]],
                                    "beneficios": e["explicacion"]["beneficios"], "vacios": e["explicacion"]["vacios"],
                                    "riesgos": e["explicacion"]["riesgos"]} for e in contenido["estrategias"]]
    r = Asistente(llm_config()).responder(body.texto, contexto, body.idioma)
    if r.origen == "claude":
        texto, gen = r.texto, "claude"
    elif contenido:
        texto, gen = resumen(contenido, body.idioma), "determinista"
    else:
        texto, gen = (("Your question was saved and will be reviewed by an expert in the " + area + " area. The language model is not connected yet.")
                      if body.idioma == "en" else
                      (f"Su pregunta quedó guardada y la revisará un experto del área de {area}. Aún no hay conexión con el modelo de lenguaje.")), "demo"
    contenido = {**contenido, "generado_por": gen, "modelo": r.modelo}
    am = db.execute(
        """INSERT INTO chat_message(conversation_id,rol,texto,idioma,estado_respaldo,area,contenido)
           VALUES (%s,'asistente',%s,%s,'solo_ia',%s,%s) RETURNING *""",
        (conv_id, texto, body.idioma, area, json.dumps(contenido))).fetchone()
    db.execute("INSERT INTO review_request(message_id,area) VALUES (%s,%s)", (am["id"], area))
    db.execute("UPDATE chat_conversation SET updated_at=now() WHERE id=%s", (conv_id,))
    audit(db, u, "chat", "chat_message", str(am["id"]), {"area": area, "generado_por": gen})
    db.commit()
    return {"conversation_id": conv_id, "mensajes": [_msg(um), _msg(am)]}


@router.get("/conversaciones")
def conversaciones(u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    return [{**r, "id": str(r["id"]), "updated_at": r["updated_at"].isoformat()} for r in db.execute(
        "SELECT id, titulo, idioma, updated_at FROM chat_conversation WHERE user_id=%s ORDER BY updated_at DESC LIMIT 50",
        (u.id,)).fetchall()]


@router.get("/conversaciones/{cid}")
def conversacion(cid: str, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> dict[str, Any]:
    try:
        c = db.execute("SELECT id, titulo, parcel_id FROM chat_conversation WHERE id=%s AND user_id=%s", (cid, u.id)).fetchone()
    except Exception:  # noqa: BLE001 - uuid inválido
        db.rollback()
        c = None
    if c is None:
        raise HTTPException(404, "Conversación no encontrada")
    msgs = db.execute(
        """SELECT m.*, rv.decision AS rev_decision, rv.texto_corregido, rv.motivo, rv.fuentes,
                  ue.areas AS rev_areas
           FROM chat_message m LEFT JOIN review_request rq ON rq.message_id=m.id
           LEFT JOIN review rv ON rv.request_id=rq.id LEFT JOIN user_account ue ON ue.id=rv.experto_id
           WHERE m.conversation_id=%s ORDER BY m.created_at""", (cid,)).fetchall()
    out = []
    for r in msgs:
        m = _msg(r)
        if r["rev_decision"]:
            m["revision"] = {"decision": r["rev_decision"], "texto_corregido": r["texto_corregido"], "motivo": r["motivo"],
                             "fuentes": r["fuentes"], "areas": r["rev_areas"]}
        out.append(m)
    return {"id": str(c["id"]), "titulo": c["titulo"], "parcel_id": str(c["parcel_id"]) if c["parcel_id"] else None, "mensajes": out}


@router.post("/mensajes/{mid}/decision")
def decidir(mid: str, body: DecisionChatIn, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> dict[str, Any]:
    """El agricultor decide: acepta, ajusta o descarta una estrategia. Queda en chat_decision y audit_log."""
    if body.decision != "descartar" and body.ranking is None:
        raise HTTPException(422, "Indique qué estrategia (0 = la actual, 1 y 2 = opciones)")
    try:
        m = db.execute(
            """SELECT m.id FROM chat_message m JOIN chat_conversation c ON c.id=m.conversation_id
               WHERE m.id=%s AND c.user_id=%s AND m.rol='asistente'""", (mid, u.id)).fetchone()
    except Exception:  # noqa: BLE001
        db.rollback()
        m = None
    if m is None:
        raise HTTPException(404, "Mensaje no encontrado")
    db.execute("INSERT INTO chat_decision(message_id,user_id,decision,ranking,comentario) VALUES (%s,%s,%s,%s,%s)",
               (mid, u.id, body.decision, body.ranking, body.comentario))
    audit(db, u, "decidir", "chat_message", mid, {"decision": body.decision, "ranking": body.ranking})
    db.commit()
    return {"ok": True, "decision": body.decision}


@router.get("/reportes")
def reportes(u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    """Respuestas ya revisadas por un experto (con respaldo o revocadas)."""
    filas = db.execute(
        """SELECT m.id, m.texto AS respuesta, m.estado_respaldo, m.area, m.idioma, rv.decision, rv.texto_corregido,
                  rv.motivo, rv.fuentes, rv.created_at AS revisado_at,
                  (SELECT q.texto FROM chat_message q WHERE q.conversation_id=m.conversation_id AND q.rol='usuario'
                     AND q.created_at < m.created_at ORDER BY q.created_at DESC LIMIT 1) AS pregunta
           FROM chat_message m JOIN chat_conversation c ON c.id=m.conversation_id
           JOIN review_request rq ON rq.message_id=m.id JOIN review rv ON rv.request_id=rq.id
           WHERE c.user_id=%s ORDER BY rv.created_at DESC""", (u.id,)).fetchall()
    return [{**f, "id": str(f["id"]), "revisado_at": f["revisado_at"].isoformat()} for f in filas]
