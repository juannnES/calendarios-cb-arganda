"""Conciliación: compara lo publicado por la FBM con lo guardado y decide qué ha cambiado.

Cada partido tiene una clave única y estable:
    temporada | grupo FBM (competición+categoría+fase+grupo) | equipo | jornada | local-vs-visitante
y un UID de calendario que se genera una sola vez y no cambia nunca. Así, un cambio de hora,
fecha o pabellón MODIFICA el evento existente y nunca crea un duplicado.
"""
import hashlib
from collections import Counter
from dataclasses import dataclass
from datetime import datetime

from .fuente import DatosContraste, Grupo, PartidoFuente, clave_contraste
from .util import fecha_es, fin_de_semana, normalizar, slug

EQUIPOS_NULOS = {"", "descansa", "retirado", "bye"}

# Tipos de cambio que NO generan email (acordado: altas de partidos y hora 00:00 -> hora oficial).
SILENCIOSOS = {"nuevo", "hora_confirmada", "pabellon_confirmado", "resultado"}

TIPOS = {
    "nuevo": "Partido nuevo",
    "hora_confirmada": "Hora publicada",
    "pabellon_confirmado": "Pabellón publicado",
    "resultado": "Resultado publicado",
    "cambio_hora": "🕐 Cambio de hora",
    "hora_retirada": "🕐 La hora ha dejado de aparecer",
    "cambio_fecha": "📅 Cambio de fecha",
    "aplazado": "⏸️ Partido aplazado",
    "aplazamiento_retirado": "▶️ Ya no figura como aplazado",
    "cancelado": "❌ Partido cancelado (eliminado del calendario)",
    "reactivado": "▶️ Partido reactivado",
    "cambio_pabellon": "📍 Cambio de pabellón",
    "desaparecido": "⚠️ El partido ya no aparece en la web oficial (se mantiene en el calendario)",
    "reaparecido": "✅ El partido vuelve a aparecer en la web oficial",
    "rival_renombrado": "✏️ Cambio de nombre de un equipo",
    "discrepancia": "⚠️ Discrepancia entre fuentes oficiales",
    "aviso_fbm": "ℹ️ Texto de estado publicado por la FBM",
    "sin_fecha": "⚠️ Partido sin fecha publicada",
    "grupo_nuevo": "🆕 Nueva competición/fase detectada",
    "grupo_desaparecido": "⚠️ Una competición ya no aparece en la web del club",
    "categoria_desconocida": "⚠️ Posible categoría no reconocida",
    "error": "❌ Problema",
}


@dataclass
class Cambio:
    tipo: str
    titulo: str
    detalle: str = ""

    @property
    def notificar(self) -> bool:
        return self.tipo not in SILENCIOSOS


def titulo_base(q: dict, nombre_corto: str) -> str:
    if q["arganda_local"]:
        return f"{nombre_corto} vs {q['rival']}"
    return f"{q['rival']} vs {nombre_corto}"


def estado_desde_texto(texto: str | None) -> str:
    t = normalizar(texto)
    if any(k in t for k in ("anulad", "cancelad", "eliminad")):
        return "cancelado"
    if any(k in t for k in ("aplaz", "suspend")):
        return "aplazado"
    return "programado"


def resolver_valores(p: PartidoFuente, contraste: list[tuple[str, dict]]) -> tuple[dict, list[str]]:
    """Contrasta fecha, hora y pabellón entre las representaciones oficiales de la FBM.

    Reglas (nunca se elige al azar):
      * Un dato ausente ("sin publicar") no contradice a uno publicado.
      * Si los datos publicados coinciden -> ese valor.
      * Si discrepan -> mayoría absoluta de fuentes; si no la hay, manda el CALENDARIO OFICIAL
        de la competición. En ambos casos la discrepancia se anota en el evento y se avisa.
    """
    fuentes = [("calendario de la competición", DatosContraste(p.fecha, p.hora, p.pabellon, p.direccion))]
    k = clave_contraste(p.competicion, p.local, p.visitante)
    for nombre, datos in contraste:
        if k in datos:
            fuentes.append((nombre, datos[k]))

    valores, discrepancias = {}, []
    for campo, etiqueta in (("fecha", "fecha"), ("hora", "hora"), ("pabellon", "pabellón")):
        publicados = [(n, getattr(d, campo)) for n, d in fuentes if getattr(d, campo)]
        norm = [normalizar(v) for _, v in publicados]
        if len(set(norm)) <= 1:
            valores[campo] = publicados[0][1] if publicados else None
            continue
        top, n = Counter(norm).most_common(1)[0]
        if n > len(norm) / 2:
            elegido = next(v for (_, v), nv in zip(publicados, norm) if nv == top)
            regla = "mayoría de fuentes oficiales"
        else:
            elegido = getattr(fuentes[0][1], campo) or publicados[0][1]
            regla = "prioridad del calendario oficial de la competición"
        valores[campo] = elegido
        discrepancias.append(
            f"{etiqueta}: " + " · ".join(f"{n}={v}" for n, v in publicados) + f" → se usa «{elegido}» ({regla})")

    valores["direccion"] = next(
        (d.direccion for _, d in fuentes if d.pabellon and normalizar(d.pabellon) == normalizar(valores["pabellon"])),
        p.direccion)
    return valores, discrepancias


