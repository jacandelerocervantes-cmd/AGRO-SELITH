from pathlib import Path

from export_engine_data import DESTINO, generar


def test_datos_del_motor_ts_estan_al_dia() -> None:
    """Si falla: uv run python tools/export_engine_data.py (y luego npm test en apps/web)."""
    for nombre, texto in generar().items():
        ruta: Path = DESTINO / nombre
        assert ruta.exists(), f"falta {ruta}"
        assert ruta.read_text(encoding="utf-8").replace("\r\n", "\n") == texto, f"{nombre} desactualizado"
