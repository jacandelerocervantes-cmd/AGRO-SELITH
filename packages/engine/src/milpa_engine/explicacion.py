"""Explicación de cada estrategia: por qué, evidencia, beneficios, vacíos de información y riesgos.

Puro y determinista (sin red). Bilingüe (es/en). El texto sale de los factores del motor y del estado de las
capas de datos; no inventa cifras: todo número viene del plan o del contexto recibido.
"""

from __future__ import annotations

from typing import Any

from .engine import Plan

T: dict[str, dict[str, str]] = {
    "por_que_base": {
        "es": "Es la rotación que usa hoy; sirve de punto de comparación.",
        "en": "This is the rotation in use today; it is the baseline for comparison.",
    },
    "por_que_top": {
        "es": "Aporta sobre todo en: {top}.",
        "en": "It contributes mostly to: {top}.",
    },
    "benef_agua": {
        "es": "Usa {ahorro:.0f} mm menos de agua que la rotación actual en {n} años.",
        "en": "Uses {ahorro:.0f} mm less water than the current rotation over {n} years.",
    },
    "benef_agua_igual": {
        "es": "Usa el mismo nivel de agua que la rotación actual.",
        "en": "Uses the same water level as the current rotation.",
    },
    "benef_n": {
        "es": "Deja más nitrógeno al suelo (+{dn:.0f} kg N/ha en total frente a la actual).",
        "en": "Leaves more nitrogen in the soil (+{dn:.0f} kg N/ha in total versus the current one).",
    },
    "benef_mo": {
        "es": "Mejora la materia orgánica frente a la actual (índice +{dmo:.1f}).",
        "en": "Improves organic matter versus the current one (index +{dmo:.1f}).",
    },
    "benef_plagas": {
        "es": "Corta mejor el ciclo de plagas (riesgo {r:.0%} frente a {r0:.0%}).",
        "en": "Breaks the pest cycle better (risk {r:.0%} versus {r0:.0%}).",
    },
    "benef_ingreso": {
        "es": "Ingreso estimado de {ing:,.0f} MXN en el periodo.",
        "en": "Estimated income of {ing:,.0f} MXN over the period.",
    },
    "ev_capa": {
        "es": "{capa} ({fuente}): {estado}",
        "en": "{capa} ({fuente}): {estado}",
    },
    "estado_real": {"es": "dato observado", "en": "observed data"},
    "estado_sint": {"es": "ejemplo (sin datos reales aún)", "en": "example (no real data yet)"},
    "estado_falta": {"es": "no disponible", "en": "not available"},
    "ev_motor": {
        "es": "Reglas del motor con parámetros {estatus}; cada aporte suma al puntaje {score:.2f}.",
        "en": "Engine rules with {estatus} parameters; each contribution adds up to the score {score:.2f}.",
    },
    "gap_inegi": {
        "es": "Falta el suelo medido (INEGI/perfil local): el suelo se estima con SoilGrids, poco fiable en terreno kárstico.",
        "en": "Measured soil is missing (INEGI/local profile): soil is estimated with SoilGrids, which is unreliable on karst terrain.",
    },
    "gap_estaciones": {
        "es": "Sin estaciones locales (SMN/CONAGUA) para corregir el sesgo de los satélites.",
        "en": "No local stations (SMN/CONAGUA) to correct satellite bias.",
    },
    "gap_params": {
        "es": "Los parámetros agronómicos están pendientes de validar por INIFAP o un extensionista.",
        "en": "Agronomic parameters are pending validation by INIFAP or an extension agent.",
    },
    "gap_capa": {
        "es": "La capa {capa} no está disponible: no se usó como evidencia.",
        "en": "The {capa} layer is not available: it was not used as evidence.",
    },
    "gap_sint": {
        "es": "La capa {capa} es de ejemplo, no una observación real.",
        "en": "The {capa} layer is example data, not a real observation.",
    },
    "riesgo_local": {
        "es": "Debe revisarlo un agrónomo local antes de aplicarlo: el plan apoya, no sustituye, su criterio.",
        "en": "A local agronomist should review it before applying: the plan supports, not replaces, your judgment.",
    },
    "riesgo_plaga": {
        "es": "Riesgo de plagas estimado en {r:.0%}; vigile los cultivos que repiten familia botánica.",
        "en": "Estimated pest risk is {r:.0%}; watch crops that repeat a botanical family.",
    },
    "riesgo_ingreso": {
        "es": "Su ingreso estimado es menor que el de la rotación actual: confirme que le conviene.",
        "en": "Its estimated income is lower than the current rotation: confirm it suits you.",
    },
    "ev_gaez": {
        "es": "FAO GAEZ ({cultivo}, secano, pocos insumos): idoneidad {ib:.0f}/100 y rendimiento alcanzable de {rb:.0f} kg de materia seca/ha; con más insumos, {ra:.0f}. Hacia 2041-2070 (insumos altos) se proyectan {r45:.0f} a {r85:.0f} según el escenario climático.",
        "en": "FAO GAEZ ({cultivo}, rainfed, low inputs): suitability {ib:.0f}/100 and attainable yield of {rb:.0f} kg dry matter/ha; with more inputs, {ra:.0f}. By 2041-2070 (high inputs) {r45:.0f} to {r85:.0f} are projected depending on the climate scenario.",
    },
    "riesgo_gaez_bajo": {
        "es": "FAO GAEZ clasifica esta zona con idoneidad baja para {cultivo} en secano con pocos insumos ({ib:.0f}/100): un experto local debe validar si la siembra compensa.",
        "en": "FAO GAEZ rates this area as low suitability for {cultivo} rainfed with low inputs ({ib:.0f}/100): a local expert should validate whether planting pays off.",
    },
    "riesgo_gaez_caida": {
        "es": "FAO GAEZ proyecta que el rendimiento alcanzable de {cultivo} baje {pct:.0f} % hacia 2041-2070 en el escenario RCP8.5.",
        "en": "FAO GAEZ projects attainable {cultivo} yield falling {pct:.0f}% by 2041-2070 under RCP8.5.",
    },
    "riesgo_incert": {
        "es": "Incertidumbre del puntaje: entre {p10:.2f} y {p90:.2f} en el 80 % de las simulaciones.",
        "en": "Score uncertainty: between {p10:.2f} and {p90:.2f} in 80% of simulations.",
    },
}

