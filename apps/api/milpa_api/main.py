"""API del sistema. Uso: uvicorn milpa_api.main:app --app-dir apps/api"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException
from milpa_engine import Motor
from milpa_engine.knowledge import PESOS_DEFECTO, construir_problema
from pydantic import BaseModel, Field

from .auth import Usuario, get_db, requiere, usuario_actual
from .config import ROOT, conocimiento, llm_config, modo_demo

sys.path.insert(0, str(Path(ROOT) / "pipelines"))
from .llm import Asistente
from .seguridad import CabecerasSeguras

app = FastAPI(title="API del sistema de apoyo a la decisión (milpa)", version="0.1.0")
TODOS = ("agricultor", "extensionista", "admin")
app.add_middleware(CabecerasSeguras)
BASE = "milpa_tradicional"

# Prioridades del productor (0-5, 3 = pesos por defecto) -> pesos del motor.
# Mapeo PROVISIONAL: lo calibra y valida el experto.
GRUPOS = {
    "agua": ("agua_eficiencia", "proteccion_etapas"),
    "forraje": ("valor_forrajero",),
    "suelo": ("fijacion_n", "materia_organica", "control_erosion", "infiltracion"),
    "ingreso": ("ingreso_neto", "estabilidad_ingreso"),
}


class Prioridades(BaseModel):
    agua: int = Field(3, ge=0, le=5)
    forraje: int = Field(3, ge=0, le=5)
    suelo: int = Field(3, ge=0, le=5)
    ingreso: int = Field(3, ge=0, le=5)


def pesos_desde(p: Prioridades) -> dict[str, float]:
    pesos = dict(PESOS_DEFECTO)
    for grupo, criterios in GRUPOS.items():
        for c in criterios:
            pesos[c] = PESOS_DEFECTO[c] * getattr(p, grupo) / 3
    return pesos


class RecomendacionIn(BaseModel):
    parcel_id: str
    escenario: Literal["normal", "canicula_prolongada", "temporal_tardio", "huracan"] = "normal"
    horizonte_anios: int = Field(4, ge=3, le=5)
    prioridades: Prioridades = Field(default_factory=lambda: Prioridades(agua=3, forraje=3, suelo=3, ingreso=3))


class DecisionIn(BaseModel):
    run_id: str
    plan_id: str | None = None
    decision: Literal["aceptar", "ajustar", "descartar"]
    comentario: str | None = None


class PreguntaIn(BaseModel):
    texto: str = Field(min_length=3)
    consentimiento_uso: bool = False
    run_id: str | None = None
    parcel_id: str | None = None


class ItemBenchmarkIn(BaseModel):
    question_id: str
    categoria: Literal["agua", "suelo", "plagas", "mercado", "calendario", "canicula", "milpa", "saber_local", "otra"]
    split: Literal["benchmark", "entrenamiento", "desarrollo"]
    respuesta_referencia: str | None = None
    rubrica: list[str] = []


def _audit(db: Any, u: Usuario, accion: str, entidad: str, entidad_id: str, detalle: dict) -> None:
    db.execute(
        "INSERT INTO audit_log(user_id,accion,entidad,entidad_id,detalle) VALUES (%s,%s,%s,%s,%s)",
        (u.id, accion, entidad, entidad_id, json.dumps(detalle)),
    )


@app.get("/salud")
def salud() -> dict[str, Any]:
    return {"ok": True, "modo_demo": modo_demo()}


@app.get("/referencia/validacion")
def validacion_eeuu() -> dict[str, Any]:
    """Métricas reales de validación con datos de EE. UU. (generadas por pipelines.validacion_eeuu)."""
    f = Path(__file__).resolve().parents[3] / "docs" / "validacion_eeuu.json"
    if not f.exists():
        raise HTTPException(404, "sin reporte de validación")
    return dict(json.loads(f.read_text(encoding="utf-8")))


@app.get("/demo/usuarios")
def demo_usuarios(db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    if not modo_demo():
        raise HTTPException(404)
    return db.execute(
        "SELECT demo_login, role, nombre, areas FROM user_account WHERE es_demo AND demo_login <> 'demo-productor-sintetico' ORDER BY role, demo_login"
    ).fetchall()


@app.get("/escenarios")
def escenarios(_: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    return db.execute("SELECT clave, nombre, parametros FROM scenario ORDER BY clave").fetchall()


@app.get("/parcelas")
def parcelas(u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    sql = (
        "SELECT p.id::text AS id, p.nombre, p.area_ha::float AS area_ha, ST_AsGeoJSON(p.geom)::json AS geom "
        "FROM parcel p JOIN farm f ON f.id=p.farm_id"
    )
    if u.role == "agricultor":
        return db.execute(sql + " WHERE f.owner_id=%s ORDER BY p.nombre", (u.id,)).fetchall()
    return db.execute(sql + " ORDER BY p.nombre").fetchall()


@app.get("/vulnerabilidad")
def vulnerabilidad(
    escenario: str = "normal", u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)
) -> dict[str, Any]:
    """Exposición a canícula del plan base por parcela. Hoy es igual para todas (falta suelo, F3)."""
    k = conocimiento()
    esc = k.escenarios.get(escenario)
    if esc is None:
        raise HTTPException(404, "Escenario desconocido")
    base = next(o for o in k.opciones if o.id == BASE)
    indice = base.sensibilidad_canicula * esc.severidad_canicula
    nivel = "ok" if indice < 0.25 else "mid" if indice < 0.5 else "bad"
    ps = parcelas(u, db)
    return {
        "escenario": escenario, "indice": indice, "nivel": nivel, "provisional": True,
        "nota": "Igual para todas las parcelas hasta cargar suelo y clima por parcela (F3).",
        "parcelas": [{"parcel_id": p["id"], "indice": indice, "nivel": nivel} for p in ps],
    }


def _parcela_accesible(db: Any, u: Usuario, parcel_id: str) -> dict[str, Any]:
    try:
        r = db.execute(
            "SELECT p.id, p.area_ha::float AS area_ha, f.owner_id FROM parcel p JOIN farm f ON f.id=p.farm_id WHERE p.id=%s",
            (parcel_id,),
        ).fetchone()
    except psycopg.errors.InvalidTextRepresentation:
        db.rollback()
        r = None
    if r is None or (u.role == "agricultor" and str(r["owner_id"]) != u.id):
        raise HTTPException(404, "Parcela no encontrada")
    return r


@app.post("/recomendaciones")
def recomendar(
    body: RecomendacionIn, u: Usuario = Depends(requiere(*TODOS)), db: Any = Depends(get_db)
) -> dict[str, Any]:
    return _recomendar(db, u, body)


def _recomendar(db: Any, u: Usuario, body: RecomendacionIn) -> dict[str, Any]:
    parcela = _parcela_accesible(db, u, body.parcel_id)
    k = conocimiento()
    prob = construir_problema(
        k, body.escenario, body.horizonte_anios, BASE, parcela["area_ha"], pesos_desde(body.prioridades)
    )
    planes = Motor(prob).recomendar()
    por_id = {o.id: o for o in k.opciones}
    mv = db.execute("SELECT id FROM model_version WHERE nombre='conocimiento-inicial'").fetchone()
    esc = db.execute("SELECT id FROM scenario WHERE clave=%s", (body.escenario,)).fetchone()
    run = db.execute(
        """INSERT INTO recommendation_run(parcel_id,user_id,model_version_id,scenario_id,prioridades,limites,horizonte_anios)
           VALUES (%s,%s,%s,%s,%s,'{}',%s) RETURNING id""",
        (body.parcel_id, u.id, mv["id"], esc["id"], body.prioridades.model_dump_json(), body.horizonte_anios),
    ).fetchone()
    run_id = str(run["id"])
    agua_base = por_id[BASE].agua_mm * prob.escenario.factor_demanda_agua * prob.n_slots
    salida = []
    for pl in planes:
        pid = str(db.execute(
            """INSERT INTO recommendation_plan(run_id,ranking,score,score_p10,score_p90,agua_total_mm,
                 ingreso_estimado,delta_mo,delta_n,riesgo_plaga) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (run_id, pl.ranking, pl.score, pl.score_p10, pl.score_p90, pl.agua_total_mm,
             pl.ingreso_estimado, pl.delta_mo, pl.delta_n, pl.riesgo_plaga),
        ).fetchone()["id"])
        for i, cid in enumerate(pl.secuencia):
            db.execute(
                "INSERT INTO plan_step(plan_id,anio,ciclo,crop_id,es_barbecho) VALUES (%s,%s,'temporal',%s,%s)",
                (pid, i + 1, cid, por_id[cid].es_barbecho),
            )
        for f in pl.factores:
            db.execute(
                "INSERT INTO recommendation_factor VALUES (%s,%s,%s,%s,%s,%s)",
                (pid, f.factor, f.valor_norm, f.peso, f.contribucion, f.explicacion),
            )
        top = [f.explicacion.split(":")[0] for f in sorted(pl.factores, key=lambda f: -f.contribucion)[:2]]
        salida.append({
            "plan_id": pid, "ranking": pl.ranking, "score": pl.score,
            "score_p10": pl.score_p10, "score_p50": pl.score_p50, "score_p90": pl.score_p90,
            "agua_total_mm": pl.agua_total_mm, "agua_base_mm": agua_base,
            "ingreso_estimado": pl.ingreso_estimado, "delta_mo": pl.delta_mo, "delta_n": pl.delta_n,
            "riesgo_plaga": pl.riesgo_plaga,
            "pasos": [{"anio": i + 1, "crop_id": c, "nombre": por_id[c].nombre, "es_barbecho": por_id[c].es_barbecho}
                      for i, c in enumerate(pl.secuencia)],
            "por_que": "Aporta sobre todo en: " + " y ".join(t.lower() for t in top) + ".",
            "factores": [{"factor": f.factor, "valor_norm": f.valor_norm, "peso": f.peso,
                          "contribucion": f.contribucion, "explicacion": f.explicacion} for f in pl.factores],
        })
    _audit(db, u, "recomendar", "recommendation_run", run_id, {"escenario": body.escenario})
    db.commit()
    return {"run_id": run_id, "escenario": body.escenario, "datos_provisionales": True, "planes": salida}


