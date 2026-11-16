# SELITH AGRO — NASA Space Apps 2026 · "Field Shift: Adapting Farms with NASA Data"

Web app (español / English) para que un productor de Tizimín, Yucatán, dibuje su parcela sobre un mapa satelital y converse (voz o texto) con un asistente que compara **tres estrategias de rotación** —la actual y dos alternativas— con observaciones de la NASA. Expertos agrónomos revisan las respuestas por área. **Apoya, no reemplaza, el criterio del productor.**

> Estado honesto: los parámetros agronómicos son **provisionales** (cada uno en `knowledge/` lleva su fuente y estatus) y el backtest contra rendimientos reales **no está validado**. Todo dato de ejemplo se rotula "ejemplo" en la interfaz.

## Qué hay
| Pieza | Dónde |
|---|---|
| Web app (React + MapLibre, PWA, ES/EN) | `apps/web` |
| API (FastAPI + PostGIS) | `apps/api` |
| Motor determinista de rotación (Python) y su copia en el navegador (TypeScript, con paridad probada) | `packages/engine`, `apps/web/src/engine` |
| Conectores de datos (NASA, FAO GAEZ, USDA) y fusión a rejilla de 100 m | `pipelines/milpa_pipelines` |
| Base agronómica (YAML con fuente y estatus) | `knowledge/` |
| Validación de productos globales con mediciones de EE. UU. (condado de Hidalgo, TX) | `docs/validacion_eeuu.json`, `pipelines/milpa_pipelines/validacion_eeuu.py` |

## Datos que usa
NASA: Landsat, MODIS (NDVI, temperatura, evapotranspiración), SRTM/NASADEM, GPM IMERG, SMAP, GLDAS, ECOSTRESS, GRACE-FO, GEDI y NASA POWER. Además Sentinel-2 (ESA), FAO GAEZ v4, SoilGrids, ERA5 (Open-Meteo) y, como referencia, USDA SSURGO, CDL y NAIP. El motor es determinista; el modelo de lenguaje solo explica, nunca decide.

## Correr la demo (sin ninguna llave)
Requisitos: Docker Desktop, [uv](https://docs.astral.sh/uv/), Node 20+.

```bash
docker compose up -d db
cd apps/api && uv run alembic upgrade head && cd ../..
uv run python apps/api/seed.py knowledge
uv run python scripts/cargar_fusion.py demo
uv run python scripts/cargar_capas.py demo
```

API y web (dos terminales):

```bash
uv run uvicorn milpa_api.main:app --app-dir apps/api
```

```bash
cd apps/web && npm install && npm run dev
```

Abre http://localhost:5173 . El acceso es simulado (usuarios de prueba, sin correo ni contraseña; solo con `MILPA_DEMO=1`, **nunca en producción con datos reales**).

## Datos NASA con cuenta (opcional)
Landsat, MODIS y SRTM/NASADEM se leen de Microsoft Planetary Computer **sin llave** (hay datos grabados de Tizimín). IMERG, SMAP, GLDAS, ECOSTRESS, GRACE-FO y GEDI requieren una cuenta gratuita de [NASA Earthdata](https://urs.earthdata.nasa.gov); las credenciales van solo en variables de entorno:

```powershell
$env:EARTHDATA_USERNAME = 'usuario'
$env:EARTHDATA_PASSWORD = 'contraseña'
uv run python scripts/cargar_capas.py auto
```

Sin cuenta, esas capas salen como ejemplo rotulado. Nunca guardes credenciales en el repositorio (`.env` está ignorado).

## Asistente de IA (opcional)
Con `ANTHROPIC_API_KEY` el chat usa Claude (Sonnet 5.5, respaldo Haiku 5.5, `config/llm.yaml`). Sin llave responde con un resumen determinista de las tres estrategias. El texto del usuario se trata como dato (saneado y delimitado) y la respuesta del modelo se filtra.

## Seguridad y límites de uso
Límites por usuario/IP (chat, capas, parcelas, global) y tope diario de preguntas, configurables con `MILPA_LIM_*` (ver `apps/api/milpa_api/seguridad.py`). Detrás de un proxy propio, `MILPA_PROXY=1` hace que se use `X-Forwarded-For`. CI con pruebas, auditoría de dependencias y escaneo de secretos.

## Mapa sin señal
En la pantalla del mapa, **"Guardar este mapa para usarlo sin señal"** descarga las teselas de una región pequeña (≈ 1 km alrededor del centro, tope de 450 por zoom) y el service worker las conserva 30 días. La región es pequeña a propósito: los proveedores de imágenes (Esri, OpenStreetMap) no permiten descargas masivas.

## Pruebas
```bash
uv run pytest                      # Python (usa la base milpa_test, no borra la de desarrollo)
cd apps/web && npx vitest run      # paridad del motor TypeScript con Python
cd apps/web && npx playwright test # extremo a extremo (productor, experto, sin señal)
```

## Datos y atribuciones
Los datos de la NASA, ESA, FAO, USDA y demás agencias tienen sus propios términos de uso; el fondo satelital (Esri) y OpenStreetMap requieren atribución, y Esri revisión de términos para uso comercial.
