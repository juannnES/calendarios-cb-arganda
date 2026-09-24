"""Generación de calendarios iCalendar (RFC 5545) compatibles con Apple Calendar, Google y Outlook."""
from datetime import date, datetime, time, timedelta, timezone

from .conciliar import titulo_base
from .util import DIAS, TZ, fecha_es, normalizar

VTIMEZONE_MADRID = [
    "BEGIN:VTIMEZONE",
    "TZID:Europe/Madrid",
    "X-LIC-LOCATION:Europe/Madrid",
    "BEGIN:DAYLIGHT",
    "TZOFFSETFROM:+0100",
    "TZOFFSETTO:+0200",
    "TZNAME:CEST",
    "DTSTART:19700329T020000",
    "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
    "END:DAYLIGHT",
    "BEGIN:STANDARD",
    "TZOFFSETFROM:+0200",
    "TZOFFSETTO:+0100",
    "TZNAME:CET",
    "DTSTART:19701025T030000",
    "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
    "END:STANDARD",
    "END:VTIMEZONE",
]


def _esc(texto: str) -> str:
    return (texto.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
            .replace("\r\n", "\n").replace("\n", "\\n"))


def _plegar(linea: str) -> str:
    """Divide líneas de más de 75 octetos (RFC 5545 §3.1) sin partir caracteres UTF-8."""
    partes, actual, limite = [], "", 75
    for ch in linea:
        if len((actual + ch).encode("utf-8")) > limite:
            partes.append(actual)
            actual, limite = ch, 74  # las líneas de continuación empiezan con un espacio
        else:
            actual += ch
    partes.append(actual)
    return "\r\n ".join(partes)


def _utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _local(dt: datetime) -> str:
    return dt.strftime("%Y%m%dT%H%M%S")


def _dt(iso: str | None) -> datetime | None:
    return datetime.fromisoformat(iso) if iso else None


def horario_evento(q: dict, conf: dict) -> tuple[datetime, datetime]:
    """Inicio = hora del partido - 45 min; fin = hora del partido + 2 h. Sin hora: 00:00 (+2 h)."""
    d = date.fromisoformat(q["fecha"])
    if q.get("hora"):
        partido = datetime.combine(d, time.fromisoformat(q["hora"]), TZ)
        return (partido - timedelta(minutes=conf["minutos_antes"]),
                partido + timedelta(minutes=conf["duracion_partido_min"]))
    inicio = datetime.combine(d, time.fromisoformat(conf["hora_pendiente"]), TZ)
    return inicio, inicio + timedelta(minutes=conf["duracion_pendiente_min"])


def ubicacion(q: dict, pabellones: dict) -> str:
    """Dirección exacta publicada por la FBM (o la corregida en pabellones.json)."""
    if not q.get("pabellon"):
        return "Pabellón pendiente de confirmación"
    corregida = pabellones.get(f"{normalizar(q['pabellon'])}|{normalizar(q.get('direccion'))}")
    if corregida:
        return corregida
    if not q.get("direccion"):
        return q["pabellon"]
    direccion = q["direccion"]
    if not normalizar(direccion).endswith("madrid"):
        direccion += ", Madrid"
    return f"{direccion}, España"


def titulo_evento(q: dict, nombre_corto: str) -> str:
    prefijo = ""
    if q.get("desaparecido_desde"):
        prefijo += "⚠️ "
    if q["estado"] == "aplazado":
        prefijo += "⏸️ APLAZADO · "
    if not q.get("hora"):
        prefijo += "⏳ "
    return prefijo + titulo_base(q, nombre_corto)


def _texto_verificacion(q: dict) -> str:
    v = q.get("verificacion") or {}
    en = _dt(v.get("en"))
    if v.get("tipo") == "viernes":
        return f"✅ CONFIRMADO en la comprobación final del viernes {en:%d/%m/%Y %H:%M}"
    if v.get("tipo") == "lunes":
        return f"🔎 Verificado el lunes {en:%d/%m/%Y %H:%M} (falta la confirmación final del viernes)"
    return "📅 Según el calendario oficial. Se verificará el lunes y se confirmará el viernes de la semana del partido"