@app.post("/decisiones")
def decidir(
    body: DecisionIn, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)
) -> dict[str, Any]:
    if body.decision != "descartar" and not body.plan_id:
        raise HTTPException(422, "Aceptar o ajustar requiere plan_id")
    try:
        run = db.execute("SELECT user_id FROM recommendation_run WHERE id=%s", (body.run_id,)).fetchone()
    except psycopg.errors.InvalidTextRepresentation:
        db.rollback()
        run = None
    if run is None or str(run["user_id"]) != u.id:
        raise HTTPException(404, "Corrida no encontrada")
    if body.plan_id and not db.execute(
        "SELECT 1 FROM recommendation_plan WHERE id=%s AND run_id=%s", (body.plan_id, body.run_id)
    ).fetchone():
        raise HTTPException(422, "El plan no pertenece a la corrida")
    db.execute(
        "INSERT INTO farmer_decision(run_id,plan_id,decision,comentario) VALUES (%s,%s,%s,%s)",
        (body.run_id, body.plan_id, body.decision, body.comentario),
    )
    _audit(db, u, "decidir", "recommendation_run", body.run_id,
           {"decision": body.decision, "plan_id": body.plan_id})
    db.commit()
    return {"ok": True, "decision": body.decision}


@app.post("/preguntas")
def preguntar(
    body: PreguntaIn, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)
) -> dict[str, Any]:
    contexto: dict[str, Any] = {"datos_provisionales": True}
    if body.run_id:
        planes = db.execute(
            """SELECT p.ranking, p.score::float, p.agua_total_mm::float,
                      (SELECT array_agg(crop_id ORDER BY anio) FROM plan_step s WHERE s.plan_id=p.id) AS pasos
               FROM recommendation_plan p JOIN recommendation_run r ON r.id=p.run_id
               WHERE r.id=%s AND r.user_id=%s ORDER BY p.ranking""",
            (body.run_id, u.id),
        ).fetchall()
        contexto["planes"] = planes
    r = Asistente(llm_config()).responder(body.texto, contexto)
    q = db.execute(
        """INSERT INTO producer_question(user_id,parcel_id,run_id,texto,contexto,origen,consentimiento_uso,
             consentimiento_at,sintetico) VALUES (%s,%s,%s,%s,%s,'app',%s,CASE WHEN %s THEN now() END,%s) RETURNING id""",
        (u.id, body.parcel_id, body.run_id, body.texto, json.dumps(contexto, default=str),
         body.consentimiento_uso, body.consentimiento_uso, False),
    ).fetchone()
    _audit(db, u, "preguntar", "producer_question", str(q["id"]),
           {"consentimiento_uso": body.consentimiento_uso, "origen_respuesta": r.origen, "modelo": r.modelo})
    db.commit()
    return {"pregunta_id": str(q["id"]),
            "respuesta": {"texto": r.texto, "modelo": r.modelo, "origen": r.origen, "sintetico": r.sintetico}}


