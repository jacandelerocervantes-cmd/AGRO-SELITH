"""Cola de solicitudes para expertos: la cola total se subdivide por área de agronomía y solo recibe quien es
experto en esa área; el reparto dentro del área es aleatorio (orden_aleatorio + SKIP LOCKED)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .areas import AREAS
from .auth import Usuario, get_db, requiere
from .deps import audit

router = APIRouter(prefix="/experto", tags=["experto"])
EXPERTO = requiere("extensionista", "admin")


class RevisionIn(BaseModel):
    decision: Literal["confirmar", "corregir", "revocar"]
    texto_corregido: str | None = Field(None, max_length=4000)
    motivo: str | None = Field(None, max_length=1000)
    fuentes: list[Annotated[str, Field(max_length=300)]] = Field(default_factory=list, max_length=10)


def _detalle(db: Any, rid: str) -> dict[str, Any]:
    r = db.execute(
        """SELECT rq.id, rq.area, rq.estado, rq.asignada_a, m.id AS message_id, m.texto AS respuesta, m.contenido,
                  m.idioma, m.sintetico, m.conversation_id,
                  (SELECT q.texto FROM chat_message q WHERE q.conversation_id=m.conversation_id AND q.rol='usuario'
                     AND q.created_at < m.created_at ORDER BY q.created_at DESC LIMIT 1) AS pregunta,
                  (SELECT q.via_voz FROM chat_message q WHERE q.conversation_id=m.conversation_id AND q.rol='usuario'
                     AND q.created_at < m.created_at ORDER BY q.created_at DESC LIMIT 1) AS via_voz,
                  p.nombre AS parcela, p.area_m2::float AS area_m2
           FROM review_request rq JOIN chat_message m ON m.id=rq.message_id
           JOIN chat_conversation c ON c.id=m.conversation_id LEFT JOIN parcel p ON p.id=c.parcel_id
           WHERE rq.id=%s""", (rid,)).fetchone()
    if r is None:
        raise HTTPException(404, "Solicitud no encontrada")
    return {**r, "id": str(r["id"]), "message_id": str(r["message_id"]), "conversation_id": str(r["conversation_id"]),
            "asignada_a": str(r["asignada_a"]) if r["asignada_a"] else None}


@router.get("/perfil")
def perfil(u: Usuario = Depends(EXPERTO)) -> dict[str, Any]:
    return {"nombre": u.nombre, "role": u.role, "areas": list(u.areas)}


@router.get("/cola")
def cola(u: Usuario = Depends(EXPERTO), db: Any = Depends(get_db)) -> dict[str, Any]:
    """Cola total repartida por área, y lo que me toca (solo mis áreas)."""
    por_area = {a: 0 for a in AREAS}
    for r in db.execute("SELECT area, count(*) AS n FROM review_request WHERE estado='pendiente' GROUP BY area").fetchall():
        por_area[r["area"]] = r["n"]
    mias = [str(r["id"]) for r in db.execute(
        "SELECT id FROM review_request WHERE estado='asignada' AND asignada_a=%s ORDER BY asignada_at", (u.id,)).fetchall()]
    return {"areas_totales": por_area, "mis_areas": list(u.areas),
            "pendientes_mis_areas": sum(por_area[a] for a in u.areas), "asignadas_a_mi": mias}


@router.post("/cola/siguiente")
def siguiente(u: Usuario = Depends(EXPERTO), db: Any = Depends(get_db)) -> dict[str, Any]:
    """Asigna al azar la siguiente solicitud de MIS áreas (si ya tengo una sin revisar, esa primero)."""
    if not u.areas:
        raise HTTPException(403, "No tiene áreas de especialidad asignadas")
    previa = db.execute(
        "SELECT id FROM review_request WHERE estado='asignada' AND asignada_a=%s ORDER BY asignada_at LIMIT 1", (u.id,)).fetchone()
    if previa:
        return _detalle(db, str(previa["id"]))
    r = db.execute(
        """UPDATE review_request SET estado='asignada', asignada_a=%s, asignada_at=now()
           WHERE id = (SELECT id FROM review_request WHERE estado='pendiente' AND area = ANY(%s)
                       ORDER BY orden_aleatorio LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING id""",
        (u.id, list(u.areas))).fetchone()
    if r is None:
        db.rollback()
        return {"vacia": True}
    audit(db, u, "tomar_solicitud", "review_request", str(r["id"]), {})
    db.commit()
    return _detalle(db, str(r["id"]))


@router.get("/solicitudes/{rid}")
def solicitud(rid: str, u: Usuario = Depends(EXPERTO), db: Any = Depends(get_db)) -> dict[str, Any]:
    d = _detalle(db, rid)
    if d["asignada_a"] != u.id and u.role != "admin":
        raise HTTPException(403, "Esta solicitud no se le asignó")
    return d


@router.post("/solicitudes/{rid}/revision")
def revisar(rid: str, body: RevisionIn, u: Usuario = Depends(EXPERTO), db: Any = Depends(get_db)) -> dict[str, Any]:
    d = _detalle(db, rid)
    if d["asignada_a"] != u.id:
        raise HTTPException(403, "Esta solicitud no se le asignó")
    if d["estado"] != "asignada":
        raise HTTPException(409, "La solicitud ya fue revisada")
    if body.decision == "corregir" and not (body.texto_corregido or "").strip():
        raise HTTPException(422, "Escriba la respuesta corregida")
    if body.decision == "revocar" and not (body.motivo or "").strip():
        raise HTTPException(422, "Indique el motivo de la revocación")
    db.execute(
        "INSERT INTO review(request_id,experto_id,decision,texto_corregido,motivo,fuentes) VALUES (%s,%s,%s,%s,%s,%s)",
        (rid, u.id, body.decision, body.texto_corregido, body.motivo, json.dumps(body.fuentes)))
    db.execute("UPDATE review_request SET estado='revisada' WHERE id=%s", (rid,))
    estado = "revocada" if body.decision == "revocar" else "con_respaldo"
    db.execute("UPDATE chat_message SET estado_respaldo=%s WHERE id=%s", (estado, d["message_id"]))
    if body.decision == "revocar":
        aviso = (f"Respuesta revocada por un experto en {d['area']}: {body.motivo}" if d["idioma"] == "es"
                 else f"Answer revoked by an expert in {d['area']}: {body.motivo}")
        db.execute("INSERT INTO chat_message(conversation_id,rol,texto,idioma,area,contenido) VALUES (%s,'sistema',%s,%s,%s,%s)",
                   (d["conversation_id"], aviso, d["idioma"], d["area"], json.dumps({"revoca": d["message_id"]})))
    audit(db, u, "revisar", "review_request", rid, {"decision": body.decision, "area": d["area"]})
    db.commit()
    return {"ok": True, "estado_respaldo": estado}


@router.get("/corpus")
def corpus(u: Usuario = Depends(EXPERTO), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    """Pares pregunta/respuesta revisados por expertos: la base del modelo agronómico y del benchmark.
    Solo incluye preguntas con consentimiento de uso (o sintéticas, rotuladas)."""
    filas = db.execute(
        """SELECT rq.area, rv.decision, rv.texto_corregido, rv.fuentes, m.texto AS respuesta_ia, m.idioma, m.sintetico,
                  (SELECT q.texto FROM chat_message q WHERE q.conversation_id=m.conversation_id AND q.rol='usuario'
                     AND q.created_at < m.created_at ORDER BY q.created_at DESC LIMIT 1) AS pregunta,
                  (SELECT q.consentimiento_uso FROM chat_message q WHERE q.conversation_id=m.conversation_id AND q.rol='usuario'
                     AND q.created_at < m.created_at ORDER BY q.created_at DESC LIMIT 1) AS consentimiento
           FROM review rv JOIN review_request rq ON rq.id=rv.request_id JOIN chat_message m ON m.id=rq.message_id
           ORDER BY rv.created_at""").fetchall()
    return [f for f in filas if f["consentimiento"] or f["sintetico"]]
