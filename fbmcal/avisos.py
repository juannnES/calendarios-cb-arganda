"""Avisos por email (Gmail SMTP, gratis). Credenciales SOLO por variables de entorno / GitHub Secrets."""
import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

from .conciliar import TIPOS, Cambio
from .util import DIAS


def componer_informe(cambios: dict[str, list[Cambio]], avisos: list[str], config: dict,
                     modo: str, ahora: datetime, url_pagina: str | None) -> tuple[str, str] | None:
    """Devuelve (asunto, cuerpo) o None si no hay nada que notificar."""
    nombres = {e["id"]: e["nombre_calendario"] for e in config["equipos"]}
    bloques = []
    total = 0
    for eid, lista in cambios.items():
        notificables = [c for c in lista if c.notificar]
        if not notificables:
            continue
        total += len(notificables)
        lineas = [f"■ {nombres.get(eid, eid)}"]
        for c in notificables:
            lineas.append(f"  • {TIPOS.get(c.tipo, c.tipo)}: {c.titulo}")
            if c.detalle:
                lineas.append(f"      {c.detalle}")
        bloques.append("\n".join(lineas))
    if avisos:
        total += len(avisos)
        bloques.append("■ Avisos del sistema\n" + "\n".join(f"  • {a}" for a in avisos))
    if not total:
        return None

    momento = f"{DIAS[ahora.weekday()]} {ahora:%d/%m/%Y %H:%M}"
    etiqueta = {"lunes": "comprobación del lunes", "viernes": "confirmación final del viernes"}.get(modo, "comprobación manual")
    asunto = f"🏀 Calendarios CB Arganda: {total} novedad{'es' if total != 1 else ''} ({etiqueta})"
    cuerpo = [f"Resultado de la {etiqueta} ({momento}, hora de Madrid).", "", *bloques, "",
              "Los calendarios ya están actualizados; Apple Calendar los recogerá en su próximo refresco."]
    if url_pagina:
        cuerpo.append(f"Página de los calendarios: {url_pagina}")
    cuerpo.append("Fuente oficial: " + config["fuente"]["club_url"])
    return asunto, "\n".join(cuerpo)


def enviar_email(asunto: str, cuerpo: str) -> bool:
    usuario = os.environ.get("GMAIL_USER", "").strip()
    clave = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "").strip()
    destino = os.environ.get("NOTIFY_TO", "").strip() or usuario
    if not (usuario and clave):
        print("ℹ️  Email no enviado: faltan GMAIL_USER / GMAIL_APP_PASSWORD (ver README).")
        print(f"--- {asunto} ---\n{cuerpo}")
        return False
    msg = EmailMessage()
    msg["Subject"] = asunto
    msg["From"] = f"Calendarios CB Arganda <{usuario}>"
    msg["To"] = destino
    msg.set_content(cuerpo)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(usuario, clave)
        s.send_message(msg)
    print(f"📧 Email enviado: {asunto}")
    return True