# Cultivo del motor -> cultivo de FAO GAEZ (el caupí es el frijol xpelón; la milpa se mide por su maíz)
GAEZ_CULTIVO = {"milpa_tradicional": "Maize", "milpa_ciclo_corto_criollo": "Maize", "maiz_monocultivo": "Maize", "frijol_xpelon": "Cowpea"}
GAEZ_NOMBRE = {"Maize": ("maíz", "maize"), "Cowpea": ("frijol xpelón (caupí)", "xpelón bean (cowpea)")}

NOMBRE_CAPA = {
    "imerg": ("Lluvia GPM/IMERG", "GPM/IMERG rainfall"),
    "smap": ("Humedad del suelo SMAP", "SMAP soil moisture"),
    "gldas": ("Humedad y ET GLDAS", "GLDAS moisture and ET"),
    "ndvi_modis": ("Vegetación MODIS", "MODIS vegetation"),
    "ndvi_landsat": ("Vegetación Landsat", "Landsat vegetation"),
    "ndvi_s2": ("Vegetación Sentinel-2 (10 m)", "Sentinel-2 vegetation (10 m)"),
    "lst_modis": ("Temperatura MODIS", "MODIS temperature"),
    "et_modis": ("Evapotranspiración MODIS", "MODIS evapotranspiration"),
    "srtm": ("Relieve SRTM", "SRTM terrain"),
    "ecostress": ("Temperatura y ET ECOSTRESS", "ECOSTRESS temperature and ET"),
    "grace": ("Agua almacenada GRACE-FO", "GRACE-FO water storage"),
    "gedi": ("Biomasa GEDI", "GEDI biomass"),
    "power": ("Clima NASA POWER", "NASA POWER climate"),
    "era5": ("Clima ERA5", "ERA5 climate"),
}


def _t(clave: str, idioma: str, **kw: Any) -> str:
    return T[clave][idioma].format(**kw)


