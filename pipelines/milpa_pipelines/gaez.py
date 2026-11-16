"""FAO GAEZ v4: idoneidad de cultivos y rendimiento alcanzable (clima histórico y proyecciones), ~9 km.

Se lee del servicio público ArcGIS ImageServer de la FAO (sin llave): `query` para encontrar los rásteres y
`identify` para leer el valor en el punto. Cobertura global: sirve para Tizimín y para cualquier parcela.
Futuro: solo hay nivel de insumos ALTO; se reporta el promedio de 5 modelos climáticos y su rango.
"""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

from .base import FIXTURES, Conector

BASE = "https://gaez-services.fao.org/server/rest/services/res05/ImageServer"
CULTIVOS = ("Maize", "Phaseolus bean", "Cowpea", "Sweet potato", "Cassava")
V_INDICE = "Suitability index  range (0 – 10000); all land in grid cell"
V_REND = "Average attainable yield of best occurring suitability class in grid cell"
MODELOS = ("GFDL-ESM2M", "HadGEM2-ES", "IPSL-CM5A-LR", "MIROC-ESM-CHEM", "NorESM1-M")

# Escenarios: clave -> condición del catálogo
ESCENARIOS = {
    "hist_bajo": "year='1981-2010' AND rcp='Historical' AND input_level='Low' AND model='CRUTS32'",
    "hist_alto": "year='1981-2010' AND rcp='Historical' AND input_level='High' AND model='CRUTS32'",
    "fut45": "year='2041-2070' AND rcp='RCP4.5' AND input_level='High' AND c02_fertilization='Without CO2 Fertilization'",
    "fut85": "year='2041-2070' AND rcp='RCP8.5' AND input_level='High' AND c02_fertilization='Without CO2 Fertilization'",
}


def _tipo(variable: str) -> str | None:
    return "indice" if variable == V_INDICE else "rend" if variable == V_REND else None


class Gaez(Conector):
    nombre, fuente = "gaez", "FAO GAEZ v4 (idoneidad y rendimiento alcanzable, ~9 km)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        crops = ",".join(f"'{c}'" for c in CULTIVOS)
        variables = f"'{V_INDICE}','{V_REND}'"
        filas: list[dict[str, Any]] = []
        catalogo: list[dict[str, Any]] = []
        for clave, cond in ESCENARIOS.items():
            r = client.get(
                f"{BASE}/query",
                params={"where": f"crop IN ({crops}) AND water_supply='Rainfed' AND variable IN ({variables}) AND {cond}",
                        "outFields": "objectid,crop,model,variable,input_level", "returnGeometry": "false", "f": "json"},
                timeout=60,
            )
            r.raise_for_status()
            for f in r.json().get("features", []):
                a = f["attributes"]
                if _tipo(a["variable"]) and (clave.startswith("hist") or a["model"] in MODELOS):
                    catalogo.append({"oid": a["objectid"], "crop": a["crop"], "esc": clave, "modelo": a["model"], "tipo": _tipo(a["variable"])})
        punto = json.dumps({"x": p["lon"], "y": p["lat"], "spatialReference": {"wkid": 4326}})

        def leer(c: dict[str, Any]) -> dict[str, Any]:
            for intento in range(4):  # el servicio de la FAO a veces tarda: se reintenta
                try:
                    r = httpx.get(f"{BASE}/identify", params={
                        "geometry": punto, "geometryType": "esriGeometryPoint", "returnGeometry": "false", "returnCatalogItems": "false", "f": "json",
                        "mosaicRule": json.dumps({"mosaicMethod": "esriMosaicLockRaster", "lockRasterIds": [c["oid"]]})}, timeout=90)
                    r.raise_for_status()
                    v = r.json().get("value")
                    return {**c, "valor": None if v in (None, "NoData", "") else float(v)}
                except (httpx.HTTPError, ValueError):
                    if intento == 3:
                        return {**c, "valor": None}
            return {**c, "valor": None}

        with ThreadPoolExecutor(4) as ex:
            filas = list(ex.map(leer, catalogo))
        if not filas:
            raise ValueError("GAEZ no devolvió rásteres")
        return {"punto": {"lon": p["lon"], "lat": p["lat"]}, "filas": filas}

    def parsear(self, crudo: Any, **p: Any) -> dict[str, dict[str, dict[str, Any]]]:
        """{cultivo: {escenario: {indice (0-100), indice_min, indice_max, rendimiento_kg_ms_ha, n_modelos}}}"""
        acum: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: {"indice": [], "rend": []})
        for f in crudo.get("filas", []):
            if f["valor"] is not None and f["valor"] >= 0:
                acum[(f["crop"], f["esc"])][f["tipo"]].append(f["valor"])
        out: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        for (crop, esc), v in acum.items():
            if not v["indice"]:
                continue
            idx = [x / 100 for x in v["indice"]]  # 0-10000 -> 0-100
            out[crop][esc] = {
                "indice": sum(idx) / len(idx), "indice_min": min(idx), "indice_max": max(idx),
                "rendimiento_kg_ms_ha": sum(v["rend"]) / len(v["rend"]) if v["rend"] else None, "n_modelos": len(idx),
            }
        return dict(out)

    def fallback_sintetico(self, **p: Any) -> Any:
        return {"sintetico": True, "punto": {"lon": p.get("lon"), "lat": p.get("lat")}, "filas": []}


