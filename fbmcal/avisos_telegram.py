"""Traduce el RESULTADO DE LA CONCILIACIÓN a mensajes de Telegram (sin red y sin token).

No reinterpreta los datos de la FBM: cada mensaje sale de un `Cambio` de conciliar.py (con su UID y sus
datos «antes») o del campo `verificacion` que fija la conciliación el lunes y el viernes.

Anti-duplicados:
  * Línea base          -> la primera vez que se procesa un equipo, sus partidos existentes se registran
                           sin aviso individual (un único resumen «📋 AVISOS DE TELEGRAM ACTIVADOS»).
  * Alta de partido     -> una vez por partido (marca `avisos_telegram.nuevo` en el estado).
  * Verificado (lunes)  -> una vez por partido y fecha (marca `avisos_telegram.lunes`).
  * Confirmado (viernes)-> una vez por partido y fecha (marca `avisos_telegram.viernes`).
  * Cambios             -> la conciliación solo los devuelve una vez (el estado ya queda actualizado).
  * Avisos del sistema  -> como mucho uno cada 3 días con el mismo texto.
"""
import hashlib
from collections import defaultdict
from datetime import date, datetime

from .conciliar import CLASES, INACTIVOS, Cambio, activo
from .telegram import texto_error
from .util import DIAS, fecha_es

# Cambios de fecha/hora que ya quedan incluidos en el aviso de aplazamiento o de nuevo horario.
CUBIERTOS_POR_APLAZAMIENTO = {"cambio_fecha", "cambio_hora", "hora_confirmada", "hora_retirada"}
PENDIENTE = "Pendiente de confirmación"


def _dia(fecha: str | None) -> str:
    if not fecha:
        return "Fecha pendiente"
    d = date.fromisoformat(fecha)
    return f"{DIAS[d.weekday()].capitalize()} {fecha_es(fecha)}"


def _hora(hora: str | None) -> str:
    return hora or f"{PENDIENTE} (se muestra a las 00:00)"


def _pab(pabellon: str | None, direccion: str | None = None, con_direccion: bool = False) -> str:
    if not pabellon:
        return PENDIENTE
    return f"{pabellon}\n{direccion}" if con_direccion and direccion else pabellon


def _lv(arganda_local: bool) -> str:
    return "Local" if arganda_local else "Visitante"


def _cabecera(titulo: str, cfg: dict, q: dict, con_rival: bool = True) -> list[str]:
    lineas = [titulo, "", f"🏀 {cfg['nombre_telegram']}"]
    if con_rival:
        lineas.append(f"🆚 {q['rival']}")
    return lineas + [""]


def _pie(cfg: dict) -> list[str]:
    return ["", f"📅 Calendario: {cfg['calendario_corto']}"]


def _datos(q: dict) -> list[str]:
    return [f"📅 Fecha: {_dia(q['fecha'])}", f"🕐 Hora: {_hora(q['hora'])}", f"📍 Pabellón: {_pab(q['pabellon'])}"]


# ---------------------------------------------------------------- plantillas de mensaje

def texto_nuevo(cfg: dict, q: dict) -> str:
    return "\n".join([
        "🏀 NUEVO PARTIDO", "",
        f"Equipo: {cfg['nombre_telegram']}",
        f"🆚 Rival: {q['rival']}", "",
        f"📅 Fecha: {_dia(q['fecha'])}",
        f"🕐 Hora: {_hora(q['hora'])}",
        f"📍 Pabellón: {_pab(q['pabellon'])}",
        f"🏠 Local/Visitante: {_lv(q['arganda_local'])}",
        f"🏆 Jornada: {q['jornada'] if q['jornada'] is not None else 'No indicada'}",
        *_pie(cfg),
    ])


def texto_verificado(cfg: dict, q: dict) -> str:
    return "\n".join([
        *_cabecera("🔎 PARTIDO DETECTADO", cfg, q),
        f"📅 {_dia(q['fecha'])}", f"🕐 {_hora(q['hora'])}", f"📍 {_pab(q['pabellon'])}", "",
        "Estado: VERIFICADO", "",
        "Próxima comprobación:", "Viernes 17:05",
        *_pie(cfg),
    ])


def texto_confirmado(cfg: dict, q: dict) -> str:
    return "\n".join([
        *_cabecera("✅ PARTIDO CONFIRMADO", cfg, q),
        f"📅 {_dia(q['fecha'])}", f"🕐 {_hora(q['hora'])}", f"📍 {_pab(q['pabellon'])}", "",
        "La información ha sido comprobada nuevamente en la fuente oficial.",
        *_pie(cfg),
    ])


