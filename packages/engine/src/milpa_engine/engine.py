"""Motor determinista de rotación (puro: sin red, sin azar sin semilla fija). Ver ADR-0002."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

CRITERIOS = (
    "agua_eficiencia",
    "fijacion_n",
    "materia_organica",
    "control_erosion",
    "infiltracion",
    "ruptura_plagas",
    "valor_forrajero",
    "ingreso_neto",
    "estabilidad_ingreso",
    "proteccion_etapas",
)
PENALIZACIONES = ("barbecho_excesivo", "concentracion_riesgo", "dependencia_monocultivo")

ETIQUETAS = {
    "agua_eficiencia": "Uso eficiente del agua",
    "fijacion_n": "Nitrógeno que deja en el suelo",
    "materia_organica": "Materia orgánica del suelo",
    "control_erosion": "Protección contra la erosión",
    "infiltracion": "Entrada de agua al suelo",
    "ruptura_plagas": "Corta el ciclo de plagas",
    "valor_forrajero": "Forraje para animales",
    "ingreso_neto": "Ingreso",
    "estabilidad_ingreso": "Ingreso estable año con año",
    "proteccion_etapas": "Protege floración y llenado de la canícula",
    "barbecho_excesivo": "Descanso sin cobertura",
    "concentracion_riesgo": "Riesgo concentrado en ciclos seguidos",
    "dependencia_monocultivo": "Depender de un solo cultivo",
}


def _clamp(x: float) -> float:
    return 0.0 if x < 0.0 else min(x, 1.0)


@dataclass(frozen=True)
class Opcion:
    id: str
    nombre: str
    familias: frozenset[str] = frozenset()
    hospedantes: frozenset[str] = frozenset()
    es_barbecho: bool = False
    es_barbecho_desnudo: bool = False
    agua_mm: float = 0.0
    tolerancia_sequia: int = 3
    sensibilidad_canicula: float = 0.0
    ingreso_mxn_ha: float = 0.0
    n_aporte_kg_ha: float = 0.0
    mo_aporte: float = 0.0
    utilidades: dict[str, float] = field(default_factory=dict)
    capacidad_absorcion_ha: float | None = None
    sintetico: bool = False


@dataclass(frozen=True)
class Regla:
    id: str
    tipo: str
    selector_a: str
    selector_b: str
    anios_min: int
    severidad: int

    @property
    def dura(self) -> bool:
        return self.severidad >= 3


def coincide(selector: str, op: Opcion) -> bool:
    tipo, _, val = selector.partition(":")
    if tipo == "id":
        return op.id == val
    if tipo == "fam":
        return val in op.familias
    if tipo == "host":
        return val in op.hospedantes
    raise ValueError(f"selector inválido: {selector}")


@dataclass(frozen=True)
class Escenario:
    id: str
    severidad_canicula: float = 0.0
    factor_demanda_agua: float = 1.0
    factor_estres_ingreso: float = 0.0
    tolerancia_minima: int = 1


@dataclass(frozen=True)
class Problema:
    opciones: tuple[Opcion, ...]
    reglas: tuple[Regla, ...]
    escenario: Escenario
    horizonte_anios: int
    plan_base: tuple[str, ...]
    pesos: dict[str, float]
    lambdas: dict[str, float] = field(default_factory=dict)
    ciclos_por_anio: int = 1
    area_ha: float = 1.0
    cuota_max: float = 0.15
    sigma_ingreso: float = 0.15  # provisional
    sigma_severidad: float = 0.10  # provisional

    @property
    def n_slots(self) -> int:
        return self.horizonte_anios * self.ciclos_por_anio


@dataclass(frozen=True)
class Factor:
    factor: str
    valor_norm: float
    peso: float
    contribucion: float
    explicacion: str


@dataclass(frozen=True)
class Plan:
    ranking: int
    secuencia: tuple[str, ...]
    score: float
    score_p10: float
    score_p50: float
    score_p90: float
    agua_total_mm: float
    ingreso_estimado: float
    delta_mo: float
    delta_n: float
    riesgo_plaga: float
    factores: tuple[Factor, ...]


class Motor:
    def __init__(self, p: Problema) -> None:
        self.p = p
        self.ops = p.opciones
        self.n = p.n_slots
        idx = {o.id: i for i, o in enumerate(self.ops)}
        if len(idx) != len(self.ops):
            raise ValueError("ids de opción duplicados")
        if len(p.plan_base) != self.n or any(b not in idx for b in p.plan_base):
            raise ValueError("plan_base debe tener un id válido por slot")
        self.idx = idx
        esc = p.escenario
        self.agua_base = [self.ops[idx[b]].agua_mm * esc.factor_demanda_agua for b in p.plan_base]
        self.max_ing = max((o.ingreso_mxn_ha for o in self.ops), default=0.0) or 1.0
        cpy = p.ciclos_por_anio
        self.H = max(1, min(max([r.anios_min * cpy for r in p.reglas] + [1]), max(self.n - 1, 1)))
        self.permitidas = [
            [i for i, o in enumerate(self.ops) if self._ok_local(o, t)] for t in range(self.n)
        ]

    # ---- filtros duros ----
    def _ok_local(self, o: Opcion, t: int) -> bool:
        esc = self.p.escenario
        if not o.es_barbecho and o.tolerancia_sequia < esc.tolerancia_minima:
            return False
        if o.agua_mm * esc.factor_demanda_agua > self.agua_base[t] + 1e-9:
            return False
        cap = o.capacidad_absorcion_ha
        return cap is None or self.p.area_ha <= cap * self.p.cuota_max + 1e-9

    def _golpes(self, hist: tuple[int, ...], nuevo: int, solo_duras: bool) -> bool:
        cpy = self.p.ciclos_por_anio
        new_op = self.ops[nuevo]
        for d in range(1, len(hist) + 1):
            e = self.ops[hist[-d]]
            for r in self.p.reglas:
                if solo_duras and not r.dura:
                    continue
                if (
                    d <= r.anios_min * cpy
                    and coincide(r.selector_a, e)
                    and coincide(r.selector_b, new_op)
                ):
                    return True
        return False

    # ---- puntaje ----
    def _terminos(
        self, hist: tuple[int, ...], i: int, sev: float, ing_mult: float
    ) -> tuple[dict[str, float], dict[str, float]]:
        o = self.ops[i]
        esc = self.p.escenario
        u = {k: _clamp(o.utilidades.get(k, 0.0)) for k in CRITERIOS}
        u["proteccion_etapas"] = _clamp(1.0 - o.sensibilidad_canicula * sev)
        estres = 1.0 - esc.factor_estres_ingreso * sev * o.sensibilidad_canicula
        u["ingreso_neto"] = _clamp(o.ingreso_mxn_ha / self.max_ing * estres * ing_mult)
        if self._golpes(hist, i, solo_duras=False):
            u["ruptura_plagas"] = 0.0
        prev = self.ops[hist[-1]] if hist else None
        pen = dict.fromkeys(PENALIZACIONES, 0.0)
        if o.es_barbecho:
            # Descanso/cobertura sin producir: pesa más si es desnudo o si sigue a otro descanso.
            seguido = prev is not None and prev.es_barbecho
            pen["barbecho_excesivo"] = (1.0 if seguido else 0.5) if o.es_barbecho_desnudo else (
                0.5 if seguido else 0.0
            )
        if prev is not None and o.sensibilidad_canicula > 0.7 and prev.sensibilidad_canicula > 0.7:
            pen["concentracion_riesgo"] = 1.0
        if prev is not None and prev.id == o.id and not o.es_barbecho:
            pen["dependencia_monocultivo"] = 1.0
        return u, pen

    def _puntaje_slot(self, u: dict[str, float], pen: dict[str, float]) -> float:
        w, lam = self.p.pesos, self.p.lambdas
        return sum(w.get(k, 0.0) * u[k] for k in CRITERIOS) - sum(
            lam.get(k, 0.0) * pen[k] for k in PENALIZACIONES
        )

    # ---- búsqueda exacta (DP k-best) ----
    def _buscar(self, k: int) -> list[tuple[float, tuple[int, ...]]]:
        sev = self.p.escenario.severidad_canicula
        estados: dict[tuple[int, ...], list[tuple[float, tuple[int, ...]]]] = {(): [(0.0, ())]}
        for t in range(self.n):
            nuevos: dict[tuple[int, ...], list[tuple[float, tuple[int, ...]]]] = {}
            for hist, lista in estados.items():
                for i in self.permitidas[t]:
                    if self._golpes(hist, i, solo_duras=True):
                        continue
                    u, pen = self._terminos(hist, i, sev, 1.0)
                    s = self._puntaje_slot(u, pen)
                    nh = (hist + (i,))[-self.H :]
                    cub = nuevos.setdefault(nh, [])
                    cub.extend((sc + s, seq + (i,)) for sc, seq in lista)
            for nh, cub in nuevos.items():
                cub.sort(key=lambda x: (-x[0], x[1]))
                del cub[k:]
            estados = nuevos
        todos = [x for lst in estados.values() for x in lst]
        todos.sort(key=lambda x: (-x[0], x[1]))
        return todos[:k]

    # ---- evaluación, explicación y Monte Carlo ----
    def _montecarlo(self, seq: tuple[int, ...], replicas: int, seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        ing = rng.lognormal(0.0, self.p.sigma_ingreso, (replicas, self.n))
        sev = np.clip(
            self.p.escenario.severidad_canicula + rng.normal(0.0, self.p.sigma_severidad, replicas),
            0.0,
            1.0,
        )
        res = np.empty(replicas)
        for r in range(replicas):
            hist: tuple[int, ...] = ()
            tot = 0.0
            for t, i in enumerate(seq):
                u, pen = self._terminos(hist, i, float(sev[r]), float(ing[r, t]))
                tot += self._puntaje_slot(u, pen)
                hist = (hist + (i,))[-self.H :]
            res[r] = tot / self.n
        return np.percentile(res, [10, 50, 90])

    def _evaluar(self, ranking: int, seq: tuple[int, ...], replicas: int, seed: int) -> Plan:
        sev = self.p.escenario.severidad_canicula
        sum_u = dict.fromkeys(CRITERIOS, 0.0)
        sum_p = dict.fromkeys(PENALIZACIONES, 0.0)
        hist: tuple[int, ...] = ()
        agua = ing = d_mo = d_n = 0.0
        for i in seq:
            u, pen = self._terminos(hist, i, sev, 1.0)
            for c in CRITERIOS:
                sum_u[c] += u[c]
            for c in PENALIZACIONES:
                sum_p[c] += pen[c]
            o = self.ops[i]
            agua += o.agua_mm * self.p.escenario.factor_demanda_agua
            ing += o.ingreso_mxn_ha * self.p.area_ha * (
                1.0 - self.p.escenario.factor_estres_ingreso * sev * o.sensibilidad_canicula
            )
            d_mo += o.mo_aporte
            d_n += o.n_aporte_kg_ha
            hist = (hist + (i,))[-self.H :]
        n = self.n
        factores: list[Factor] = []
        for c in CRITERIOS:
            v, w = sum_u[c] / n, self.p.pesos.get(c, 0.0)
            factores.append(Factor(c, v, w, w * v, _explicar(c, w * v)))
        for c in PENALIZACIONES:
            v, lam = sum_p[c] / n, self.p.lambdas.get(c, 0.0)
            factores.append(Factor(c, v, lam, -lam * v, _explicar(c, -lam * v)))
        score = sum(f.contribucion for f in factores)
        p10, p50, p90 = (float(x) for x in self._montecarlo(seq, replicas, seed))
        return Plan(
            ranking=ranking,
            secuencia=tuple(self.ops[i].id for i in seq),
            score=score,
            score_p10=p10,
            score_p50=p50,
            score_p90=p90,
            agua_total_mm=agua,
            ingreso_estimado=ing,
            delta_mo=d_mo,
            delta_n=d_n,
            riesgo_plaga=1.0 - sum_u["ruptura_plagas"] / n,
            factores=tuple(factores),
        )

    def recomendar(self, k: int = 3, replicas: int = 200, seed: int = 0) -> list[Plan]:
        if replicas < 200:
            raise ValueError("Monte Carlo requiere al menos 200 réplicas")
        return [
            self._evaluar(r + 1, seq, replicas, seed)
            for r, (_, seq) in enumerate(self._buscar(k))
        ]

    def evaluar_ids(self, ids: tuple[str, ...], replicas: int = 200, seed: int = 0, ranking: int = 0) -> Plan:
        """Evalúa una secuencia dada (p. ej. la rotación que el productor ya usa) con el mismo puntaje."""
        if len(ids) != self.n or any(i not in self.idx for i in ids):
            raise ValueError("secuencia inválida")
        return self._evaluar(ranking, tuple(self.idx[i] for i in ids), replicas, seed)

    def comparar(self, alternativas: int = 2, replicas: int = 200, seed: int = 0) -> list[Plan]:
        """Rotación existente (ranking 0) + las mejores alternativas distintas: mínimo tres estrategias."""
        existente = self.evaluar_ids(self.p.plan_base, replicas, seed, ranking=0)
        otras = [
            replace(pl, ranking=i + 1)
            for i, pl in enumerate(
                [pl for pl in self.recomendar(alternativas + 1, replicas, seed) if pl.secuencia != existente.secuencia][
                    :alternativas
                ]
            )
        ]
        return [existente, *otras]


def _explicar(factor: str, contrib: float) -> str:
    verbo = "suma" if contrib >= 0 else "resta"
    return f"{ETIQUETAS[factor]}: {verbo} {abs(contrib):.2f} al puntaje"
