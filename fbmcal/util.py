"""Utilidades comunes: zona horaria, normalización de textos y fechas."""
import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Madrid")


def ahora_madrid() -> datetime:
    return datetime.now(TZ)


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes ni símbolos: 'Cadete Masc. 1ºaño' -> 'cadetemasc1oano'."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def slug(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def temporada_de(d: date) -> str:
    """La temporada empieza en agosto: 24/09/2026 -> '2026-27'."""
    inicio = d.year if d.month >= 8 else d.year - 1
    return f"{inicio}-{(inicio + 1) % 100:02d}"


def fecha_es(iso: str | None) -> str:
    if not iso:
        return "Pendiente de confirmación"
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def fin_de_semana(d: date) -> date:
    """Domingo de la semana (lunes-domingo) que contiene d."""
    return d + timedelta(days=6 - d.weekday())


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