def texto_cambio(c: Cambio, cfg: dict, q: dict, tipos_del_partido: set[str]) -> str:
    """Mensaje para un cambio de la conciliación sobre un partido concreto."""
    a = c.antes or {}
    t = c.tipo
    if t in ("cambio_hora", "hora_confirmada", "hora_retirada"):
        return "\n".join([
            *_cabecera("🔄 CAMBIO DE HORA", cfg, q),
            f"🕐 Antes: {a.get('hora') or 'Pendiente (se mostraba a las 00:00)'}",
            f"🕐 Ahora: {q['hora'] or 'Pendiente (se muestra a las 00:00)'}", "",
            f"📅 {_dia(q['fecha'])}", f"📍 {_pab(q['pabellon'])}",
            *_pie(cfg),
        ])
    if t == "cambio_fecha":
        return "\n".join([
            *_cabecera("📅 CAMBIO DE FECHA", cfg, q),
            f"📅 Antes: {_dia(a.get('fecha'))}", f"📅 Ahora: {_dia(q['fecha'])}", "",
            f"🕐 Hora: {_hora(q['hora'])}", f"📍 Pabellón: {_pab(q['pabellon'])}",
            *_pie(cfg),
        ])
    if t in ("cambio_pabellon", "pabellon_confirmado"):
        return "\n".join([
            *_cabecera("📍 CAMBIO DE PABELLÓN", cfg, q),
            "📍 Antes:", _pab(a.get("pabellon"), a.get("direccion"), True), "",
            "📍 Ahora:", _pab(q["pabellon"], q["direccion"], True), "",
            f"📅 {_dia(q['fecha'])}", f"🕐 {_hora(q['hora'])}",
            *_pie(cfg),
        ])
    if t == "aplazado":
        lineas = [*_cabecera("⚠️ PARTIDO APLAZADO", cfg, q),
                  f"📅 Fecha anterior: {_dia(a.get('fecha'))}",
                  f"🕐 Hora anterior: {_hora(a.get('hora'))}", "",
                  "Estado: APLAZADO"]
        if (q["fecha"], q["hora"]) != (a.get("fecha"), a.get("hora")):
            lineas += ["", f"📅 Nueva fecha: {_dia(q['fecha'])}", f"🕐 Nueva hora: {_hora(q['hora'])}"]
        else:
            lineas += ["", "Nueva fecha: pendiente de publicar por la FBM.",
                       "El evento sigue en su fecha marcado como ⏸️ APLAZADO."]
        return "\n".join(lineas + _pie(cfg))
    if t == "aplazamiento_retirado":
        lineas = [*_cabecera("📅 NUEVO HORARIO TRAS EL APLAZAMIENTO", cfg, q)]
        if a.get("fecha") != q["fecha"]:
            lineas.append(f"📅 Antes: {_dia(a.get('fecha'))}")
        if a.get("hora") != q["hora"]:
            lineas.append(f"🕐 Antes: {_hora(a.get('hora'))}")
        lineas += [*_datos(q), "", "Estado: PROGRAMADO (ya no figura como aplazado)"]
        return "\n".join(lineas + _pie(cfg))
    if t == "cancelado":
        return "\n".join([
            *_cabecera("❌ PARTIDO CANCELADO", cfg, q),
            f"📅 {_dia(q['fecha'])}", f"🕐 {_hora(q['hora'])}", f"📍 {_pab(q['pabellon'])}", "",
            "El partido ha sido marcado como CANCELADO por la fuente oficial.",
            "Se ha quitado del calendario.",
            *_pie(cfg),
        ])
    if t == "eliminado":
        return "\n".join([
            *_cabecera("🗑️ PARTIDO ELIMINADO", cfg, q),
            f"📅 {_dia(q['fecha'])}", f"🕐 {_hora(q['hora'])}", "",
            "El evento ha sido eliminado del calendario porque la fuente oficial ya no lo publica.",
            f"({c.detalle})",
            *_pie(cfg),
        ])
    if t == "desaparecido":
        return "\n".join([
            *_cabecera("⚠️ POSIBLE DESAPARICIÓN", cfg, q),
            f"📅 {_dia(q['fecha'])}", f"🕐 {_hora(q['hora'])}", f"📍 {_pab(q['pabellon'])}", "",
            "El partido no aparece ahora en la web oficial de la FBM.",
            "NO se ha eliminado: sigue en el calendario marcado con ⚠️ y se volverá a comprobar.",
            *_pie(cfg),
        ])
    # Resto de cambios: 🔄 INFORMACIÓN ACTUALIZADA
    cambio_rival = t == "rival_renombrado" and a.get("rival") != q["rival"]
    lineas = _cabecera("🔄 INFORMACIÓN ACTUALIZADA", cfg, q, con_rival=not cambio_rival)
    if t == "rival_renombrado":
        if cambio_rival:
            lineas += [f"🆚 Antes: {a.get('rival')}", f"🆚 Ahora: {q['rival']}"]
        if a.get("arganda_local") is not None and a.get("arganda_local") != q["arganda_local"]:
            lineas.append(f"🏠 Local/Visitante: {_lv(a['arganda_local'])} → {_lv(q['arganda_local'])}")
        if a.get("local") != q["local"]:
            lineas.append(f"🏠 Equipo local: {a.get('local')} → {q['local']}")
        if a.get("visitante") != q["visitante"]:
            lineas.append(f"🚌 Equipo visitante: {a.get('visitante')} → {q['visitante']}")
    elif t == "competicion":
        lineas += [f"🏆 Antes: {a.get('competicion')}", f"🏆 Ahora: {q['competicion']}"]
    elif t == "reaparecido":
        lineas.append("✅ El partido vuelve a aparecer en la web oficial de la FBM (se quita el aviso ⚠️).")
    elif t == "reactivado":
        lineas.append(f"▶️ Estado: {str(a.get('estado', '')).upper()} → PROGRAMADO. Vuelve a estar en el calendario.")
    elif t == "resultado":
        lineas.append(f"🏁 Resultado: {q['local']} {q['marcador']} {q['visitante']}")
    elif t == "discrepancia":
        lineas += ["⚠️ Discrepancia entre fuentes oficiales de la FBM:", c.detalle]
    elif t == "aviso_fbm":
        lineas.append(f"ℹ️ La FBM indica: {c.detalle}")
    else:
        lineas.append(f"ℹ️ {c.detalle}")
    return "\n".join(lineas + ["", *_datos(q)] + _pie(cfg))