def _cerca_del_fixture(lat: float, lon: float) -> bool:
    ruta = FIXTURES / "gaez.json"
    if not ruta.exists():
        return False
    fx = json.loads(ruta.read_text(encoding="utf-8"))["punto"]
    return abs(fx["lat"] - lat) <= 0.1 and abs(fx["lon"] - lon) <= 0.1


def cargar_gaez(conn: Any, modo: str = "demo") -> dict[str, int]:
    """Guarda idoneidad y rendimiento de GAEZ para cada parcela (rejilla de ~9 km, con caché por celda)."""
    cur = conn.cursor()
    parcelas = cur.execute("SELECT id, ST_X(ST_Centroid(geom)), ST_Y(ST_Centroid(geom)) FROM parcel").fetchall()
    cache: dict[tuple[int, int], Any] = {}
    n = omitidas = 0
    for pid, lon, lat in parcelas:
        clave = (round(lat / 0.0833), round(lon / 0.0833))
        if clave not in cache:
            cache[clave] = Gaez(modo=modo).obtener(lat=round(lat, 4), lon=round(lon, 4))
        r = cache[clave]
        # El fixture grabado es de un punto concreto (Tizimín): no se reutiliza para parcelas lejanas
        if r.origen == "fixture" and not r.sintetico and not _cerca_del_fixture(lat, lon):
            omitidas += 1
            continue
        for cultivo, escs in r.datos.items():
            for esc, v in escs.items():
                cur.execute(
                    """INSERT INTO parcel_gaez(parcel_id,cultivo,escenario,indice,indice_min,indice_max,rendimiento_kg_ms_ha,
                         n_modelos,fuente,sintetico) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (parcel_id,cultivo,escenario) DO UPDATE SET indice=EXCLUDED.indice,
                         indice_min=EXCLUDED.indice_min, indice_max=EXCLUDED.indice_max,
                         rendimiento_kg_ms_ha=EXCLUDED.rendimiento_kg_ms_ha, n_modelos=EXCLUDED.n_modelos,
                         fuente=EXCLUDED.fuente, sintetico=EXCLUDED.sintetico""",
                    (pid, cultivo, esc, v["indice"], v["indice_min"], v["indice_max"], v["rendimiento_kg_ms_ha"],
                     v["n_modelos"], r.fuente, r.sintetico),
                )
                n += 1
    conn.commit()
    return {"parcelas": len(parcelas), "filas": n, "omitidas_por_lejania": omitidas}
