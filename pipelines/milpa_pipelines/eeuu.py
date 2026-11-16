"""Recursos de EE. UU. usados como REFERENCIA donde valen la pena (caso de referencia: condado de Hidalgo, Texas).

No se copian valores a Tizimín: sirven para (1) medir cuánto se equivocan los productos globales cuando hay
medición real (SSURGO vs SoilGrids; NAIP de ~1 m vs Sentinel-2/Landsat), (2) conocer rotaciones reales (CDL) y
(3) calibrar la incertidumbre que el motor usa en México. Todo sin llave: NRCS Soil Data Access y Planetary Computer.
"""

from __future__ import annotations

from typing import Any

import httpx
import numpy as np

from .base import Conector
from .nasa import _buscar_items, _fecha_item, _firmar, _leer_ventana

SDA = "https://sdmdataaccess.nrcs.usda.gov/Tabular/post.rest"


class Ssurgo(Conector):
    """Suelo oficial del NRCS (SSURGO) en un punto: horizonte superficial del componente dominante."""

    nombre, fuente = "ssurgo", "USDA NRCS SSURGO (Soil Data Access)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        q = f"""SELECT TOP 1 mu.mukey, mu.muname, c.compname, c.comppct_r, c.drainagecl, c.hydgrp,
                 ch.hzdept_r, ch.hzdepb_r, ch.sandtotal_r, ch.silttotal_r, ch.claytotal_r, ch.om_r, ch.awc_r, ch.ph1to1h2o_r
                FROM mapunit mu INNER JOIN component c ON c.mukey = mu.mukey INNER JOIN chorizon ch ON ch.cokey = c.cokey
                WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT({p["lon"]} {p["lat"]})'))
                  AND c.majcompflag = 'Yes' ORDER BY c.comppct_r DESC, ch.hzdept_r ASC"""
        r = client.post(SDA, json={"query": q, "format": "JSON+COLUMNNAME"}, timeout=60)
        r.raise_for_status()
        tabla = r.json().get("Table", [])
        if len(tabla) < 2:
            raise ValueError("SSURGO no tiene suelo mapeado en ese punto")
        return {"producto": "SSURGO horizonte superficial", "fila": dict(zip(tabla[0], tabla[1], strict=True))}

    def parsear(self, crudo: Any, **p: Any) -> dict[str, Any]:
        f = crudo["fila"]
        num = lambda k: None if f.get(k) in (None, "") else float(f[k])  # noqa: E731
        return {"unidad_suelo": f["muname"], "componente": f["compname"], "drenaje": f["drainagecl"], "grupo_hidrologico": f["hydgrp"],
                "arena_pct": num("sandtotal_r"), "limo_pct": num("silttotal_r"), "arcilla_pct": num("claytotal_r"),
                "materia_organica_pct": num("om_r"), "agua_disponible_cm_cm": num("awc_r"), "ph": num("ph1to1h2o_r"),
                "profundidad_cm": [num("hzdept_r"), num("hzdepb_r")]}

    def fallback_sintetico(self, **p: Any) -> Any:
        raise FileNotFoundError("sin ejemplo sintético: SSURGO es un dato medido")


class CdlRotacion(Conector):
    """Qué cultivo hubo cada año (USDA Cropland Data Layer, 30 m, vía Planetary Computer): la rotación real."""

    nombre, fuente = "cdl", "USDA NASS Cropland Data Layer (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        anios = []
        for it in _buscar_items("usda-cdl", p["bbox"], "2008-01-01", p["fin"], 40):
            if "cropland" not in it.assets:  # hay también items de "cultivated" y de frecuencias
                continue
            it = _firmar(it)
            a = it.assets["cropland"]
            arr, _ = _leer_ventana(a.href, p["bbox"])
            clases = {int(c["value"]): c["description"] for c in a.extra_fields.get("classification:classes", [])}
            vals, cuentas = np.unique(arr[np.isfinite(arr)].astype(int), return_counts=True)
            total = cuentas.sum()
            if total == 0:
                continue
            dist = {clases.get(int(v), str(int(v))): round(float(c) / total * 100, 1) for v, c in zip(vals, cuentas, strict=True)}
            anios.append({"anio": int(_fecha_item(it)[:4]), "distribucion": dict(sorted(dist.items(), key=lambda x: -x[1]))})
        if not anios:
            raise ValueError("sin datos CDL")
        return {"producto": "CDL", "anios": sorted(anios, key=lambda x: x["anio"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        raise FileNotFoundError("sin ejemplo sintético: CDL es un dato observado")


class Naip(Conector):
    """NDVI de ~1 m a partir de NAIP (fotografía aérea con infrarrojo cercano): casi 'verdad de campo' visual."""

    nombre, fuente = "naip", "USDA NAIP ~1 m (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        items = _buscar_items("naip", p["bbox"], "2018-01-01", p["fin"], 6)
        if not items:
            raise ValueError("sin imágenes NAIP")
        it = sorted(items, key=lambda i: i.datetime or i.properties.get("datetime"))[-1]  # la más reciente
        it = _firmar(it)
        import rasterio
        from rasterio.warp import transform_bounds
        from rasterio.windows import from_bounds

        with rasterio.open(it.assets["image"].href) as src:
            b = transform_bounds("EPSG:4326", src.crs, *p["bbox"])
            win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
            rojo = src.read(1, window=win).astype("float64")
            nir = src.read(4, window=win).astype("float64")
        ndvi = np.where((nir + rojo) > 0, (nir - rojo) / (nir + rojo), np.nan)
        paso = max(1, ndvi.shape[0] // 400)  # se guarda reducido (≈ 400 px) para no inflar el archivo
        h, w = (ndvi.shape[0] // paso) * paso, (ndvi.shape[1] // paso) * paso
        red = np.nanmean(ndvi[:h, :w].reshape(h // paso, paso, w // paso, paso), axis=(1, 3))
        return {"producto": "NAIP NDVI", "unidad": "NDVI", "resolucion_m": round(paso * 0.6, 1), "fecha": _fecha_item(it), "bbox": p["bbox"],
                "valores": [[None if not np.isfinite(x) else float(x) for x in fila] for fila in red]}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        raise FileNotFoundError("sin ejemplo sintético: NAIP es una imagen observada")


class NassPrecios(Conector):
    """Precio recibido por el productor en EE. UU. (USDA NASS Quick Stats): contexto del mercado T-MEC para maíz/frijol/sorgo.

    Necesita una llave gratuita en la variable de entorno NASS_API_KEY (https://quickstats.nass.usda.gov/api).
    Sin llave el conector queda como pendiente: nunca se inventan precios (regla dura 1).
    """

    nombre, fuente = "nass_precios", "USDA NASS Quick Stats"
    URL = "https://quickstats.nass.usda.gov/api/api_GET/"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import os

        from .base import ConectorNoConfigurado

        llave = os.environ.get("NASS_API_KEY")
        if not llave:
            raise ConectorNoConfigurado("falta NASS_API_KEY (llave gratuita de USDA NASS)")
        r = client.get(self.URL, params={"key": llave, "commodity_desc": p.get("producto", "CORN"), "statisticcat_desc": "PRICE RECEIVED",
                                         "agg_level_desc": "NATIONAL", "freq_desc": "MONTHLY", "year__GE": p.get("desde", "2021"), "format": "JSON"}, timeout=60)
        r.raise_for_status()
        return r.json()

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return [{"periodo": f"{d['year']}-{d['reference_period_desc']}", "valor": float(d["Value"].replace(",", "")), "unidad": d["unit_desc"]}
                for d in crudo.get("data", []) if d.get("Value", "").replace(",", "").replace(".", "", 1).isdigit()]

    def fallback_sintetico(self, **p: Any) -> Any:
        raise FileNotFoundError("sin ejemplo sintético: precio de mercado pendiente de llave NASS")