def texto_aviso_equipo(c: Cambio, cfg: dict, ultima_ok: str | None) -> str:
    """Avisos sin partido concreto (nueva competición, error de un grupo…)."""
    if c.tipo == "error":
        return texto_error(f"{c.titulo}: {c.detalle}", ultima_ok, f"el calendario {cfg['calendario_corto']}")
    if c.tipo == "grupo_nuevo":
        return "\n".join(["🆕 NUEVA COMPETICIÓN DETECTADA", "", f"🏀 {cfg['nombre_telegram']}",
                          f"🏆 {c.titulo}", "", c.detalle, *_pie(cfg)])
    return "\n".join(["⚠️ AVISO DEL SISTEMA", "", f"🏀 {cfg['nombre_telegram']}", f"🏆 {c.titulo}", "",
                      c.detalle, *_pie(cfg)])


# ---------------------------------------------------------------- de la conciliación a la cola

def _orden(q: dict):
    return q["fecha"] or "9999", q["hora"] or "", q["clave"]


def _mensaje(cfg: dict, clase: str, id_: str, texto: str, uid: str | None = None) -> dict:
    return {"id": id_, "equipo": cfg["id"], "clase": clase, "uid": uid, "texto": texto}


def texto_inicio(equipos: list[tuple[dict, int]]) -> str:
    lineas = ["📋 AVISOS DE TELEGRAM ACTIVADOS", "",
              "Se ha registrado el estado inicial de los calendarios (sin avisar partido a partido):", ""]
    for cfg, n in equipos:
        lineas.append(f"🏀 {cfg['calendario_corto']}: {n} partido{'s' if n != 1 else ''}"
                      + ("" if n else " (la FBM aún no los ha publicado)"))
    return "\n".join(lineas + ["", "A partir de ahora recibirás un aviso por cada partido nuevo, cada cambio, "
                                   "la verificación del lunes y la confirmación del viernes."])


