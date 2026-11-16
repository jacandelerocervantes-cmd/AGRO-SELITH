"""Conectores concretos. Abiertos y verificados en vivo: POWER, Open-Meteo, SoilGrids, STAC.
SIAP, SNIIM y Monitor de Sequía: URL por variable de entorno (no verificados en vivo)."""

from __future__ import annotations

import csv
import io
import os
from datetime import date, timedelta
from typing import Any

import httpx

from .base import Conector, ConectorNoConfigurado

MISSING = -999.0


def _f(x: Any) -> float | None:
    return None if x is None or float(x) <= MISSING else float(x)


def _fecha(s: str) -> str:
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


class NasaPower(Conector):
    nombre, fuente = "nasa_power", "NASA POWER (power.larc.nasa.gov)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        r = client.get(
            "https://power.larc.nasa.gov/api/temporal/daily/point",
            params={
                "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,ALLSKY_SFC_SW_DWN",
                "community": "AG", "format": "JSON",
                "latitude": p["lat"], "longitude": p["lon"],
                "start": p["inicio"].replace("-", ""), "end": p["fin"].replace("-", ""),
            },
        )
        r.raise_for_status()
        return r.json()

    def parsear(self, crudo: Any, **p: Any) -> list[dict[str, Any]]:
        d = crudo["properties"]["parameter"]
        return [
            {
                "fecha": _fecha(k), "precip_mm": _f(d["PRECTOTCORR"][k]), "tmax": _f(d["T2M_MAX"][k]),
                "tmin": _f(d["T2M_MIN"][k]), "rad_mj": _f(d["ALLSKY_SFC_SW_DWN"][k]), "et0_mm": None,
            }
            for k in sorted(d["PRECTOTCORR"])
        ]


class OpenMeteoERA5(Conector):
    nombre, fuente = "open_meteo_era5", "Open-Meteo archivo ERA5 (open-meteo.com)"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        r = client.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": p["lat"], "longitude": p["lon"],
                "start_date": p["inicio"], "end_date": p["fin"], "timezone": "America/Merida",
                "daily": "precipitation_sum,temperature_2m_max,temperature_2m_min,"
                "et0_fao_evapotranspiration,shortwave_radiation_sum",
            },
        )
        r.raise_for_status()
        return r.json()

    def parsear(self, crudo: Any, **p: Any) -> list[dict[str, Any]]:
        d = crudo["daily"]
        return [
            {
                "fecha": d["time"][i], "precip_mm": d["precipitation_sum"][i],
                "tmax": d["temperature_2m_max"][i], "tmin": d["temperature_2m_min"][i],
                "rad_mj": d["shortwave_radiation_sum"][i],
                "et0_mm": d["et0_fao_evapotranspiration"][i],
            }
            for i in range(len(d["time"]))
        ]