def _equipo_del_club(g: Grupo, cfg: dict) -> str:
    nombres = {t for p in g.partidos for t in (p.local, p.visitante)}
    if cfg.get("nombre_fbm"):
        if cfg["nombre_fbm"] in nombres:
            return cfg["nombre_fbm"]
        raise ValueError(f"No aparece el equipo «{cfg['nombre_fbm']}» (config nombre_fbm) en {g.competicion}")
    candidatos = sorted(n for n in nombres if any(pat in normalizar(n) for pat in cfg["patrones_nombre"]))
    if len(candidatos) == 1:
        return candidatos[0]
    if not candidatos:
        raise ValueError(f"No se encuentra ningún equipo del club en {g.competicion}")
    raise ValueError(f"Hay varios equipos del club en {g.competicion}: {', '.join(candidatos)}. "
                     "Indica cuál es en config.json (nombre_fbm).")


def _clave(temporada: str, g: Grupo, cfg: dict, p: PartidoFuente) -> str:
    j = f"j{p.jornada:02d}" if p.jornada is not None else "j--"
    return f"{temporada}|fbm-{g.id}|{cfg['id']}|{j}|{slug(p.local)}-vs-{slug(p.visitante)}"


def _uid(clave: str) -> str:
    return hashlib.sha1(clave.encode("utf-8")).hexdigest()[:24] + "@calendarios-cb-arganda"