def preparar_mensajes(cambios: dict[str, list[Cambio]], estado: dict, config: dict, modo: str,
                      ahora: datetime, ultima_ok: str | None) -> tuple[list[dict], list[tuple[dict, str, str]]]:
    """Devuelve (mensajes, marcas). Las marcas anti-duplicado se aplican solo si todo ha ido bien.

    LÍNEA BASE: la primera vez que Telegram procesa un equipo (su estado aún no tiene
    `avisos_telegram_desde`), los partidos que ya existen se registran como estado inicial SIN un aviso
    «NUEVO PARTIDO» por cada uno; en su lugar se envía un único resumen. Desde esa ejecución, todo partido
    que aparezca después sí genera «NUEVO PARTIDO», y los cambios, la verificación del lunes y la
    confirmación del viernes se avisan con normalidad (también en la propia ejecución de línea base).
    """
    ahora_iso = ahora.isoformat(timespec="minutes")
    hoy = ahora.date().isoformat()
    mensajes, marcas, en_linea_base = [], [], []
    for cfg in config["equipos"]:
        est = estado["equipos"].setdefault(cfg["id"], {})
        partidos = est.get("partidos", {})
        por_uid = {q["uid"]: q for q in partidos.values()}
        lista = cambios.get(cfg["id"], [])
        tipos = defaultdict(set)
        for c in lista:
            if c.uid:
                tipos[c.uid].add(c.tipo)
        linea_base = "avisos_telegram_desde" not in est
        if linea_base:
            en_linea_base.append((cfg, sum(1 for q in partidos.values() if activo(q))))
            marcas.append((est, "avisos_telegram_desde", ahora_iso))

        # 1) Alta: cada partido futuro se anuncia UNA vez (salvo los registrados en la línea base).
        for q in sorted(partidos.values(), key=_orden):
            if activo(q) and not (q.get("avisos_telegram") or {}).get("nuevo"):
                if linea_base:
                    marcas.append((q.setdefault("avisos_telegram", {}), "nuevo", "linea-base"))
                elif q["fecha"] and q["fecha"] >= hoy:
                    mensajes.append(_mensaje(cfg, "NUEVO", f"{q['uid']}|nuevo", texto_nuevo(cfg, q), q["uid"]))
                    marcas.append((q.setdefault("avisos_telegram", {}), "nuevo", ahora_iso))

        # 2) Cambios, en el orden en que los detectó la conciliación.
        for c in lista:
            if c.tipo == "nuevo" or (linea_base and c.tipo == "grupo_nuevo"):
                continue  # altas: cubiertas por el punto 1 (o por el resumen de la línea base)
            if c.uid is None:
                clave = hashlib.sha1(f"{c.tipo}|{c.titulo}|{c.detalle}".encode()).hexdigest()[:16]
                mensajes.append(_mensaje(cfg, CLASES.get(c.tipo, "AVISO"), f"sistema|{cfg['id']}|{clave}",
                                         texto_aviso_equipo(c, cfg, ultima_ok)))
                continue
            q = por_uid.get(c.uid)
            if q is None:
                continue
            if c.tipo in CUBIERTOS_POR_APLAZAMIENTO and tipos[c.uid] & {"aplazado", "aplazamiento_retirado"}:
                continue  # ya va dentro del aviso de aplazamiento / nuevo horario
            mensajes.append(_mensaje(cfg, CLASES.get(c.tipo, "MODIFICADO"), f"{c.uid}|{c.tipo}|{ahora_iso}",
                                     texto_cambio(c, cfg, q, tipos[c.uid]), c.uid))

        # 3) Verificación del lunes / confirmación del viernes (una vez por partido y fecha).
        if modo in ("lunes", "viernes"):
            for q in sorted(partidos.values(), key=_orden):
                v = q.get("verificacion") or {}
                if (activo(q) and v.get("tipo") == modo and v.get("en") == ahora_iso
                        and (q.get("avisos_telegram") or {}).get(modo) != q["fecha"]):
                    clase, texto = (("VERIFICADO", texto_verificado(cfg, q)) if modo == "lunes"
                                    else ("CONFIRMADO", texto_confirmado(cfg, q)))
                    mensajes.append(_mensaje(cfg, clase, f"{q['uid']}|{modo}|{q['fecha']}", texto, q["uid"]))
                    marcas.append((q.setdefault("avisos_telegram", {}), modo, q["fecha"]))

    if en_linea_base:
        mensajes.insert(0, {"id": f"linea-base|{ahora_iso}|{','.join(c['id'] for c, _ in en_linea_base)}",
                            "equipo": "todos", "clase": "INICIO", "uid": None, "texto": texto_inicio(en_linea_base)})
    return mensajes, marcas


def aplicar_marcas(marcas: list[tuple[dict, str, str]]) -> None:
    for destino, clave, valor in marcas:
        destino[clave] = valor


def contar(cambios: dict[str, list[Cambio]], estado: dict, config: dict, modo: str, ahora: datetime) -> dict:
    """Recuento por equipo según el resultado de la conciliación (para el resumen de la ejecución)."""
    ahora_iso = ahora.isoformat(timespec="minutes")
    res = {}
    for cfg in config["equipos"]:
        n = defaultdict(int)
        for c in cambios.get(cfg["id"], []):
            n[CLASES.get(c.tipo, "AVISO")] += 1
        for q in estado["equipos"].get(cfg["id"], {}).get("partidos", {}).values():
            v = q.get("verificacion") or {}
            if modo == "viernes" and v.get("tipo") == "viernes" and v.get("en") == ahora_iso and q["estado"] not in INACTIVOS:
                n["CONFIRMADO"] += 1
        res[cfg["id"]] = dict(n)
    return res
