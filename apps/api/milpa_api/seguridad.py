"""Seguridad de la API: límites de uso, cabeceras y defensa contra inyección de instrucciones.

- Límites: ventana deslizante en memoria (ráfagas) + tope diario DURABLE por usuario en la base (costo del LLM).
  En despliegues con varias instancias la memoria no se comparte: el tope diario sí, porque vive en la base.
- Inyección: el texto del usuario es DATO. Se sanea, se delimita y se marca si parece una orden al modelo.
- Nada de esto decide por el productor: solo protege el servicio y el presupuesto.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import unicodedata
from collections import defaultdict, deque
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from .auth import Usuario, get_db, usuario_actual

log = logging.getLogger("milpa.seguridad")

# ---------------------------------------------------------------- límites de uso

_LOCK = threading.Lock()
_VENTANAS: dict[str, deque[float]] = defaultdict(deque)


def ip_cliente(request: Request) -> str:
    """IP del cliente. Solo se confía en X-Forwarded-For si MILPA_PROXY=1 (detrás de un proxy propio)."""
    if os.environ.get("MILPA_PROXY") == "1":
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()[:64]
    return request.client.host if request.client else "desconocida"


def _permitir(clave: str, maximo: int, ventana_s: float, ahora: float | None = None) -> float:
    """0 si se permite; si no, segundos que faltan para poder reintentar."""
    t = time.monotonic() if ahora is None else ahora
    with _LOCK:
        q = _VENTANAS[clave]
        while q and q[0] <= t - ventana_s:
            q.popleft()
        if len(q) >= maximo:
            return max(1.0, q[0] + ventana_s - t)
        q.append(t)
        if len(_VENTANAS) > 50_000:  # evita crecer sin fin
            for k in [k for k, v in _VENTANAS.items() if not v or v[-1] <= t - 3600][:10_000]:
                _VENTANAS.pop(k, None)
    return 0.0


def reiniciar_limites() -> None:
    with _LOCK:
        _VENTANAS.clear()


def _limite(nombre: str, defecto: int) -> int:
    try:
        return int(os.environ.get(f"MILPA_LIM_{nombre.upper()}", defecto))
    except ValueError:
        return defecto


def limitar(nombre: str, maximo: int, ventana_s: float = 60) -> Callable[..., None]:
    """Dependencia de FastAPI: ráfagas por usuario (o por IP si aún no hay usuario). Responde 429 con Retry-After."""

    def dep(request: Request) -> None:
        sujeto = request.headers.get("x-demo-login") or ip_cliente(request)
        espera = _permitir(f"{nombre}:{sujeto}", _limite(nombre, maximo), ventana_s)
        if espera:
            log.warning("límite %s excedido por %s", nombre, sujeto)
            raise HTTPException(429, "Demasiadas solicitudes. Espere un momento e intente de nuevo.",
                                headers={"Retry-After": str(int(espera) + 1)})

    return dep


def tope_diario_chat(u: Usuario = Depends(usuario_actual), db: Any = Depends(get_db)) -> None:
    """Máximo de preguntas por usuario en 24 h (cada una puede costar una llamada al LLM). Durable: se cuenta en la base."""
    maximo = _limite("chat_dia", 80)
    n = db.execute(
        """SELECT count(*) AS n FROM chat_message m JOIN chat_conversation c ON c.id=m.conversation_id
           WHERE c.user_id=%s AND m.rol='usuario' AND m.created_at > now() - interval '24 hours'""", (u.id,)).fetchone()["n"]
    if n >= maximo:
        raise HTTPException(429, "Llegó al máximo de preguntas de hoy. Vuelva mañana.", headers={"Retry-After": "3600"})


class CabecerasSeguras(BaseHTTPMiddleware):
    """Cabeceras de endurecimiento y límite general por IP (una API de datos no necesita más de unas decenas por segundo)."""

    async def dispatch(self, request: Request, call_next: Callable[[Request], Any]) -> Response:
        if request.url.path not in ("/salud",):
            espera = _permitir(f"global:{ip_cliente(request)}", _limite("global", 600), 60)
            if espera:
                return Response("Demasiadas solicitudes", status_code=429, headers={"Retry-After": str(int(espera) + 1)})
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Permissions-Policy", "camera=(), geolocation=(self), microphone=(self)")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp


# ---------------------------------------------------------------- inyección de instrucciones

_INVISIBLES = dict.fromkeys([0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069])

_PATRONES = [re.compile(p, re.IGNORECASE) for p in (
    r"ignor[ae]\w*\s+(todas?\s+)?(las\s+)?(instrucciones|reglas|indicaciones)",
    r"olvida\w*\s+(todo|lo\s+anterior|tus\s+instrucciones)",
    r"ignore\s+(all\s+|the\s+)?(previous|prior|above)\s+(instructions|rules|prompts?)",
    r"disregard\s+(your|the|all)\s+(instructions|rules|system)",
    r"(muestra|revela|dime|repite|imprime|show|reveal|print|repeat)\w*\s+.{0,30}(prompt|instrucciones|system|sistema)",
    r"\b(system|developer|assistant)\s*(prompt|message|role)\b",
    r"act[uú]a\s+como|finge\s+(ser|que)|pretend\s+(to\s+be|you)|you\s+are\s+now|ahora\s+eres",
    r"\bjailbreak\b|\bDAN\b|modo\s+desarrollador|developer\s+mode",
    r"</?\s*(contexto|pregunta|system|instructions?)[^>]*>",
    r"(api[_ -]?key|llave\s+de\s+la\s+api|contrase[ñn]a|password|token|secret)",
)]


def sanear_texto(texto: str, maximo: int = 2000) -> str:
    """Quita caracteres de control e invisibles (usados para esconder órdenes) y normaliza espacios."""
    t = unicodedata.normalize("NFKC", texto).translate(_INVISIBLES)
    t = "".join(c for c in t if c in "\n\t" or unicodedata.category(c)[0] != "C")
    t = re.sub(r"[ \t]{3,}", "  ", t)
    t = re.sub(r"\n{4,}", "\n\n\n", t)
    return t.strip()[:maximo]


def parece_inyeccion(texto: str) -> list[str]:
    """Patrones que suenan a orden dirigida al modelo. Solo alerta y registra: el texto sigue siendo DATO delimitado."""
    return [p.pattern[:40] for p in _PATRONES if p.search(texto)]


def delimitar(texto: str, etiqueta: str) -> str:
    """Encierra texto no confiable en etiquetas; neutraliza cualquier etiqueta de cierre que traiga dentro."""
    seguro = re.sub(r"<\s*/?\s*(" + re.escape(etiqueta) + r"|contexto_json|pregunta_del_usuario)[^>]*>", "[etiqueta eliminada]", texto, flags=re.IGNORECASE)
    return f"<{etiqueta}>\n{seguro}\n</{etiqueta}>"


_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_ENLACE = re.compile(r"\[([^\]]*)\]\((?:https?:)?//[^)]*\)")
_URL = re.compile(r"https?://\S+", re.IGNORECASE)
_HTML = re.compile(r"</?\s*(script|iframe|img|object|embed|style|link|meta|form|svg)[^>]*>", re.IGNORECASE)


def limpiar_salida(texto: str, maximo: int = 4000) -> str:
    """La respuesta del modelo también es no confiable: sin imágenes ni enlaces remotos (exfiltración) ni HTML activo."""
    t = _IMG.sub("", texto)
    t = _ENLACE.sub(r"\1", t)
    t = _URL.sub("[enlace eliminado]", t)
    t = _HTML.sub("", t)
    return t.strip()[:maximo]
