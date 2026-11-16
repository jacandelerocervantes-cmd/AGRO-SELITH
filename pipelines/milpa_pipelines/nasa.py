"""Conectores de observaciones de la NASA (y socios) para el desafío Field Shift.

Cada conector devuelve una respuesta cruda NORMALIZADA, de dos formas:
  serie:   {"producto","unidad","resolucion_m","serie":[{"fecha","valor"}]}            (valor puntual o promedio de la zona)
  raster:  {"producto","unidad","resolucion_m","bbox":[w,s,e,n],"valores":[[...]]}      (filas de norte a sur)
  escenas: {"producto","unidad","resolucion_m","escenas":[{"fecha","bbox","valores"}]}  (varias imágenes)

Acceso:
  - Sin llave (Microsoft Planetary Computer, STAC): MODIS NDVI, Landsat NDVI, SRTM/NASADEM.
  - Con cuenta gratuita NASA Earthdata (EARTHDATA_USERNAME / EARTHDATA_PASSWORD): IMERG, SMAP, GLDAS,
    ECOSTRESS, GRACE-FO, GEDI. Sin cuenta usan caché/fixtures reales o, si no hay, un ejemplo SINTÉTICO rotulado.
Las capas que requieren cuenta Earthdata caen a datos de ejemplo rotulados si no hay credenciales.
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from .base import CACHE, Conector, ConectorNoConfigurado

MPC_STAC = "https://planetarycomputer.microsoft.com/api/stac/v1"


def _earthdata() -> Any:
    if not (os.environ.get("EARTHDATA_USERNAME") and os.environ.get("EARTHDATA_PASSWORD")) and not os.environ.get(
        "EARTHDATA_TOKEN"
    ):
        raise ConectorNoConfigurado("cree una cuenta gratuita en NASA Earthdata y defina EARTHDATA_USERNAME/PASSWORD")
    try:
        import earthaccess
    except ImportError as e:  # pragma: no cover
        raise ConectorNoConfigurado("falta instalar earthaccess") from e
    earthaccess.login(strategy="environment")
    return earthaccess


def _caja(lat: float, lon: float, grados: float = 0.05) -> tuple[float, float, float, float]:
    return (lon - grados, lat - grados, lon + grados, lat + grados)


def _fecha_gr(r: dict[str, Any]) -> str:
    return r["umm"]["TemporalExtent"]["RangeDateTime"]["BeginningDateTime"][:10]


def _nearest(da: Any, lat: float, lon: float) -> float | None:
    v = float(da.sel(lat=lat, lon=lon, method="nearest").values)
    return None if math.isnan(v) or v <= -9990 else v


# ---------------------------------------------------------------- sintéticos (rotulados)
def _estacional(mes: int, pico: tuple[int, ...] = (6, 7, 8, 9, 10)) -> float:
    return 1.0 if mes in pico else 0.25


def _dias(inicio: str, fin: str, paso: int = 1) -> list[date]:
    d0, d1 = date.fromisoformat(inicio), date.fromisoformat(fin)
    return [d0 + timedelta(days=i) for i in range(0, (d1 - d0).days + 1, paso)]


def _sint_serie(nombre: str, unidad: str, res: int, inicio: str, fin: str, paso: int, f: Any, **extra: Any) -> dict[str, Any]:
    rng = np.random.default_rng(sum(map(ord, nombre)))
    return {"producto": nombre, "unidad": unidad, "resolucion_m": res, "sintetico": True,
            "serie": [{"fecha": d.isoformat(), "valor": float(f(d, rng))} for d in _dias(inicio, fin, paso)], **extra}


def _sint_raster(nombre: str, unidad: str, res: int, bbox: list[float], base: float, pendiente: float, ruido: float, n: int = 24) -> dict[str, Any]:
    rng = np.random.default_rng(sum(map(ord, nombre)))
    yy, xx = np.mgrid[0:n, 0:n]
    v = base + pendiente * (xx / n) + rng.normal(0, ruido, (n, n))
    return {"producto": nombre, "unidad": unidad, "resolucion_m": res, "bbox": bbox, "sintetico": True,
            "valores": [[float(x) for x in fila] for fila in v]}


# ---------------------------------------------------------------- base STAC (Planetary Computer)
def _leer_ventana(href: str, bbox: list[float]) -> tuple[np.ndarray, list[float]]:
    """Lee la ventana del bbox (lon/lat) de un COG; devuelve valores enmascarados (nan) y su bbox WGS84 aprox."""
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import from_bounds

    with rasterio.open(href) as src:
        b = transform_bounds("EPSG:4326", src.crs, *bbox)
        win = from_bounds(*b, transform=src.transform).round_offsets().round_lengths()
        arr = src.read(1, window=win, masked=True).astype("float64")
        arr = np.ma.filled(arr, np.nan)
    return arr, bbox


def _buscar_items(coleccion: str, bbox: list[float], inicio: str, fin: str, limite: int, query: dict[str, Any] | None = None) -> list[Any]:
    from pystac_client import Client

    cat = Client.open(MPC_STAC)
    s = cat.search(collections=[coleccion], bbox=bbox, datetime=f"{inicio}/{fin}", limit=limite, query=query or {})
    return list(s.items())[:limite]


def _fecha_item(it: Any) -> str:
    """Fecha de la escena; los productos compuestos (MODIS) traen start_datetime en vez de datetime."""
    if it.datetime is not None:
        return str(it.datetime.date().isoformat())
    return str(it.properties["start_datetime"])[:10]


def _firmar(item: Any) -> Any:
    import planetary_computer as pc

    return pc.sign(item)


class ModisNdvi(Conector):
    nombre, fuente = "modis_ndvi", "NASA MODIS MOD13Q1 v061 (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        serie = []
        for it in _buscar_items("modis-13Q1-061", p["bbox"], p["inicio"], p["fin"], 60):
            it = _firmar(it)
            arr, _ = _leer_ventana(it.assets["250m_16_days_NDVI"].href, p["bbox"])
            v = np.nanmean(arr) * 0.0001 if np.isfinite(arr).any() else None
            serie.append({"fecha": _fecha_item(it), "valor": None if v is None else float(v)})
        if not serie:
            raise ValueError("sin escenas MODIS")
        return {"producto": "MOD13Q1 NDVI", "unidad": "NDVI", "resolucion_m": 250, "serie": sorted(serie, key=lambda x: x["fecha"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("MOD13Q1 NDVI (ejemplo)", "NDVI", 250, p["inicio"], p["fin"], 16,
                           lambda d, r: 0.35 + 0.35 * _estacional(d.month) + r.normal(0, .03))


class LandsatNdvi(Conector):
    nombre, fuente = "landsat_ndvi", "NASA/USGS Landsat 8-9 C2 L2 (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        escenas = []
        for it in _buscar_items("landsat-c2-l2", p["bbox"], p["inicio"], p["fin"], 40, {"eo:cloud_cover": {"lt": 40}}):
            it = _firmar(it)
            rojo, _ = _leer_ventana(it.assets["red"].href, p["bbox"])
            nir, _ = _leer_ventana(it.assets["nir08"].href, p["bbox"])
            qa, _ = _leer_ventana(it.assets["qa_pixel"].href, p["bbox"])
            h, w = min(rojo.shape[0], nir.shape[0], qa.shape[0]), min(rojo.shape[1], nir.shape[1], qa.shape[1])
            rojo, nir, qa = rojo[:h, :w] * 2.75e-05 - 0.2, nir[:h, :w] * 2.75e-05 - 0.2, qa[:h, :w]
            nube = (qa.astype("int64") & 0b11110) != 0  # bits: dilatada, cirro, nube, sombra
            ndvi = np.where(nube | ((nir + rojo) == 0), np.nan, (nir - rojo) / (nir + rojo))
            ndvi = np.where((ndvi >= -1) & (ndvi <= 1), ndvi, np.nan)  # píxeles con reflectancia inválida
            if np.isfinite(ndvi).mean() < 0.5:
                continue
            escenas.append({"fecha": it.datetime.date().isoformat(), "bbox": p["bbox"],
                            "valores": [[None if not np.isfinite(x) else float(x) for x in fila] for fila in ndvi]})
        if not escenas:
            raise ValueError("sin escenas Landsat útiles")
        return {"producto": "Landsat NDVI", "unidad": "NDVI", "resolucion_m": 30, "escenas": sorted(escenas, key=lambda e: e["fecha"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        fechas = _dias(p["inicio"], p["fin"], 16)
        return {"producto": "Landsat NDVI (ejemplo)", "unidad": "NDVI", "resolucion_m": 30, "sintetico": True,
                "escenas": [{"fecha": d.isoformat(), "bbox": p["bbox"],
                             "valores": _sint_raster("landsat" + d.isoformat(), "NDVI", 30, p["bbox"],
                                                     0.35 + 0.35 * _estacional(d.month), 0.05, 0.04)["valores"]} for d in fechas]}


class SrtmRelieve(Conector):
    nombre, fuente = "srtm_relieve", "NASA SRTM / NASADEM 30 m (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        items = _buscar_items("nasadem", p["bbox"], "2000-01-01", "2001-01-01", 1)
        if not items:
            raise ValueError("sin tesela NASADEM")
        arr, bbox = _leer_ventana(_firmar(items[0]).assets["elevation"].href, p["bbox"])
        return {"producto": "NASADEM elevación", "unidad": "m", "resolucion_m": 30, "bbox": bbox,
                "valores": [[None if not np.isfinite(x) else float(x) for x in fila] for fila in arr]}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_raster("SRTM elevación (ejemplo)", "m", 30, p["bbox"], 24.0, 3.0, 0.4)


# ---------------------------------------------------------------- Earthdata (requieren cuenta gratuita)
class Imerg(Conector):
    nombre, fuente = "imerg", "NASA GPM IMERG diario (GPM_3IMERGDL v07)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import xarray as xr

        ea = _earthdata()
        res = ea.search_data(short_name="GPM_3IMERGDL", version="07", bounding_box=_caja(p["lat"], p["lon"]),
                             temporal=(p["inicio"], p["fin"]), count=400)
        res = res[::4]  # 1 de cada 4 días: suficiente para la tendencia de lluvia
        serie = []
        for r, f in zip(res, ea.open(res), strict=False):
            with xr.open_dataset(f, engine="h5netcdf") as ds:
                serie.append({"fecha": _fecha_gr(r), "valor": _nearest(ds["precipitation"].isel(time=0), p["lat"], p["lon"])})
        if not serie:
            raise ValueError("sin granulos IMERG")
        return {"producto": "IMERG precipitación diaria", "unidad": "mm/día", "resolucion_m": 10000, "serie": serie}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("IMERG precipitación (ejemplo)", "mm/día", 10000, p["inicio"], p["fin"], 1,
                           lambda d, r: max(0.0, r.gamma(0.6, 7.0) * _estacional(d.month)))


class Smap(Conector):
    nombre, fuente = "smap", "NASA SMAP L3 humedad del suelo enriquecida (SPL3SMP_E v006)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import xarray as xr

        ea = _earthdata()
        res = ea.search_data(short_name="SPL3SMP_E", bounding_box=_caja(p["lat"], p["lon"], 0.2),
                             temporal=(p["inicio"], p["fin"]), count=400)
        res = res[::6]  # ~1 de cada 6 días: basta para la tendencia y evita bajar cientos de archivos
        serie = []
        for r, f in zip(res, ea.open(res), strict=False):
            with xr.open_dataset(f, group="Soil_Moisture_Retrieval_Data_AM", engine="h5netcdf", phony_dims="sort") as ds:
                lat, lon, sm = ds["latitude"].values, ds["longitude"].values, ds["soil_moisture"].values
                d = (lat - p["lat"]) ** 2 + (lon - p["lon"]) ** 2
                i = np.unravel_index(np.nanargmin(np.where(lat > -9990, d, np.nan)), d.shape)
                v = float(sm[i])
                serie.append({"fecha": _fecha_gr(r), "valor": None if v <= -9990 or math.isnan(v) else v})
        if not serie:
            raise ValueError("sin granulos SMAP")
        return {"producto": "SMAP humedad superficial", "unidad": "m³/m³", "resolucion_m": 9000, "serie": serie}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("SMAP humedad (ejemplo)", "m³/m³", 9000, p["inicio"], p["fin"], 3,
                           lambda d, r: 0.12 + 0.18 * _estacional(d.month) + r.normal(0, .02))


class Gldas(Conector):
    nombre, fuente = "gldas", "NASA GLDAS Noah 0.25° mensual (GLDAS_NOAH025_M v2.1)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import xarray as xr

        ea = _earthdata()
        res = ea.search_data(short_name="GLDAS_NOAH025_M", version="2.1", bounding_box=_caja(p["lat"], p["lon"], 0.3),
                             temporal=(p["inicio"], p["fin"]), count=200)
        serie, et = [], []
        for r, f in zip(res, ea.open(res), strict=False):
            with xr.open_dataset(f, engine="h5netcdf") as ds:
                fe = _fecha_gr(r)
                serie.append({"fecha": fe, "valor": _nearest(ds["SoilMoi0_10cm_inst"].isel(time=0), p["lat"], p["lon"])})
                et.append({"fecha": fe, "valor": _nearest(ds["Evap_tavg"].isel(time=0), p["lat"], p["lon"])})
        if not serie:
            raise ValueError("sin granulos GLDAS")
        return {"producto": "GLDAS humedad 0-10 cm", "unidad": "kg/m²", "resolucion_m": 25000, "serie": serie, "serie_et": et}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        s = _sint_serie("GLDAS humedad (ejemplo)", "kg/m²", 25000, p["inicio"], p["fin"], 30,
                        lambda d, r: 12 + 14 * _estacional(d.month) + r.normal(0, 1))
        s["serie_et"] = [{"fecha": x["fecha"], "valor": 1e-5 * x["valor"]} for x in s["serie"]]
        return s


class GraceFo(Conector):
    nombre, fuente = "grace", "NASA GRACE-FO mascones (agua equivalente, JPL RL06.1)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import xarray as xr

        ea = _earthdata()
        res = ea.search_data(short_name="TELLUS_GRAC-GRFO_MASCON_CRI_GRID_RL06.1_V3", count=5)
        if not res:
            raise ValueError("sin producto GRACE")
        with xr.open_dataset(ea.open(res[:1])[0], engine="h5netcdf") as ds:
            lon = p["lon"] % 360
            da = ds["lwe_thickness"].sel(lat=p["lat"], lon=lon, method="nearest")
            serie = [{"fecha": str(t)[:10], "valor": float(v)} for t, v in zip(da["time"].values, da.values, strict=True)
                     if not math.isnan(float(v))]
        return {"producto": "GRACE-FO agua equivalente", "unidad": "cm", "resolucion_m": 300000,
                "serie": [s for s in serie if p["inicio"] <= s["fecha"] <= p["fin"]] or serie[-24:]}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("GRACE-FO agua almacenada (ejemplo)", "cm", 300000, p["inicio"], p["fin"], 30,
                           lambda d, r: -0.02 * ((d - date.fromisoformat(p["inicio"])).days / 30) + 3 * math.sin(d.month / 12 * 6.28) + r.normal(0, .4))


class Ecostress(Conector):
    nombre, fuente = "ecostress", "NASA ECOSTRESS L2T LSTE (temperatura superficial) y L3T JET (ET)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import rasterio
        from rasterio.io import MemoryFile
        from rasterio.warp import transform

        ea = _earthdata()
        lst: list[dict[str, Any]] = []
        res = ea.search_data(short_name="ECO_L2T_LSTE", bounding_box=_caja(p["lat"], p["lon"], 0.02),
                             temporal=(p["inicio"], p["fin"]), count=60)
        for r in res:
            for f in ea.open([r]):
                if not str(getattr(f, "path", getattr(f, "full_name", ""))).endswith("_LST.tif"):
                    continue
                with MemoryFile(f.read()) as mf, mf.open() as src:
                    xs, ys = transform("EPSG:4326", src.crs, [p["lon"]], [p["lat"]])
                    v = next(src.sample([(xs[0], ys[0])]))[0]
                    if np.isfinite(v) and v > 0:
                        lst.append({"fecha": _fecha_gr(r), "valor": float(v) - 273.15})
        if not lst:
            raise ValueError("sin escenas ECOSTRESS útiles")
        _ = rasterio  # lectura de ET (ECO_L3T_JET) queda como ampliación
        return {"producto": "ECOSTRESS LST", "unidad": "°C", "resolucion_m": 70, "serie": sorted(lst, key=lambda x: x["fecha"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("ECOSTRESS LST (ejemplo)", "°C", 70, p["inicio"], p["fin"], 5,
                           lambda d, r: 31 + 8 * math.sin((d.month - 2) / 12 * 3.14) + r.normal(0, 1.5))


class Gedi(Conector):
    nombre, fuente = "gedi", "NASA GEDI L4B biomasa aérea en cuadrícula de 1 km (descarga grande)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        import rasterio
        from rasterio.warp import transform_bounds  # noqa: F401

        ea = _earthdata()
        res = ea.search_data(short_name="GEDI_L4B_GriddedBiomass_V2_1", count=1)
        if not res:
            raise ValueError("sin producto GEDI L4B")
        destino = Path(CACHE) / "gedi"
        destino.mkdir(parents=True, exist_ok=True)
        archivos = [a for a in ea.download(res, str(destino)) if str(a).endswith("MU.tif")]
        if not archivos:
            raise ValueError("el producto GEDI no trae el mapa de media")
        with rasterio.open(archivos[0]) as src:
            v = next(src.sample([(p["lon"], p["lat"])]))[0]
        return {"producto": "GEDI L4B biomasa", "unidad": "Mg/ha", "resolucion_m": 1000,
                "serie": [{"fecha": p["fin"], "valor": None if v < 0 or not np.isfinite(v) else float(v)}]}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return {"producto": "GEDI biomasa (ejemplo)", "unidad": "Mg/ha", "resolucion_m": 1000, "sintetico": True,
                "serie": [{"fecha": p["fin"], "valor": None}]}


class Sentinel2Ndvi(Conector):
    """NDVI de 10 m de Sentinel-2 (ESA, agencia socia): la mejor resolución disponible sin llave para una parcela."""

    nombre, fuente = "sentinel2_ndvi", "ESA Copernicus Sentinel-2 L2A 10 m (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        escenas = []
        for it in _buscar_items("sentinel-2-l2a", p["bbox"], p["inicio"], p["fin"], 40, {"eo:cloud_cover": {"lt": 40}}):
            it = _firmar(it)
            rojo, _ = _leer_ventana(it.assets["B04"].href, p["bbox"])
            nir, _ = _leer_ventana(it.assets["B08"].href, p["bbox"])
            scl, _ = _leer_ventana(it.assets["SCL"].href, p["bbox"])  # 20 m
            scl = np.kron(scl, np.ones((2, 2)))  # a 10 m, por vecino más cercano
            h = min(rojo.shape[0], nir.shape[0], scl.shape[0])
            w = min(rojo.shape[1], nir.shape[1], scl.shape[1])
            # Línea base de procesamiento >= 04.00: reflectancia = (DN - 1000) / 10000
            off = 0.1 if str(it.properties.get("s2:processing_baseline", "00.00")) >= "04.00" else 0.0
            r, n, s = rojo[:h, :w] / 1e4 - off, nir[:h, :w] / 1e4 - off, scl[:h, :w]
            malo = np.isin(s, (0, 1, 3, 8, 9, 10, 11))  # sin dato, saturado, sombra, nubes y nieve
            ndvi = np.where(malo | ((n + r) == 0), np.nan, (n - r) / (n + r))
            ndvi = np.where((ndvi >= -1) & (ndvi <= 1), ndvi, np.nan)
            if np.isfinite(ndvi).mean() < 0.5:
                continue
            escenas.append({"fecha": _fecha_item(it), "bbox": p["bbox"],
                            "valores": [[None if not np.isfinite(x) else float(x) for x in fila] for fila in ndvi]})
        if not escenas:
            raise ValueError("sin escenas Sentinel-2 útiles")
        return {"producto": "Sentinel-2 NDVI", "unidad": "NDVI", "resolucion_m": 10, "escenas": sorted(escenas, key=lambda e: e["fecha"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        fechas = _dias(p["inicio"], p["fin"], 10)
        return {"producto": "Sentinel-2 NDVI (ejemplo)", "unidad": "NDVI", "resolucion_m": 10, "sintetico": True,
                "escenas": [{"fecha": d.isoformat(), "bbox": p["bbox"],
                             "valores": _sint_raster("s2" + d.isoformat(), "NDVI", 10, p["bbox"], 0.35 + 0.35 * _estacional(d.month), 0.05, 0.04)["valores"]}
                            for d in fechas]}


class ModisLst(Conector):
    """Temperatura de la superficie diurna de MODIS (NASA, 1 km, 8 días): sustituto sin llave de ECOSTRESS."""

    nombre, fuente = "modis_lst", "NASA MODIS MOD11A2 v061 temperatura superficial (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        serie = []
        for it in _buscar_items("modis-11A2-061", p["bbox"], p["inicio"], p["fin"], 60):
            it = _firmar(it)
            arr, _ = _leer_ventana(it.assets["LST_Day_1km"].href, p["bbox"])
            arr = np.where(arr > 0, arr, np.nan)  # 0 = sin dato
            v = float(np.nanmean(arr) * 0.02 - 273.15) if np.isfinite(arr).any() else None
            serie.append({"fecha": _fecha_item(it), "valor": v})
        if not serie:
            raise ValueError("sin escenas MODIS LST")
        return {"producto": "MOD11A2 LST diurna", "unidad": "°C", "resolucion_m": 1000, "serie": sorted(serie, key=lambda x: x["fecha"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("MODIS LST (ejemplo)", "°C", 1000, p["inicio"], p["fin"], 8,
                           lambda d, r: 31 + 8 * math.sin((d.month - 2) / 12 * 3.14) + r.normal(0, 1.5))


class ModisEt(Conector):
    """Evapotranspiración anual de MODIS (NASA MOD16A3GF, 500 m): demanda de agua real sin llave."""

    nombre, fuente = "modis_et", "NASA MODIS MOD16A3GF v061 evapotranspiración anual (vía Planetary Computer)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        serie = []
        for it in _buscar_items("modis-16A3GF-061", p["bbox"], "2018-01-01", p["fin"], 12):
            it = _firmar(it)
            arr, _ = _leer_ventana(it.assets["ET_500m"].href, p["bbox"])
            arr = np.where((arr >= 0) & (arr < 30000), arr, np.nan)  # >= 30000 = relleno
            v = float(np.nanmean(arr) * 0.1) if np.isfinite(arr).any() else None  # kg/m² = mm al año
            serie.append({"fecha": _fecha_item(it), "valor": v})
        if not serie:
            raise ValueError("sin datos MODIS ET")
        return {"producto": "MOD16A3GF ET anual", "unidad": "mm/año", "resolucion_m": 500, "serie": sorted(serie, key=lambda x: x["fecha"])}

    def parsear(self, crudo: Any, **p: Any) -> Any:
        return crudo

    def fallback_sintetico(self, **p: Any) -> Any:
        return _sint_serie("MODIS ET (ejemplo)", "mm/año", 500, "2018-01-01", p["fin"], 365, lambda d, r: 900 + r.normal(0, 60))


CAPAS_NASA: dict[str, Any] = {
    "ndvi_s2": Sentinel2Ndvi, "lst_modis": ModisLst, "et_modis": ModisEt,
    "imerg": Imerg, "smap": Smap, "gldas": Gldas, "ndvi_modis": ModisNdvi, "ndvi_landsat": LandsatNdvi,
    "srtm": SrtmRelieve, "ecostress": Ecostress, "grace": GraceFo, "gedi": Gedi,
}