def explicar(plan: Plan, base: Plan, contexto: dict[str, Any], idioma: str = "es", n_anios: int = 4) -> dict[str, Any]:
    """Estructura que el chat muestra: por qué, evidencia, beneficios, vacíos y riesgos."""
    if idioma not in ("es", "en"):
        idioma = "es"
    esbase = plan.ranking == 0
    top = [f.explicacion.split(":")[0].lower() for f in sorted(plan.factores, key=lambda f: -f.contribucion)[:2]]
    por_que = _t("por_que_base", idioma) if esbase else _t("por_que_top", idioma, top=" / ".join(top))

    beneficios: list[str] = []
    if not esbase:
        ahorro = base.agua_total_mm - plan.agua_total_mm
        beneficios.append(_t("benef_agua", idioma, ahorro=ahorro, n=n_anios) if ahorro > 1 else _t("benef_agua_igual", idioma))
        if plan.delta_n - base.delta_n > 1:
            beneficios.append(_t("benef_n", idioma, dn=plan.delta_n - base.delta_n))
        if plan.delta_mo - base.delta_mo > 0.05:
            beneficios.append(_t("benef_mo", idioma, dmo=plan.delta_mo - base.delta_mo))
        if base.riesgo_plaga - plan.riesgo_plaga > 0.02:
            beneficios.append(_t("benef_plagas", idioma, r=plan.riesgo_plaga, r0=base.riesgo_plaga))
    beneficios.append(_t("benef_ingreso", idioma, ing=plan.ingreso_estimado))

    evidencia: list[str] = []
    gaps: list[str] = []
    capas: dict[str, dict[str, Any]] = contexto.get("capas", {})
    for clave, (es, en) in NOMBRE_CAPA.items():
        c = capas.get(clave)
        capa = es if idioma == "es" else en
        if c is None:
            continue
        if not c.get("disponible"):
            gaps.append(_t("gap_capa", idioma, capa=capa))
            continue
        estado = _t("estado_sint" if c.get("sintetico") else "estado_real", idioma)
        evidencia.append(_t("ev_capa", idioma, capa=capa, fuente=c.get("fuente", ""), estado=estado))
        if c.get("sintetico"):
            gaps.append(_t("gap_sint", idioma, capa=capa))
    evidencia.append(_t("ev_motor", idioma, estatus=contexto.get("estatus_parametros", "provisional"), score=plan.score))
    gaez_riesgos: list[str] = []
    vistos: set[str] = set()
    for cid in plan.secuencia:
        cultivo = GAEZ_CULTIVO.get(cid)
        g = contexto.get("gaez", {}).get(cultivo or "")
        if not cultivo or cultivo in vistos or not g:
            continue
        hb, ha, f45, f85 = g.get("hist_bajo"), g.get("hist_alto"), g.get("fut45"), g.get("fut85")
        if not (hb and ha and f45 and f85):
            continue
        vistos.add(cultivo)
        nom = GAEZ_NOMBRE[cultivo][0 if idioma == "es" else 1]
        evidencia.append(_t("ev_gaez", idioma, cultivo=nom, ib=hb["indice"], rb=hb["rend"] or 0, ra=ha["rend"] or 0,
                            r45=f45["rend"] or 0, r85=f85["rend"] or 0))
        if hb["indice"] < 30:
            gaez_riesgos.append(_t("riesgo_gaez_bajo", idioma, cultivo=nom, ib=hb["indice"]))
        if ha["rend"] and f85["rend"] and f85["rend"] < 0.8 * ha["rend"]:
            gaez_riesgos.append(_t("riesgo_gaez_caida", idioma, cultivo=nom, pct=(1 - f85["rend"] / ha["rend"]) * 100))
    if contexto.get("suelo_sin_medicion", True):
        gaps.append(_t("gap_inegi", idioma))
    if not contexto.get("hay_estaciones", False):
        gaps.append(_t("gap_estaciones", idioma))
    if contexto.get("estatus_parametros", "provisional") != "validado":
        gaps.append(_t("gap_params", idioma))

    riesgos = [_t("riesgo_local", idioma)]
    riesgos += gaez_riesgos
    if plan.riesgo_plaga > 0.4:
        riesgos.append(_t("riesgo_plaga", idioma, r=plan.riesgo_plaga))
    if not esbase and plan.ingreso_estimado < base.ingreso_estimado:
        riesgos.append(_t("riesgo_ingreso", idioma))
    if plan.score_p10 is not None and plan.score_p90 is not None:
        riesgos.append(_t("riesgo_incert", idioma, p10=plan.score_p10, p90=plan.score_p90))

    return {"por_que": por_que, "beneficios": beneficios, "evidencia": evidencia, "vacios": gaps, "riesgos": riesgos}
