"""Informes de cada ejecución. Sin email y sin ninguna credencial personal.

  * Resumen visible en la propia ejecución de GitHub Actions (variable GITHUB_STEP_SUMMARY).
  * Archivo de aviso (variable AVISO_ARCHIVO): si hay cambios, el workflow lo publica como un Issue
    del repositorio usando el token automático de GitHub, y GitHub avisa al propietario.
  * docs/estado.json: estado público de la última comprobación correcta.
"""
import os
from datetime import datetime

from .conciliar import TIPOS, Cambio, activo
from .util import DIAS, fecha_es

ETIQUETAS_MODO = {"lunes": "comprobación de las 17:00 del lunes",
                  "viernes": "confirmación final de las 17:00 del viernes"}


def etiqueta_modo(modo: str) -> str:
    return ETIQUETAS_MODO.get(modo, "comprobación manual")


def _lineas_cambios(cambios: dict[str, list[Cambio]], config: dict, solo_notificables: bool) -> list[str]:
    nombres = {e["id"]: e["nombre_calendario"] for e in config["equipos"]}
    lineas = []
    for eid, lista in cambios.items():
        lista = [c for c in lista if c.notificar] if solo_notificables else [c for c in lista if c.tipo != "nuevo"]
        if not lista:
            continue
        lineas.append(f"### {nombres.get(eid, eid)}")
        for c in lista:
            lineas.append(f"- **{TIPOS.get(c.tipo, c.tipo)}**: {c.titulo}" + (f" — {c.detalle}" if c.detalle else ""))
        lineas.append("")
    return lineas


def componer_aviso(cambios: dict[str, list[Cambio]], avisos: list[str], config: dict,
                   modo: str, ahora: datetime, url_pagina: str | None) -> tuple[str, str] | None:
    """(título, cuerpo en Markdown) si hay algo que avisar; None si no.

    No se avisa de partidos nuevos ni de «hora 00:00 → hora oficial» (acordado)."""
    total = sum(1 for lista in cambios.values() for c in lista if c.notificar) + len(avisos)
    if not total:
        return None
    titulo = (f"🏀 {total} novedad{'es' if total != 1 else ''} en los calendarios · "
              f"{DIAS[ahora.weekday()]} {ahora:%d/%m/%Y} ({etiqueta_modo(modo)})")
    cuerpo = [f"Resultado de la {etiqueta_modo(modo)} ({ahora:%d/%m/%Y %H:%M}, hora de Madrid).", ""]
    cuerpo += _lineas_cambios(cambios, config, solo_notificables=True)
    if avisos:
        cuerpo += ["### Avisos del sistema", *[f"- {a}" for a in avisos], ""]
    cuerpo.append("Los calendarios ya están actualizados; Apple Calendar los recogerá en su próximo refresco.")
    if url_pagina:
        cuerpo.append(f"\nCalendarios: {url_pagina}")
    cuerpo.append(f"Fuente oficial: {config['fuente']['club_url']}")
    cuerpo.append("\n_Puedes cerrar este aviso cuando lo hayas leído._")
    return titulo, "\n".join(cuerpo)


def resumen_ejecucion(cambios: dict[str, list[Cambio]], avisos: list[str], config: dict, estado: dict,
                      modo: str, ahora: datetime) -> str:
    """Resumen en Markdown para la página de la ejecución en GitHub Actions."""
    hoy = ahora.date().isoformat()
    lineas = [f"## 🏀 Calendarios CB Arganda — {etiqueta_modo(modo)}",
              f"{DIAS[ahora.weekday()]} {ahora:%d/%m/%Y %H:%M} (Europe/Madrid) · ✅ ejecución correcta", "",
              "| Calendario | Partidos | Próximo partido | Cambios |", "|---|---|---|---|"]
    for cfg in config["equipos"]:
        est = estado["equipos"].get(cfg["id"], {})
        activos = [q for q in est.get("partidos", {}).values() if activo(q)]
        futuros = sorted((q for q in activos if q["fecha"] and q["fecha"] >= hoy), key=lambda q: (q["fecha"], q["hora"] or ""))
        prox = (f"{fecha_es(futuros[0]['fecha'])} {futuros[0]['hora'] or '(hora pendiente)'} · "
                f"{futuros[0]['local']} - {futuros[0]['visitante']}") if futuros else "sin partidos publicados"
        n = len([c for c in cambios.get(cfg["id"], []) if c.tipo != "nuevo"])
        lineas.append(f"| {cfg['nombre_calendario']} | {len(activos)} | {prox} | {n} |")
    lineas.append("")
    lineas += _lineas_cambios(cambios, config, solo_notificables=False)
    if avisos:
        lineas += ["### Avisos del sistema", *[f"- {a}" for a in avisos]]
    return "\n".join(lineas) + "\n"


