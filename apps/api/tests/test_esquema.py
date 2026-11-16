"""Pruebas de esquema contra PostGIS real. Se omiten si no hay base (TEST_DATABASE_URL / localhost)."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config

API = Path(__file__).resolve().parents[1]
ROOT = API.parents[1]
sys.path.insert(0, str(API))
import seed

# Las pruebas usan SU PROPIA base (milpa_test) para no borrar los datos de desarrollo/demo.
URL = os.environ.get("TEST_DATABASE_URL", "postgresql://milpa:milpa_dev_only@localhost:5432/milpa_test")


def _asegurar_bd() -> None:
    base, _, nombre = URL.rpartition("/")
    with psycopg.connect(f"{base}/postgres", autocommit=True, connect_timeout=3) as c:
        if not c.execute("SELECT 1 FROM pg_database WHERE datname=%s", (nombre,)).fetchone():
            c.execute(f'CREATE DATABASE "{nombre}"')


def _conectar() -> psycopg.Connection:
    return psycopg.connect(URL, connect_timeout=3)


try:
    _asegurar_bd()
    _conectar().close()
    HAY_DB = True
except Exception:
    HAY_DB = False

pytestmark = pytest.mark.skipif(not HAY_DB, reason="sin PostGIS (make up)")


def _cfg() -> Config:
    cfg = Config(str(API / "alembic.ini"))
    cfg.set_main_option("script_location", str(API / "alembic"))
    cfg.attributes["url"] = URL.replace("postgresql://", "postgresql+psycopg://")
    return cfg


@pytest.fixture(scope="module")
def conn() -> Iterator[psycopg.Connection]:
    cfg = _cfg()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    c = _conectar()
    yield c
    c.close()


def test_upgrade_crea_todas_las_tablas(conn: psycopg.Connection) -> None:
    n = conn.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name <> 'alembic_version'"
        " AND table_type='BASE TABLE' AND table_name NOT IN ('spatial_ref_sys')"
    ).fetchone()
    assert n is not None and n[0] == 35


def test_parcel_usa_geometria_multipoligono_4326(conn: psycopg.Connection) -> None:
    r = conn.execute("SELECT type, srid FROM geometry_columns WHERE f_table_name='parcel'").fetchone()
    assert r == ("MULTIPOLYGON", 4326)


def test_rol_invalido_es_rechazado(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO user_account(demo_login,role,nombre) VALUES ('x','hacker','n')")
    conn.rollback()


def test_usuario_sin_ninguna_identidad_es_rechazado(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("INSERT INTO user_account(role,nombre) VALUES ('agricultor','n')")
    conn.rollback()


def _usuario(conn: psycopg.Connection, login: str = "demo-agricultor") -> str:
    seed.sembrar(conn, ROOT / "knowledge")
    r = conn.execute("SELECT id FROM user_account WHERE demo_login=%s", (login,)).fetchone()
    assert r is not None
    return str(r[0])


def _pregunta(conn: psycopg.Connection, uid: str, consent: bool) -> str:
    r = conn.execute(
        "INSERT INTO producer_question(user_id,texto,origen,consentimiento_uso,consentimiento_at,sintetico)"
        " VALUES (%s,'¿Cuándo siembro si la canícula se alarga?','demo',%s,%s,true) RETURNING id",
        (uid, consent, datetime.now(UTC) if consent else None),
    ).fetchone()
    assert r is not None
    return str(r[0])


def test_pregunta_sin_consentimiento_no_pasa_a_benchmark(conn: psycopg.Connection) -> None:
    qid = _pregunta(conn, _usuario(conn), consent=False)
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "INSERT INTO benchmark_item(question_id,texto,texto_hash,categoria,split)"
            " VALUES (%s,'t','h-sin','canicula','benchmark')",
            (qid,),
        )
    conn.rollback()


def test_benchmark_solo_evalua_items_del_split_benchmark(conn: psycopg.Connection) -> None:
    uid = _usuario(conn)
    qid = _pregunta(conn, uid, consent=True)
    bench = conn.execute(
        "INSERT INTO benchmark_item(question_id,texto,texto_hash,categoria,split)"
        " VALUES (%s,'t','h-b','canicula','benchmark') RETURNING id",
        (qid,),
    ).fetchone()
    train = conn.execute(
        "INSERT INTO benchmark_item(texto,texto_hash,categoria,split) VALUES ('t2','h-t','agua','entrenamiento')"
        " RETURNING id"
    ).fetchone()
    run = conn.execute(
        "INSERT INTO benchmark_run(nombre,sistema,modelo) VALUES ('r','llm','claude-fable-5-2') RETURNING id"
    ).fetchone()
    assert bench and train and run
    conn.execute(
        "INSERT INTO benchmark_result(run_id,item_id,respuesta,puntaje) VALUES (%s,%s,'ok',0.8)",
        (run[0], bench[0]),
    )
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute(
            "INSERT INTO benchmark_result(run_id,item_id,respuesta) VALUES (%s,%s,'x')", (run[0], train[0])
        )
    conn.rollback()


def test_item_validado_exige_experto_y_referencia(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO benchmark_item(texto,texto_hash,categoria,split,estatus)"
            " VALUES ('t','h-v','agua','benchmark','validado')"
        )
    conn.rollback()


def test_usuarios_demo_sembrados_sin_correo(conn: psycopg.Connection) -> None:
    seed.sembrar(conn, ROOT / "knowledge")
    rows = conn.execute("SELECT role FROM user_account WHERE es_demo AND firebase_uid IS NULL").fetchall()
    assert {r[0] for r in rows} == {"admin", "agricultor", "extensionista"}


def test_parametro_sin_fuente_o_estatus_invalido_es_rechazado(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO rotation_rule(id,tipo,crop_a,crop_b,anios_min,severidad,fuente,estatus)"
            " VALUES ('r','intervalo_retorno','a','b',1,3,'  ','provisional')"
        )
    conn.rollback()
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO rotation_rule(id,tipo,crop_a,crop_b,anios_min,severidad,fuente,estatus)"
            " VALUES ('r','intervalo_retorno','a','b',1,3,'f','quizas')"
        )
    conn.rollback()


def test_audit_log_es_solo_anexar(conn: psycopg.Connection) -> None:
    conn.execute("INSERT INTO audit_log(accion,entidad) VALUES ('t','t')")
    with pytest.raises(psycopg.errors.RaiseException):
        conn.execute("DELETE FROM audit_log")
    conn.rollback()


def test_decision_exige_plan_salvo_descartar(conn: psycopg.Connection) -> None:
    ok = conn.execute(
        "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid='farmer_decision'::regclass AND contype='c'"
    ).fetchall()
    assert any("descartar" in r[0] for r in ok)


def test_semilla_idempotente_y_con_fuente_y_estatus(conn: psycopg.Connection) -> None:
    a = seed.sembrar(conn, ROOT / "knowledge")
    b = seed.sembrar(conn, ROOT / "knowledge")
    assert a == b and a["crop"] == 10 and a["rule"] == 3 and a["scenario"] == 4
    assert conn.execute("SELECT count(*) FROM crop").fetchone() == (10,)
    assert conn.execute("SELECT count(*) FROM crop_param").fetchone() == (10,)
    assert conn.execute("SELECT count(*) FROM model_version").fetchone() == (1,)
    assert conn.execute(
        "SELECT count(*) FROM crop_param WHERE length(trim(fuente))=0 OR estatus IS NULL"
    ).fetchone() == (0,)
    # nada validado todavía: todo es provisional
    assert conn.execute("SELECT count(*) FROM crop_param WHERE estatus='validado'").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM market_balance WHERE NOT sintetico").fetchone() == (0,)


def test_downgrade_deja_la_base_limpia(conn: psycopg.Connection) -> None:
    conn.close()
    command.downgrade(_cfg(), "base")
    c = _conectar()
    n = c.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' AND table_name NOT IN ('alembic_version','spatial_ref_sys')"
    ).fetchone()
    c.close()
    assert n == (0,)
