"""Valida la base agronómica: todo parámetro lleva valor, unidad, fuente y estatus.

Uso: python tools/validate_knowledge.py knowledge   (código de salida 1 si hay errores)
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

ESTATUS = {"validado", "provisional"}
PENDIENTE = "pendiente de validación"
SECCIONES = ("opciones", "rules", "escenarios", "mercado", "incertidumbre")


def _check_param(p: dict[str, Any], where: str, errs: list[str]) -> None:
    if isinstance(p.get("valor"), bool) or not isinstance(p.get("valor"), int | float | str):
        errs.append(f"{where}: 'valor' ausente o inválido")
    if not str(p.get("unidad", "")).strip():
        errs.append(f"{where}: falta 'unidad'")
    fuente = str(p.get("fuente", "")).strip()
    if not fuente:
        errs.append(f"{where}: falta 'fuente'")
    est = p.get("estatus")
    if est not in ESTATUS:
        errs.append(f"{where}: 'estatus' debe ser validado|provisional (es {est!r})")
    if est == "validado" and PENDIENTE in fuente:
        errs.append(f"{where}: marcado 'validado' pero la fuente está pendiente")


def _check_params_map(m: Any, where: str, errs: list[str], *, unidad_requerida: bool = True) -> None:
    if not isinstance(m, dict) or not m:
        errs.append(f"{where}: sección vacía o ausente")
        return
    for k, v in m.items():
        if not isinstance(v, dict) or "valor" not in v:
            errs.append(f"{where}.{k}: número suelto sin fuente/estatus (debe ser un parámetro)")
        else:
            _check_param(v, f"{where}.{k}", errs)


def validate_file(path: Path) -> list[str]:
    errs: list[str] = []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not any(s in data for s in SECCIONES):
        return [f"{path}: sin sección reconocida {SECCIONES}"]
    for o in data.get("opciones", []):
        w = f"{path.name}:{o.get('id', '?')}"
        _check_params_map(o.get("parametros"), f"{w}.parametros", errs)
        _check_params_map(o.get("utilidades"), f"{w}.utilidades", errs)
    for r in data.get("rules", []):
        w = f"{path.name}:{r.get('id', '?')}"
        if not str(r.get("fuente", "")).strip():
            errs.append(f"{w}: regla sin fuente")
        if r.get("estatus") not in ESTATUS:
            errs.append(f"{w}: regla con estatus inválido")
    for e in data.get("escenarios", []):
        _check_params_map(e.get("parametros"), f"{path.name}:{e.get('id', '?')}", errs)
    for i in data.get("incertidumbre", []):
        _check_params_map(i.get("parametros"), f"{path.name}:{i.get('id', '?')}", errs)
    for m in data.get("mercado", []):
        w = f"{path.name}:{m.get('opcion_id', '?')}"
        if not isinstance(m.get("sintetico"), bool):
            errs.append(f"{w}: falta bandera booleana 'sintetico'")
        _check_params_map(m.get("parametros"), f"{w}.parametros", errs)
    return errs


def validate_dir(root: Path) -> list[str]:
    files = sorted(root.rglob("*.yaml"))
    if not files:
        return [f"{root}: no hay archivos YAML"]
    errs: list[str] = []
    for f in files:
        errs.extend(validate_file(f))
    return errs


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "knowledge")
    errs = validate_dir(root)
    for e in errs:
        print("ERROR", e)
    n = len(list(root.rglob("*.yaml")))
    print(f"{'FALLA' if errs else 'OK'}: {n} archivos, {len(errs)} errores")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
