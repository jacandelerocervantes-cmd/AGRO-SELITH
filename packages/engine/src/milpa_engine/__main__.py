"""Demo por línea de comandos: python -m milpa_engine --escenario canicula_prolongada"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .engine import Motor
from .knowledge import cargar, construir_problema


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    ap =argparse.ArgumentParser()
    ap.add_argument("--escenario", default="normal")
    ap.add_argument("--anios", type=int, default=4)
    ap.add_argument("--conocimiento", default="knowledge")
    a = ap.parse_args()
    k = cargar(Path(a.conocimiento))
    prob = construir_problema(k, a.escenario, a.anios)
    print(f"Escenario: {a.escenario} · base: {prob.plan_base[0]} · DATOS PROVISIONALES")
    for plan in Motor(prob).recomendar():
        print(
            f"\n#{plan.ranking} score={plan.score:.2f} "
            f"[P10 {plan.score_p10:.2f} · P50 {plan.score_p50:.2f} · P90 {plan.score_p90:.2f}] "
            f"agua={plan.agua_total_mm:.0f} mm"
        )
        print("   " + " → ".join(plan.secuencia))
        for f in sorted(plan.factores, key=lambda f: -abs(f.contribucion))[:3]:
            print("   -", f.explicacion)


if __name__ == "__main__":
    main()