class SoilGrids(Conector):
    """Suelo global (prior). En terreno kárstico es poco fiable: se marca baja confianza (plan §11)."""

    nombre, fuente = "soilgrids", "ISRIC SoilGrids v2.0 (rest.isric.org)"
    PROPS = ("phh2o", "soc", "clay", "sand", "silt")

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        r = client.get(
            "https://rest.isric.org/soilgrids/v2.0/properties/query",
            params=[("lon", p["lon"]), ("lat", p["lat"]), ("depth", "0-5cm"), ("value", "mean")]
            + [("property", x) for x in self.PROPS],
            timeout=60.0,
        )
        r.raise_for_status()
        return r.json()

    def fallback_sintetico(self, **p: Any) -> Any:
        # SINTÉTICO y sin valores inventados: estructura con "sin dato" (None) para cada propiedad.
        capas = [
            {"name": n, "unit_measure": {"d_factor": 1}, "depths": [{"values": {"mean": None}}]}
            for n in self.PROPS
        ]
        return {"properties": {"layers": capas}}

    def parsear(self, crudo: Any, **p: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for capa in crudo["properties"]["layers"]:
            m = capa["depths"][0]["values"]["mean"]
            fac = capa["unit_measure"]["d_factor"] or 1
            out[capa["name"]] = None if m is None else m / fac
        out["baja_confianza_karst"] = True
        return out


class StacSentinel(Conector):
    """Metadatos de escenas (nubosidad) vía STAC de Planetary Computer; sin descarga de píxeles."""

    nombre, fuente = "stac_planetary", "Microsoft Planetary Computer STAC"

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        r = client.post(
            "https://planetarycomputer.microsoft.com/api/stac/v1/search",
            json={
                "collections": [p.get("coleccion", "sentinel-2-l2a")], "bbox": p["bbox"],
                "datetime": f"{p['inicio']}/{p['fin']}", "limit": p.get("limite", 100),
            },
        )
        r.raise_for_status()
        return r.json()

    def parsear(self, crudo: Any, **p: Any) -> list[dict[str, Any]]:
        return [
            {
                "id": f["id"], "fecha": f["properties"]["datetime"][:10],
                "nubosidad_pct": f["properties"].get("eo:cloud_cover"),
                "plataforma": f["properties"].get("platform"),
            }
            for f in crudo["features"]
        ]


class _CsvConfigurable(Conector):
    env: str

    def fetch(self, client: httpx.Client, **p: Any) -> Any:
        url = os.environ.get(self.env)
        if not url:
            raise ConectorNoConfigurado(f"defina {self.env} con la URL del CSV abierto")
        r = client.get(url)
        r.raise_for_status()
        return r.text

    @staticmethod
    def _filas(crudo: Any) -> list[dict[str, str]]:
        return list(csv.DictReader(io.StringIO(crudo)))


class Siap(_CsvConfigurable):
    """Rendimientos SIAP (datos abiertos). Columnas: Anio, Nommunicipio, Nomcultivo, Rendimiento, ..."""

    nombre, fuente, env = "siap", "SIAP datos abiertos (SADER)", "SIAP_CSV_URL"

    def parsear(self, crudo: Any, **p: Any) -> list[dict[str, Any]]:
        mun, cult = p.get("municipio"), p.get("cultivo")
        return [
            {"anio": int(r["Anio"]), "municipio": r["Nommunicipio"], "cultivo": r["Nomcultivo"],
             "rendimiento_t_ha": float(r["Rendimiento"]), "modalidad": r.get("Nommodalidad", "")}
            for r in self._filas(crudo)
            if (mun is None or r["Nommunicipio"] == mun) and (cult is None or r["Nomcultivo"] == cult)
        ]

    def fallback_sintetico(self, **p: Any) -> Any:  # SINTÉTICO: forma de los datos, no sus valores
        return "Anio,Nommunicipio,Nomcultivo,Rendimiento,Nommodalidad\n" + "\n".join(
            f"{a},Tizimín,{c},{v},Temporal" for a in (2021, 2022, 2023)
            for c, v in (("Maíz grano", 0.8), ("Frijol", 0.5), ("Calabaza", 0.6))
        )


class Sniim(_CsvConfigurable):
    """Precios de abasto (Mérida). Sin API formal: CSV exportado por URL configurable; si falla, SIAP."""

    nombre, fuente, env = "sniim", "SNIIM (Secretaría de Economía)", "SNIIM_CSV_URL"

    def parsear(self, crudo: Any, **p: Any) -> list[dict[str, Any]]:
        return [
            {"central": r["central"], "producto": r["producto"], "fecha": r["fecha"],
             "precio_min": float(r["precio_min"]), "precio_max": float(r["precio_max"]),
             "precio_frec": float(r["precio_frec"])}
            for r in self._filas(crudo)
        ]

    def fallback_sintetico(self, **p: Any) -> Any:  # SINTÉTICO
        d0 = date(2023, 6, 1)
        filas = [
            f"Mérida,{prod},{d0 + timedelta(days=7 * i)},{lo},{hi},{(lo + hi) / 2}"
            for prod, lo, hi in (("Maíz", 6, 8), ("Frijol", 20, 26), ("Chile habanero", 30, 45))
            for i in range(4)
        ]
        return "central,producto,fecha,precio_min,precio_max,precio_frec\n" + "\n".join(filas)


class MonitorSequia(_CsvConfigurable):
    """Monitor de Sequía de México (SMN/CONAGUA): categoría D0-D4 por municipio y quincena."""

    nombre, fuente, env = "monitor_sequia", "Monitor de Sequía de México (SMN/CONAGUA)", "SEQUIA_CSV_URL"

    def parsear(self, crudo: Any, **p: Any) -> list[dict[str, Any]]:
        return [
            {"municipio": r["municipio"], "fecha": r["fecha"], "categoria": r["categoria"]}
            for r in self._filas(crudo)
        ]

    def fallback_sintetico(self, **p: Any) -> Any:  # SINTÉTICO
        return "municipio,fecha,categoria\nTizimín,2023-07-15,D0\nTizimín,2023-07-31,D1\nTizimín,2023-08-15,D2\n"


TODOS = (NasaPower, OpenMeteoERA5, SoilGrids, StacSentinel, Siap, Sniim, MonitorSequia)