EXPERTOS = requiere("extensionista", "admin")


@app.get("/experto/parametros")
def experto_parametros(_: Usuario = Depends(EXPERTOS), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    return db.execute(
        "SELECT crop_id, agua_mm_ciclo::float, tolerancia_sequia, fuente, estatus FROM crop_param ORDER BY crop_id"
    ).fetchall()


@app.get("/experto/bitacora")
def experto_bitacora(_: Usuario = Depends(EXPERTOS), db: Any = Depends(get_db)) -> list[dict[str, Any]]:
    return db.execute(
        "SELECT id, user_id::text, accion, entidad, entidad_id, detalle, at FROM audit_log ORDER BY id DESC LIMIT 100"
    ).fetchall()


@app.post("/experto/benchmark/items")
def promover_item(
    body: ItemBenchmarkIn, u: Usuario = Depends(EXPERTOS), db: Any = Depends(get_db)
) -> dict[str, Any]:
    try:
        q = db.execute("SELECT texto FROM producer_question WHERE id=%s", (body.question_id,)).fetchone()
    except psycopg.errors.InvalidTextRepresentation:
        db.rollback()
        q = None
    if q is None:
        raise HTTPException(404, "Pregunta no encontrada")
    h = hashlib.sha256(" ".join(q["texto"].lower().split()).encode()).hexdigest()
    try:
        r = db.execute(
            """INSERT INTO benchmark_item(question_id,texto,texto_hash,categoria,split,respuesta_referencia,rubrica)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.question_id, q["texto"], h, body.categoria, body.split, body.respuesta_referencia,
             json.dumps(body.rubrica)),
        ).fetchone()
    except psycopg.errors.RaiseException as e:
        db.rollback()
        raise HTTPException(409, "La pregunta no tiene consentimiento de uso") from e
    except psycopg.errors.UniqueViolation as e:
        db.rollback()
        raise HTTPException(409, "Pregunta ya incluida en el benchmark") from e
    _audit(db, u, "promover_benchmark", "benchmark_item", str(r["id"]), {"split": body.split})
    db.commit()
    return {"item_id": str(r["id"]), "estatus": "provisional"}


# ---- Sincronización de lo hecho sin señal ----
class ItemSync(BaseModel):
    client_id: str
    tipo: Literal["decision", "pregunta"]
    creado_at: datetime
    parcel_id: str
    escenario: Literal["normal", "canicula_prolongada", "temporal_tardio", "huracan"] = "normal"
    prioridades: Prioridades = Field(default_factory=lambda: Prioridades(agua=3, forraje=3, suelo=3, ingreso=3))
    horizonte_anios: int = Field(4, ge=3, le=5)
    ranking: int | None = Field(None, ge=1, le=3)
    decision: Literal["aceptar", "ajustar", "descartar"] | None = None
    comentario: str | None = None
    texto: str | None = None
    consentimiento_uso: bool = False


class SyncIn(BaseModel):
    items: list[ItemSync] = Field(max_length=200)


def _uuid_valido(x: str) -> bool:
    try:
        UUID(x)
    except ValueError:
        return False
    return True


@app.post("/sincronizar")
def sincronizar(
    body: SyncIn, u: Usuario = Depends(requiere("agricultor")), db: Any = Depends(get_db)
) -> dict[str, Any]:
    """Aplica en orden lo que el productor hizo sin señal. Idempotente por client_id.
    Las decisiones se re-calculan con el motor (determinista) para dejar el plan en la base."""
    resultados: list[dict[str, Any]] = []
    for it in sorted(body.items, key=lambda i: i.creado_at):
        if not _uuid_valido(it.client_id):
            resultados.append({"client_id": it.client_id, "estado": "error", "detalle": "client_id inválido"})
            continue
        tabla = "farmer_decision" if it.tipo == "decision" else "producer_question"
        if db.execute(f"SELECT 1 FROM {tabla} WHERE client_id=%s", (it.client_id,)).fetchone():
            resultados.append({"client_id": it.client_id, "estado": "duplicado"})
            continue
        try:
            if it.tipo == "decision":
                if it.decision is None or (it.decision != "descartar" and it.ranking is None):
                    raise HTTPException(422, "Decisión incompleta")
                rec = _recomendar(db, u, RecomendacionIn(
                    parcel_id=it.parcel_id, escenario=it.escenario,
                    horizonte_anios=it.horizonte_anios, prioridades=it.prioridades))
                plan_id = None
                if it.decision != "descartar":
                    assert it.ranking is not None
                    if it.ranking > len(rec["planes"]):
                        raise HTTPException(422, "Plan inexistente")
                    plan_id = rec["planes"][it.ranking - 1]["plan_id"]
                db.execute(
                    """INSERT INTO farmer_decision(run_id,plan_id,decision,comentario,decidido_at,client_id,offline)
                       VALUES (%s,%s,%s,%s,%s,%s,true)""",
                    (rec["run_id"], plan_id, it.decision, it.comentario, it.creado_at, it.client_id),
                )
                _audit(db, u, "decidir", "recommendation_run", rec["run_id"],
                       {"decision": it.decision, "plan_id": plan_id, "offline": True, "client_id": it.client_id})
                resultados.append({"client_id": it.client_id, "estado": "ok", "run_id": rec["run_id"]})
            else:
                if not it.texto or len(it.texto.strip()) < 3:
                    raise HTTPException(422, "Pregunta vacía")
                r = Asistente(llm_config()).responder(it.texto, {"datos_provisionales": True})
                q = db.execute(
                    """INSERT INTO producer_question(user_id,parcel_id,texto,contexto,origen,consentimiento_uso,
                         consentimiento_at,created_at,client_id,offline)
                       VALUES (%s,%s,%s,%s,'app',%s,CASE WHEN %s THEN %s END,%s,%s,true) RETURNING id""",
                    (u.id, it.parcel_id, it.texto, json.dumps({"datos_provisionales": True}),
                     it.consentimiento_uso, it.consentimiento_uso, it.creado_at, it.creado_at, it.client_id),
                ).fetchone()
                _audit(db, u, "preguntar", "producer_question", str(q["id"]),
                       {"offline": True, "client_id": it.client_id, "origen_respuesta": r.origen})
                db.commit()
                resultados.append({"client_id": it.client_id, "estado": "ok", "respuesta": {
                    "texto": r.texto, "modelo": r.modelo, "origen": r.origen, "sintetico": r.sintetico}})
                continue
            db.commit()
        except HTTPException as e:
            db.rollback()
            resultados.append({"client_id": it.client_id, "estado": "error", "detalle": e.detail})
    return {"resultados": resultados}


# ---- Datos conocidos de una parcela (fusión F3) ----
@app.get("/parcelas/{parcel_id}/contexto")
def contexto_parcela(
    parcel_id: str, u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)
) -> dict[str, Any]:
    from milpa_pipelines import fusion  # import diferido: depende de shapely/pyproj
    from milpa_pipelines.conectores import StacSentinel

    _parcela_accesible(db, u, parcel_id)
    celda = db.execute(
        "SELECT cell_id FROM parcel_cell WHERE parcel_id=%s ORDER BY peso DESC LIMIT 1", (parcel_id,)
    ).fetchone()
    clima: dict[str, Any] | None = None
    if celda:
        filas = db.execute(
            """SELECT to_char(fecha,'YYYY-MM-DD') AS fecha, precip_mm::float, precip_sd::float, tmax::float, tmin::float
               FROM climate_daily WHERE cell_id=%s ORDER BY fecha""",
            (celda["cell_id"],),
        ).fetchall()
        if filas:
            clima = {
                "periodo": [filas[0]["fecha"], filas[-1]["fecha"]], "dias": len(filas),
                "precip_total_mm": sum(f["precip_mm"] or 0 for f in filas),
                "precip_sd_medio_mm": sum(f["precip_sd"] or 0 for f in filas) / len(filas),
                "racha_seca_max_dias_jul_ago": fusion.racha_seca_max(filas),
                "fuente": "fusion(POWER,ERA5)",
                "nota": "Sin estaciones SMN/CONAGUA ni CEM: el campo es igual para todas las parcelas.",
            }
    suelo = db.execute(
        "SELECT fuente, ph::float, incertidumbre, sintetico FROM parcel_soil WHERE parcel_id=%s ORDER BY fecha DESC LIMIT 1",
        (parcel_id,),
    ).fetchone()
    esc = StacSentinel(modo="demo").obtener(bbox=[-88.19, 21.10, -88.11, 21.18], inicio="2023-06-01", fin="2023-08-31")
    return {
        "clima": clima, "suelo": suelo,
        "vegetacion": {"disponibilidad_optica": fusion.disponibilidad_optica(esc.datos), "origen": esc.origen},
    }


# ---- Routers del producto: parcela dibujada, chat, capas NASA y cola de expertos ----
from . import capas as r_capas  # noqa: E402
from . import chat as r_chat  # noqa: E402
from . import expertos as r_expertos  # noqa: E402
from . import parcelas as r_parcelas  # noqa: E402

for _router in (r_parcelas.router, r_capas.router, r_chat.router, r_expertos.router):
    app.include_router(_router)