def resumen_por_equipo(conteos: dict[str, dict], config: dict, en_cola: int | None) -> str:
    """Resumen interno de la ejecución (GitHub Actions → Summary), según el resultado de la conciliación."""
    lineas = ["```", "🏀 CALENDARIOS CB ARGANDA", ""]
    for cfg in config["equipos"]:
        n = conteos.get(cfg["id"], {})
        lineas += [cfg.get("calendario_corto", cfg["nombre_calendario"]),
                   f"- Nuevos: {n.get('NUEVO', 0)}",
                   f"- Modificados: {n.get('MODIFICADO', 0)}",
                   f"- Confirmados: {n.get('CONFIRMADO', 0)}",
                   f"- Aplazados: {n.get('APLAZADO', 0)}",
                   f"- Cancelados: {n.get('CANCELADO', 0)}"]
        if n.get("ELIMINADO"):
            lineas.append(f"- Eliminados: {n['ELIMINADO']}")
        if n.get("ERROR"):
            lineas.append(f"- Errores: {n['ERROR']}")
        lineas.append("")
    lineas.append("Estado: ✅ Correcto")
    lineas.append(f"Avisos de Telegram en cola: {en_cola}" if en_cola is not None
                  else "Avisos de Telegram: ⚠️ no se pudieron preparar (ver log)")
    return "\n".join(lineas + ["```", ""])


def estado_publico(cambios: dict[str, list[Cambio]], avisos: list[str], config: dict, estado: dict,
                   modo: str, ahora: datetime) -> dict:
    """Contenido de docs/estado.json (solo datos públicos de partidos)."""
    hoy = ahora.date().isoformat()
    equipos = {}
    for cfg in config["equipos"]:
        est = estado["equipos"].get(cfg["id"], {})
        activos = [q for q in est.get("partidos", {}).values() if activo(q)]
        futuros = sorted((q for q in activos if q["fecha"] and q["fecha"] >= hoy), key=lambda q: (q["fecha"], q["hora"] or ""))
        equipos[cfg["id"]] = {
            "calendario": cfg["nombre_calendario"],
            "archivo_ics": cfg["archivo_ics"],
            "competiciones": sorted(g["competicion"] for g in est.get("grupos", {}).values()),
            "partidos_en_calendario": len(activos),
            "partidos_sin_hora": sum(1 for q in futuros if not q["hora"]),
            "proximo_partido": ({k: futuros[0][k] for k in ("fecha", "hora", "local", "visitante", "pabellon")}
                                if futuros else None),
        }
    return {
        "resultado": "ok",
        "ultima_comprobacion_correcta": ahora.isoformat(timespec="minutes"),
        "tipo": etiqueta_modo(modo),
        "equipos": equipos,
        "cambios": [{"calendario": eid, "tipo": c.tipo, "partido": c.titulo, "detalle": c.detalle}
                    for eid, lista in cambios.items() for c in lista if c.tipo != "nuevo"],
        "avisos": avisos,
    }


def escribir_aviso(titulo: str, cuerpo: str) -> None:
    """Deja el aviso para que el workflow lo publique como Issue. Primera línea = título."""
    ruta = os.environ.get("AVISO_ARCHIVO")
    if not ruta:
        print(f"ℹ️  Aviso (no se publica porque AVISO_ARCHIVO no está definido):\n{titulo}\n{cuerpo}")
        return
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(f"{titulo}\n{cuerpo}\n")
    print(f"📣 Aviso preparado: {titulo}")


def escribir_resumen(markdown: str) -> None:
    ruta = os.environ.get("GITHUB_STEP_SUMMARY")
    if ruta:
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(markdown)