def conciliar_equipo(cfg: dict, est: dict, grupos: list[Grupo], contraste: list[tuple[str, dict]],
                     ahora: datetime, modo: str, temporada: str) -> list[Cambio]:
    """Actualiza `est` (estado guardado de un equipo) y devuelve la lista de cambios detectados."""
    cambios: list[Cambio] = []
    ahora_iso = ahora.isoformat(timespec="minutes")
    hoy = ahora.date().isoformat()
    est.setdefault("grupos", {})
    est.setdefault("partidos", {})
    est.setdefault("categorias_avisadas", [])
    partidos: dict = est["partidos"]
    corto = cfg["nombre_corto"]

    def anotar(q: dict | None, tipo: str, titulo: str, detalle: str = ""):
        cambios.append(Cambio(tipo, titulo, detalle))
        if q is not None:
            q.setdefault("historial", []).append({"en": ahora_iso, "tipo": tipo, "detalle": detalle})

    categorias = {normalizar(c) for c in cfg["categoria_fbm"]}
    mios = [g for g in grupos if normalizar(g.categoria) in categorias]

    # Aviso único si aparece una categoría "parecida" (p. ej. la FBM cambia el nombre) que no reconocemos.
    for g in grupos:
        n = normalizar(g.categoria)
        if (n not in categorias and all(w in n for w in cfg["palabras_categoria"])
                and ("1oano" in n or "primer" in n) and g.categoria not in est["categorias_avisadas"]):
            est["categorias_avisadas"].append(g.categoria)
            anotar(None, "categoria_desconocida", g.competicion,
                   "Parece la categoría de este equipo pero no coincide con config.json (categoria_fbm). Revísalo.")

    ids_pagina = {g.id for g in grupos}
    for gid, info in est["grupos"].items():
        if gid not in ids_pagina and not info.get("ausente_desde"):
            info["ausente_desde"] = ahora_iso
            anotar(None, "grupo_desaparecido", info["competicion"],
                   "Sus partidos se mantienen en el calendario sin cambios hasta que vuelva a aparecer.")

    vistos: set[str] = set()
    grupos_procesados: set[str] = set()
    for g in mios:
        try:
            nombre = _equipo_del_club(g, cfg)
        except ValueError as e:
            anotar(None, "error", g.competicion, str(e))
            continue

        info = est["grupos"].get(g.id)
        if info is None:
            est["grupos"][g.id] = {"competicion": g.competicion, "equipo_fbm": nombre, "detectado": ahora_iso}
            anotar(None, "grupo_nuevo", g.competicion, f"Equipo en la FBM: «{nombre}». Sus partidos se han añadido.")
        else:
            info.pop("ausente_desde", None)
            info["equipo_fbm"] = nombre

        observados = []
        for p in g.partidos:
            if nombre not in (p.local, p.visitante):
                continue
            rival = p.visitante if p.local == nombre else p.local
            if normalizar(rival) in EQUIPOS_NULOS:
                continue  # jornada de descanso: no hay partido
            observados.append((p, rival, _clave(temporada, g, cfg, p)))

        guardados_grupo = [q for q in partidos.values() if q["grupo_id"] == g.id and q["estado"] != "cancelado"]
        if not observados and guardados_grupo:
            anotar(None, "error", g.competicion,
                   "La web no muestra ningún partido del equipo en este grupo. No se ha tocado el calendario.")
            continue
        grupos_procesados.add(g.id)

        claves_fuente = {c for _, _, c in observados}
        for p, rival, clave in observados:
            vistos.add(clave)
            valores, disc = resolver_valores(p, contraste)
            estado_nuevo = estado_desde_texto(p.texto_estado)
            arganda_local = p.local == nombre
            q = partidos.get(clave)

            if q is None:
                # ¿Es un partido ya guardado cuyo rival (o nuestro equipo) ha cambiado de nombre?
                candidatos = [x for x in partidos.values()
                              if x["grupo_id"] == g.id and x["jornada"] == p.jornada
                              and x["arganda_local"] == arganda_local and x["clave"] not in claves_fuente]
                if len(candidatos) == 1:
                    q = candidatos[0]
                    antes = f"{q['local']} - {q['visitante']}"
                    partidos.pop(q["clave"])
                    q.update(clave=clave, local=p.local, visitante=p.visitante, rival=rival, equipo_fbm=nombre)
                    partidos[clave] = q
                    anotar(q, "rival_renombrado", titulo_base(q, corto), f"{antes} → {p.local} - {p.visitante}")
                    q["secuencia"] += 1
                    q["modificado"] = ahora_iso

            if q is None:
                q = {
                    "uid": _uid(clave), "clave": clave, "grupo_id": g.id, "competicion": g.competicion,
                    "jornada": p.jornada, "local": p.local, "visitante": p.visitante, "equipo_fbm": nombre,
                    "arganda_local": arganda_local, "rival": rival,
                    "fecha": valores["fecha"], "hora": valores["hora"],
                    "pabellon": valores["pabellon"], "direccion": valores["direccion"],
                    "marcador": p.marcador, "estado": estado_nuevo, "texto_estado": p.texto_estado,
                    "discrepancias": disc, "verificacion": {"tipo": "provisional", "en": None},
                    "secuencia": 0, "creado": ahora_iso, "modificado": ahora_iso,
                    "ultima_comprobacion": ahora_iso, "desaparecido_desde": None, "historial": [],
                }
                partidos[clave] = q
                anotar(q, "nuevo", titulo_base(q, corto), f"{fecha_es(q['fecha'])} {q['hora'] or 'hora pendiente'}")
                if disc:
                    anotar(q, "discrepancia", titulo_base(q, corto), " | ".join(disc))
                if not q["fecha"]:
                    anotar(q, "sin_fecha", titulo_base(q, corto), "No se puede poner en el calendario hasta que tenga fecha.")
                continue

            titulo = titulo_base(q, corto)
            material = False

            if q.get("desaparecido_desde"):
                anotar(q, "reaparecido", titulo, f"No aparecía desde {q['desaparecido_desde'][:16].replace('T', ' ')}")
                q["desaparecido_desde"] = None
                material = True

            aplazado_con_fecha = False
            if valores["fecha"] and valores["fecha"] != q["fecha"]:
                tipo = "aplazado" if estado_nuevo == "aplazado" else "cambio_fecha"
                aplazado_con_fecha = tipo == "aplazado"
                anotar(q, tipo, titulo, f"{fecha_es(q['fecha'])} → {fecha_es(valores['fecha'])}")
                q["fecha"] = valores["fecha"]
                material = True

            if valores["hora"] != q["hora"]:
                if q["hora"] is None:
                    anotar(q, "hora_confirmada", titulo, valores["hora"])
                elif valores["hora"] is None:
                    anotar(q, "hora_retirada", titulo, f"{q['hora']} → pendiente (se muestra a las 00:00)")
                else:
                    anotar(q, "cambio_hora", titulo, f"{q['hora']} → {valores['hora']}")
                q["hora"] = valores["hora"]
                material = True

            if (normalizar(valores["pabellon"]), normalizar(valores["direccion"])) != (
                    normalizar(q["pabellon"]), normalizar(q["direccion"])):
                antes = f"{q['pabellon'] or 'por determinar'} ({q['direccion'] or '-'})"
                despues = f"{valores['pabellon'] or 'por determinar'} ({valores['direccion'] or '-'})"
                anotar(q, "pabellon_confirmado" if not q["pabellon"] else "cambio_pabellon", titulo, f"{antes} → {despues}")
                q["pabellon"], q["direccion"] = valores["pabellon"], valores["direccion"]
                material = True

            if estado_nuevo != q["estado"]:
                if estado_nuevo == "cancelado":
                    anotar(q, "cancelado", titulo, f"Texto FBM: {p.texto_estado}")
                elif estado_nuevo == "aplazado" and not aplazado_con_fecha:
                    anotar(q, "aplazado", titulo, f"Texto FBM: {p.texto_estado}. Sin nueva fecha todavía: "
                                                  "se mantiene en su fecha marcado como APLAZADO.")
                elif q["estado"] == "cancelado":
                    anotar(q, "reactivado", titulo, "Vuelve a figurar como partido programado.")
                elif q["estado"] == "aplazado" and estado_nuevo == "programado":
                    anotar(q, "aplazamiento_retirado", titulo, f"{fecha_es(q['fecha'])} {q['hora'] or 'hora pendiente'}")
                q["estado"] = estado_nuevo
                material = True
            elif p.texto_estado and p.texto_estado != q.get("texto_estado") and estado_nuevo == "programado":
                anotar(q, "aviso_fbm", titulo, p.texto_estado)
            q["texto_estado"] = p.texto_estado

            if p.marcador and p.marcador != q.get("marcador"):
                anotar(q, "resultado", titulo, p.marcador)
                q["marcador"] = p.marcador
                material = True

            if disc and disc != q.get("discrepancias"):
                anotar(q, "discrepancia", titulo, " | ".join(disc))
            if disc != q.get("discrepancias"):
                q["discrepancias"] = disc
                material = True

            q["competicion"] = g.competicion
            q["ultima_comprobacion"] = ahora_iso
            if material:
                q["secuencia"] += 1
                q["modificado"] = ahora_iso
                q["verificacion"] = {"tipo": "provisional", "en": None}

    # Partidos futuros que ya no aparecen: NO se borran; se marcan y se avisa.
    for q in partidos.values():
        if (q["grupo_id"] in grupos_procesados and q["clave"] not in vistos and q["estado"] != "cancelado"
                and not q.get("desaparecido_desde") and (q["fecha"] or "9999") >= hoy):
            q["desaparecido_desde"] = ahora_iso
            q["secuencia"] += 1
            q["modificado"] = ahora_iso
            anotar(q, "desaparecido", titulo_base(q, corto),
                   f"{fecha_es(q['fecha'])} {q['hora'] or ''}. Se mantiene en el calendario con aviso ⚠️.")

    # Verificación de la semana: lunes = primera comprobación, viernes = confirmación final.
    if modo in ("lunes", "viernes"):
        domingo = fin_de_semana(ahora.date()).isoformat()
        for q in partidos.values():
            if q["clave"] in vistos and q["fecha"] and hoy <= q["fecha"] <= domingo:
                q["verificacion"] = {"tipo": modo, "en": ahora_iso}

    est["ultima_comprobacion"] = ahora_iso
    return cambios
