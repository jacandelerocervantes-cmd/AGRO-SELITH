"""Siembra idempotente de la base agronómica (knowledge/*.yaml -> PostgreSQL).

Uso: uv run python apps/api/seed.py [knowledge] (lee DATABASE_URL)
Conserva fuente/estatus de cada parámetro; lo que no se conoce queda NULL (nunca inventado).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages" / "engine" / "src"))
from milpa_engine.knowledge import PESOS_DEFECTO

COBERTURA = {"cobertura", "abono_verde"}
MODELO = "conocimiento-inicial"
DEMO_USUARIOS = [
    ("demo-agricultor", "agricultor", "Productor de prueba", []),
    ("demo-extensionista", "extensionista", "Extensionista de prueba", ["suelos", "cultivos"]),
    ("demo-admin", "admin", "Administrador de prueba", []),
    # Expertos de prueba, uno por área de agronomía (la landing elige la especialidad)
    ("demo-experto-suelos", "extensionista", "Experto en suelos (prueba)", ["suelos"]),
    ("demo-experto-patogenos", "extensionista", "Experto en patógenos (prueba)", ["patogenos"]),
    ("demo-experto-agua", "extensionista", "Experto en agua (prueba)", ["agua"]),
    ("demo-experto-clima", "extensionista", "Experto en clima (prueba)", ["clima"]),
    ("demo-experto-mercado", "extensionista", "Experto en mercado (prueba)", ["mercado"]),
    ("demo-experto-cultivos", "extensionista", "Experto en cultivos (prueba)", ["cultivos"]),
]
# Solicitudes sintéticas para poblar la cola del experto (SINTÉTICAS: no son preguntas reales)
COLA_SINTETICA = [
    ("suelos", "¿Cómo mejoro un suelo pedregoso y poco profundo?", "How can I improve a shallow, stony soil?"),
    ("suelos", "¿El abono verde de mucuna sirve en suelo rojo (k'ankab)?", "Does velvet-bean green manure work in red soil?"),
    ("suelos", "¿Cuánto tarda en recuperarse un acahual de 3 años?", "How long does a 3-year fallow take to recover?"),
    ("patogenos", "¿Puedo sembrar chile después de chile?", "Can I plant chili after chili?"),
    ("patogenos", "Mi frijol tiene manchas en las hojas, ¿qué es?", "My beans have leaf spots, what is it?"),
    ("agua", "¿Cómo protejo la floración si la canícula dura mucho?", "How do I protect flowering if the dry spell is long?"),
    ("agua", "¿Cuándo sembrar si la lluvia llega tarde?", "When should I plant if the rains come late?"),
    ("clima", "¿Qué tan seguido hay canícula larga en mi zona?", "How often is there a long dry spell in my area?"),
    ("clima", "¿Un huracán puede arruinar el ciclo de invierno?", "Can a hurricane ruin the winter cycle?"),
    ("mercado", "¿Hay mercado para la calabaza de pepita cerca?", "Is there a nearby market for pumpkin seed?"),
    ("mercado", "¿Conviene sembrar más frijol xpelón este año?", "Is it worth planting more xpelón bean this year?"),
    ("cultivos", "¿Qué variedad criolla de maíz es de ciclo corto?", "Which native maize variety has a short cycle?"),
]


def _yamls(raiz: Path, sub: str) -> list[dict[str, Any]]:
    return [yaml.safe_load(f.read_text(encoding="utf-8")) or {} for f in sorted((raiz / sub).glob("*.yaml"))]


def _valor(p: dict[str, Any], k: str) -> Any:
    return p[k]["valor"] if k in p else None


def _sembrar_cola(cur: psycopg.Cursor) -> None:
    """Productor sintético + preguntas sintéticas con respuesta 'solo IA' en cola (idempotente)."""
    cur.execute(
        """INSERT INTO user_account(demo_login,es_demo,role,nombre) VALUES ('demo-productor-sintetico',true,'agricultor','Productor sintético')
           ON CONFLICT (demo_login) DO NOTHING"""
    )
    u = cur.execute("SELECT id FROM user_account WHERE demo_login='demo-productor-sintetico'").fetchone()
    assert u is not None
    if cur.execute("SELECT 1 FROM chat_conversation WHERE user_id=%s", (u[0],)).fetchone():
        return
    conv = cur.execute(
        "INSERT INTO chat_conversation(user_id,titulo) VALUES (%s,'Preguntas sintéticas') RETURNING id", (u[0],)
    ).fetchone()
    assert conv is not None
    for area, es, en in COLA_SINTETICA:
        for texto, idioma in ((es, "es"), (en, "en")):
            m = cur.execute(
                """INSERT INTO chat_message(conversation_id,rol,texto,idioma,area,sintetico) VALUES (%s,'usuario',%s,%s,%s,true)
                   RETURNING id""", (conv[0], texto, idioma, area)).fetchone()
            assert m is not None
            r = cur.execute(
                """INSERT INTO chat_message(conversation_id,rol,texto,idioma,estado_respaldo,area,sintetico,contenido)
                   VALUES (%s,'asistente',%s,%s,'solo_ia',%s,true,%s) RETURNING id""",
                (conv[0], "Respuesta de ejemplo del asistente (sintética)." if idioma == "es"
                 else "Example assistant answer (synthetic).", idioma, area,
                 json.dumps({"sintetico": True, "pregunta": texto})),
            ).fetchone()
            assert r is not None
            cur.execute("INSERT INTO review_request(message_id,area) VALUES (%s,%s)", (r[0], area))


def sembrar(conn: psycopg.Connection, raiz: Path) -> dict[str, int]:
    cur = conn.cursor()
    row = cur.execute("SELECT id FROM model_version WHERE nombre=%s", (MODELO,)).fetchone()
    if row is None:
        row = cur.execute(
            "INSERT INTO model_version(nombre,pesos,estado) VALUES (%s,%s,'borrador') RETURNING id",
            (MODELO, json.dumps(PESOS_DEFECTO)),
        ).fetchone()
    assert row is not None
    version = row[0]
    n = {"crop": 0, "rule": 0, "scenario": 0, "market": 0}

    for sub in ("crops", "milpa"):
        for doc in _yamls(raiz, sub):
            for o in doc.get("opciones", []):
                fams, tipo = o.get("familias", []), o.get("tipo", [])
                cur.execute(
                    """INSERT INTO crop(id,nombre,familia_botanica,familias,tipo,es_asociacion,es_barbecho,fija_n,cobertura)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET nombre=EXCLUDED.nombre, familia_botanica=EXCLUDED.familia_botanica,
                         familias=EXCLUDED.familias, tipo=EXCLUDED.tipo, es_asociacion=EXCLUDED.es_asociacion,
                         es_barbecho=EXCLUDED.es_barbecho, fija_n=EXCLUDED.fija_n, cobertura=EXCLUDED.cobertura""",
                    (o["id"], o["nombre"], fams[0] if fams else None, fams, tipo,
                     "policultivo" in tipo, o["es_barbecho"], "fabaceae" in fams, bool(COBERTURA & set(tipo))),
                )
                p = o["parametros"]
                todos = {**p, **{f"u_{k}": v for k, v in o["utilidades"].items()}}
                estatus = "validado" if all(v["estatus"] == "validado" for v in todos.values()) else "provisional"
                fuente = "; ".join(sorted({v["fuente"] for v in todos.values()}))
                cur.execute(
                    """INSERT INTO crop_param(crop_id,version_id,agua_mm_ciclo,tolerancia_sequia,n_aporte_kg_ha,
                         mo_aporte,sensibilidad_canicula,ingreso_ref_mxn_ha,parametros,fuente,estatus)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (crop_id,version_id) DO UPDATE SET agua_mm_ciclo=EXCLUDED.agua_mm_ciclo,
                         tolerancia_sequia=EXCLUDED.tolerancia_sequia, n_aporte_kg_ha=EXCLUDED.n_aporte_kg_ha,
                         mo_aporte=EXCLUDED.mo_aporte, sensibilidad_canicula=EXCLUDED.sensibilidad_canicula,
                         ingreso_ref_mxn_ha=EXCLUDED.ingreso_ref_mxn_ha, parametros=EXCLUDED.parametros,
                         fuente=EXCLUDED.fuente, estatus=EXCLUDED.estatus""",
                    (o["id"], version, _valor(p, "agua_mm_ciclo"), _valor(p, "tolerancia_sequia"),
                     _valor(p, "n_aporte_kg_ha"), _valor(p, "mo_aporte"), _valor(p, "sensibilidad_canicula"),
                     _valor(p, "ingreso_ref_mxn_ha"), json.dumps(todos), fuente, estatus),
                )
                n["crop"] += 1

    for doc in _yamls(raiz, "rules"):
        for r in doc.get("rules", []):
            cur.execute(
                """INSERT INTO rotation_rule(id,tipo,crop_a,crop_b,anios_min,severidad,descripcion,fuente,estatus)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO UPDATE SET tipo=EXCLUDED.tipo, crop_a=EXCLUDED.crop_a, crop_b=EXCLUDED.crop_b,
                     anios_min=EXCLUDED.anios_min, severidad=EXCLUDED.severidad, descripcion=EXCLUDED.descripcion,
                     fuente=EXCLUDED.fuente, estatus=EXCLUDED.estatus""",
                (r["id"], r["tipo"], r["selector_a"], r["selector_b"], r["anios_min"], r["severidad"],
                 r.get("descripcion"), r["fuente"], r["estatus"]),
            )
            n["rule"] += 1

    for doc in _yamls(raiz, "scenarios"):
        for e in doc.get("escenarios", []):
            tipo = "base" if e["id"] == "normal" else e["id"]
            cur.execute(
                """INSERT INTO scenario(clave,nombre,tipo,parametros) VALUES (%s,%s,%s,%s)
                   ON CONFLICT (clave) DO UPDATE SET nombre=EXCLUDED.nombre, parametros=EXCLUDED.parametros""",
                (e["id"], e["nombre"], tipo, json.dumps(e["parametros"])),
            )
            n["scenario"] += 1

    for doc in _yamls(raiz, "market"):
        for m in doc.get("mercado", []):
            cap = m["parametros"]["capacidad_absorcion_ha"]
            cur.execute(
                """INSERT INTO market_balance(crop_id,region,anio,capacidad_absorcion_ha,fuente,sintetico)
                   VALUES (%s,'Tizimín',2025,%s,%s,%s)
                   ON CONFLICT (crop_id,region,anio) DO UPDATE SET capacidad_absorcion_ha=EXCLUDED.capacidad_absorcion_ha,
                     fuente=EXCLUDED.fuente, sintetico=EXCLUDED.sintetico""",
                (m["opcion_id"], cap["valor"], cap["fuente"], m["sintetico"]),
            )
            n["market"] += 1
    # Usuarios de PRUEBA para la demo: sin correo ni contraseña; el rol se elige en pantalla.
    for login, rol, nombre, areas in DEMO_USUARIOS:
        cur.execute(
            """INSERT INTO user_account(demo_login,es_demo,role,nombre,areas) VALUES (%s,true,%s,%s,%s)
               ON CONFLICT (demo_login) DO UPDATE SET role=EXCLUDED.role, nombre=EXCLUDED.nombre,
                 areas=EXCLUDED.areas""",
            (login, rol, nombre, areas),
        )
    _sembrar_cola(cur)
    n["demo_users"] = len(DEMO_USUARIOS)
    # Parcelas de prueba del productor demo (cuadrados de ~400 m cerca de Tizimín; SINTÉTICAS).
    dueno = cur.execute("SELECT id FROM user_account WHERE demo_login='demo-agricultor'").fetchone()
    assert dueno is not None
    finca = cur.execute(
        "SELECT id FROM farm WHERE owner_id=%s AND nombre='Finca de prueba'", (dueno[0],)
    ).fetchone() or cur.execute(
        "INSERT INTO farm(owner_id,nombre,municipio_cve) VALUES (%s,'Finca de prueba','31096') RETURNING id",
        (dueno[0],),
    ).fetchone()
    assert finca is not None
    lon0, lat0, d = -88.1503, 21.1427, 0.004
    for i, nombre in enumerate(("Mi milpa", "El monte", "Norte", "Sur")):
        x, y = lon0 + (i % 2) * d * 1.2, lat0 + (i // 2) * d * 1.2
        wkt = f"POLYGON(({x} {y},{x + d} {y},{x + d} {y + d},{x} {y + d},{x} {y}))"
        cur.execute(
            """INSERT INTO parcel(farm_id,nombre,geom,area_ha,area_m2)
               SELECT %s,%s,ST_Multi(ST_GeomFromText(%s,4326)),ST_Area(ST_GeomFromText(%s,4326)::geography)/10000,
                      ST_Area(ST_GeomFromText(%s,4326)::geography)
               WHERE NOT EXISTS (SELECT 1 FROM parcel WHERE farm_id=%s AND nombre=%s)""",
            (finca[0], nombre, wkt, wkt, wkt, finca[0], nombre),
        )
    n["parcelas"] = 4
    conn.commit()
    return n


def main() -> None:
    url = os.environ.get("DATABASE_URL", "postgresql://milpa:milpa_dev_only@localhost:5432/milpa")
    url = url.replace("postgresql+psycopg", "postgresql")
    raiz = Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge")
    with psycopg.connect(url) as conn:
        print("sembrado:", sembrar(conn, raiz))


if __name__ == "__main__":
    main()