def descripcion(q: dict, cfg: dict, conf: dict, fuente_url: str, pabellones: dict) -> str:
    d = date.fromisoformat(q["fecha"])
    inicio, fin = horario_evento(q, conf)
    ult = _dt(q["ultima_comprobacion"])
    lineas = [
        f"🏀 {cfg['nombre_corto']}",
        f"Categoría: {cfg['categoria_mostrada']}",
        f"Competición: {q['competicion']}",
        f"Jornada: {q['jornada'] if q['jornada'] is not None else 'No indicada'}",
        f"Rival: {q['rival']}",
        f"Local/Visitante: {'Local' if q['arganda_local'] else 'Visitante'}",
        "",
        f"📍 Pabellón: {q['pabellon'] or 'Pendiente de confirmación'}",
        f"🗺️ Dirección: {ubicacion(q, pabellones) if q.get('pabellon') else 'Pendiente de confirmación'}",
        f"📅 Fecha: {DIAS[d.weekday()]} {fecha_es(q['fecha'])}",
    ]
    if q.get("hora"):
        lineas += [f"🕐 Hora: {q['hora']}",
                   f"⏰ En el calendario: {inicio:%H:%M}–{fin:%H:%M} "
                   f"({conf['minutos_antes']} min antes + {conf['duracion_partido_min'] // 60} h de partido)"]
    else:
        lineas += ["🕐 Hora: Hora pendiente de confirmación",
                   f"⏰ Se muestra a las {conf['hora_pendiente']} hasta que la FBM publique la hora oficial"]
    lineas.append("")
    if q["estado"] == "aplazado":
        lineas.append(f"⏸️ APLAZADO según la FBM{': ' + q['texto_estado'] if q.get('texto_estado') else ''}")
    if q.get("desaparecido_desde"):
        lineas.append(f"⚠️ Este partido no aparece en la web oficial desde el "
                      f"{_dt(q['desaparecido_desde']):%d/%m/%Y %H:%M}. Se mantiene hasta aclararlo.")
    if q.get("marcador"):
        lineas.append(f"🏁 Resultado: {q['local']} {q['marcador']} {q['visitante']}")
    for disc in q.get("discrepancias") or []:
        lineas.append(f"⚠️ Discrepancia entre fuentes oficiales — {disc}")
    lineas += [
        f"Estado: {_texto_verificacion(q)}",
        f"✅ Última comprobación: {ult:%d/%m/%Y %H:%M}",
        "",
        "Fuente oficial:",
        fuente_url,
    ]
    return "\n".join(lineas)


def generar_ics(cfg: dict, est: dict, conf: dict, fuente_url: str, pabellones: dict, ahora: datetime) -> str:
    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Calendarios CB Arganda//FBM//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_esc(cfg['nombre_calendario'])}",
        f"X-WR-CALDESC:{_esc('Partidos oficiales (FBM) de ' + cfg['nombre_corto'] + ' · ' + cfg['categoria_mostrada'])}",
        "X-WR-TIMEZONE:Europe/Madrid",
        f"X-APPLE-CALENDAR-COLOR:{cfg['color']}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
        *VTIMEZONE_MADRID,
    ]
    dtstamp = _utc(ahora)
    partidos = sorted(est.get("partidos", {}).values(), key=lambda q: (q["fecha"] or "", q["hora"] or "", q["clave"]))
    for q in partidos:
        if q["estado"] == "cancelado" or not q["fecha"]:
            continue  # cancelado -> se elimina del calendario (acordado)
        inicio, fin = horario_evento(q, conf)
        lineas += [
            "BEGIN:VEVENT",
            f"UID:{q['uid']}",
            f"DTSTAMP:{dtstamp}",
            f"CREATED:{_utc(_dt(q['creado']))}",
            f"LAST-MODIFIED:{_utc(_dt(q['modificado']))}",
            f"SEQUENCE:{q['secuencia']}",
            f"DTSTART;TZID=Europe/Madrid:{_local(inicio)}",
            f"DTEND;TZID=Europe/Madrid:{_local(fin)}",
            f"SUMMARY:{_esc(titulo_evento(q, cfg['nombre_corto']))}",
            f"LOCATION:{_esc(ubicacion(q, pabellones))}",
            f"DESCRIPTION:{_esc(descripcion(q, cfg, conf, fuente_url, pabellones))}",
            f"URL:{fuente_url}",
            "STATUS:CONFIRMED",  # TENTATIVE se ve atenuado en Apple Calendar; el estado va en la descripción
            "TRANSP:OPAQUE",
            "CATEGORIES:Baloncesto",
            "END:VEVENT",
        ]
    lineas.append("END:VCALENDAR")
    return "\r\n".join(_plegar(l) for l in lineas) + "\r\n"
