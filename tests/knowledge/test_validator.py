from pathlib import Path

import yaml
from validate_knowledge import validate_dir

RAIZ = Path(__file__).resolve().parents[2] / "knowledge"


def test_base_real_es_valida() -> None:
    assert validate_dir(RAIZ) == []


def _escribir(tmp: Path, opcion: dict) -> None:
    (tmp / "a.yaml").write_text(yaml.safe_dump({"opciones": [opcion]}), encoding="utf-8")


def _op(param: dict, util: dict | None = None) -> dict:
    ok = {"valor": 0.5, "unidad": "i", "fuente": "x", "estatus": "provisional"}
    return {"id": "o", "parametros": {"p": param}, "utilidades": util or {"u": ok}}


def test_falla_sin_fuente(tmp_path: Path) -> None:
    _escribir(tmp_path, _op({"valor": 1, "unidad": "mm", "estatus": "provisional"}))
    assert any("fuente" in e for e in validate_dir(tmp_path))


def test_falla_sin_estatus(tmp_path: Path) -> None:
    _escribir(tmp_path, _op({"valor": 1, "unidad": "mm", "fuente": "x"}))
    assert any("estatus" in e for e in validate_dir(tmp_path))


def test_falla_con_numero_suelto(tmp_path: Path) -> None:
    _escribir(tmp_path, _op({"valor": 1, "unidad": "mm", "fuente": "x", "estatus": "validado"}, {"u": 0.4}))
    assert any("número suelto" in e for e in validate_dir(tmp_path))


def test_validado_no_puede_tener_fuente_pendiente(tmp_path: Path) -> None:
    f = "pendiente de validación INIFAP/extensionista"
    _escribir(tmp_path, _op({"valor": 1, "unidad": "mm", "fuente": f, "estatus": "validado"}))
    assert any("pendiente" in e for e in validate_dir(tmp_path))
