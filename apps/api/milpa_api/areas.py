"""Clasificación de preguntas por área de agronomía y utilidades de idioma/escenario. Determinista y sin red."""

from __future__ import annotations

import unicodedata

AREAS = ("suelos", "patogenos", "agua", "clima", "mercado", "cultivos")

PALABRAS: dict[str, tuple[str, ...]] = {
    "suelos": ("suelo", "tierra", "abono", "materia organica", "nitrogeno", "erosion", "pedregos", "fertil", "acahual",
               "soil", "organic matter", "nitrogen", "erosion", "fallow", "stony"),
    "patogenos": ("plaga", "enfermedad", "hongo", "mancha", "patogeno", "virus", "gusano", "insecto",
                  "pest", "disease", "fungus", "pathogen", "blight", "insect", "worm"),
    "agua": ("agua", "riego", "sequia", "canicula", "lluvia", "humedad", "regar", "aguada",
             "water", "irrigation", "drought", "dry spell", "rain", "moisture"),
    "clima": ("clima", "temperatura", "huracan", "helada", "calor", "tormenta", "pronostico",
              "weather", "climate", "hurricane", "frost", "heat", "storm", "forecast"),
    "mercado": ("precio", "mercado", "vender", "venta", "ingreso", "comprador", "ganancia",
                "market", "price", "sell", "income", "buyer", "profit"),
}


def _plano(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", t.lower()) if not unicodedata.combining(c))


def clasificar_area(texto: str) -> str:
    t = _plano(texto)
    puntos = {a: sum(t.count(p) for p in ps) for a, ps in PALABRAS.items()}
    mejor = max(puntos, key=lambda a: puntos[a])
    return mejor if puntos[mejor] > 0 else "cultivos"


def detectar_escenario(texto: str) -> str:
    t = _plano(texto)
    if any(p in t for p in ("huracan", "hurricane", "tormenta", "storm")):
        return "huracan"
    if any(p in t for p in ("canicula", "sequia", "dry spell", "drought", "no llueve", "no rain")):
        return "canicula_prolongada"
    if any(p in t for p in ("tarde", "late rain", "late start", "retras")):
        return "temporal_tardio"
    return "normal"


def pide_plan(texto: str) -> bool:
    t = _plano(texto)
    return any(p in t for p in ("sembr", "siembr", "rotacion", "plan", "cultivo", "plant", "rotation", "crop", "should i grow", "what to grow"))


NOMBRES = {
    "milpa_tradicional": ("Milpa (maíz, frijol y calabaza)", "Milpa (maize, bean and squash)"),
    "milpa_ciclo_corto_criollo": ("Milpa de maíz criollo de ciclo corto", "Short-cycle native-maize milpa"),
    "maiz_monocultivo": ("Maíz solo", "Maize alone"),
    "calabaza_pepita": ("Calabaza para pepita", "Pumpkin for seed"),
    "frijol_xpelon": ("Frijol xpelón", "Xpelón bean"),
    "chile_habanero": ("Chile habanero", "Habanero chili"),
    "mucuna_abono_verde": ("Abono verde de mucuna", "Velvet-bean green manure"),
    "canavalia_cobertura": ("Cobertura de canavalia", "Jack-bean cover crop"),
    "acahual_descanso": ("Descanso con acahual", "Fallow (acahual)"),
    "barbecho_desnudo": ("Barbecho sin cobertura", "Bare fallow"),
}


def nombre_cultivo(crop_id: str, idioma: str) -> str:
    es, en = NOMBRES.get(crop_id, (crop_id, crop_id))
    return en if idioma == "en" else es
