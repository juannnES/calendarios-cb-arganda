"""Descarga y lectura de la fuente oficial: la web de la Federación de Baloncesto de Madrid.

La página del club (https://www.fbm.es/resultados-club-6917/baloncesto-arganda) es HTML
generado en servidor (sin JavaScript ni Cloudflare) y contiene:
  * la tabla "PRÓXIMOS PARTIDOS" del club, y
  * el CALENDARIO completo de cada grupo en el que juega un equipo del club.
Además, la FBM ofrece la misma tabla de próximos partidos exportada a XLSX, que usamos como
tercera representación oficial para contrastar fecha, hora y pabellón.
"""
import io
import re
import time
import urllib.request
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .util import normalizar

UA = "Mozilla/5.0 (compatible; calendarios-cb-arganda/1.0; uso personal, 2 consultas/semana)"

RE_FECHA = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
RE_HORA = re.compile(r"\b(\d{1,2}):(\d{2})\b")
RE_JORNADA = re.compile(r"Jornada\s+(\d+)", re.I)


class FuenteError(Exception):
    """La fuente oficial no se ha podido descargar o su formato ha cambiado."""


@dataclass
class PartidoFuente:
    grupo_id: str
    competicion: str
    jornada: int | None
    local: str
    visitante: str
    fecha: str | None  # ISO AAAA-MM-DD
    hora: str | None  # HH:MM
    pabellon: str | None
    direccion: str | None
    marcador: str | None = None
    texto_estado: str | None = None


@dataclass
class Grupo:
    id: str
    competicion: str  # "Cadete Masc. 1ºaño - PRIMERA FASE - GRUPO 3"
    categoria: str
    fase: str
    grupo: str
    partidos: list[PartidoFuente] = field(default_factory=list)


@dataclass
class DatosContraste:
    """Fecha/hora/pabellón de un partido según una fuente secundaria."""
    fecha: str | None
    hora: str | None
    pabellon: str | None
    direccion: str | None


def descargar(url: str, intentos: int = 3, espera: int = 20) -> bytes:
    ultimo = None
    for i in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - reintentamos cualquier error de red
            ultimo = e
            if i < intentos - 1:
                time.sleep(espera)
    raise FuenteError(f"No se pudo descargar {url}: {ultimo}")


def _lineas(tag) -> list[str]:
    return [l.strip() for l in tag.get_text("\n").split("\n") if l.strip()]


def _fecha_hora(textos: list[str]) -> tuple[str | None, str | None, str | None]:
    """Extrae fecha, hora y cualquier texto extra (p. ej. 'APLAZADO') de una celda."""
    fecha = hora = None
    extra = []
    for t in textos:
        m = RE_FECHA.search(t)
        if m and not fecha:
            fecha = f"{m[3]}-{int(m[2]):02d}-{int(m[1]):02d}"
            t = RE_FECHA.sub("", t, count=1).strip()
        h = RE_HORA.search(t)
        if h and not hora:
            hora = f"{int(h[1]):02d}:{h[2]}"
            t = RE_HORA.sub("", t, count=1).strip()
        if t:
            extra.append(t)
    if hora == "00:00":  # la FBM no programa a medianoche: lo tratamos como hora sin publicar
        hora = None
    return fecha, hora, (" ".join(extra) or None)


def _campo(textos: list[str]) -> tuple[str | None, str | None]:
    """Pabellón y dirección. 'CAMPO POR DETERMINAR' / '..., Madrid' significan 'aún sin publicar'."""
    if not textos:
        return None, None
    pabellon = textos[0]
    direccion = ", ".join(textos[1:]) or None
    if normalizar(pabellon) in ("", "campopordeterminar", "pordeterminar"):
        return None, None
    if direccion and direccion.lstrip().startswith("..."):
        direccion = None
    return pabellon, direccion


def _partes_competicion(titulo: str) -> tuple[str, str, str]:
    partes = [p.strip() for p in titulo.split(" - ") if p.strip()]
    if len(partes) >= 3:
        return " - ".join(partes[:-2]), partes[-2], partes[-1]
    return titulo, "", ""


def leer_calendarios(html: str) -> list[Grupo]:
    """Lee la sección CALENDARIOS de la página del club: un bloque por grupo de competición."""
    soup = BeautifulSoup(html, "html.parser")
    grupos = []
    for cab in soup.find_all("header", id=re.compile(r"^pestana_calendario_\d+$")):
        gid = cab["id"].rsplit("_", 1)[1]
        titulo = " ".join(cab.get_text(" ").split())
        categoria, fase, nombre_grupo = _partes_competicion(titulo)
        grupo = Grupo(gid, titulo, categoria, fase, nombre_grupo)
        capa = soup.find(id=f"capa_calendario_{gid}")
        if capa is None:
            raise FuenteError(f"El grupo {titulo or gid} no tiene bloque de calendario (¿página incompleta o cambió la web?)")
        for bloque in capa.find_all("div", class_="capa_cien_cinco"):
            h6 = bloque.find("h6")
            mj = RE_JORNADA.search(h6.get_text(" ")) if h6 else None
            jornada = int(mj[1]) if mj else None
            tabla = bloque.find("table")
            if tabla is None:
                continue
            for tr in (tabla.find("tbody") or tabla).find_all("tr"):
                tds = tr.find_all("td", recursive=False)
                if len(tds) < 6:
                    continue
                local = " ".join(tds[0].get_text(" ").split())
                visitante = " ".join(tds[3].get_text(" ").split())
                pts_l = " ".join(tds[1].get_text(" ").split())
                pts_v = " ".join(tds[2].get_text(" ").split())
                fecha, hora, extra = _fecha_hora(_lineas(tds[4]))
                pabellon, direccion = _campo(_lineas(tds[5]))
                marcador = None
                textos_estado = [extra] if extra else []
                if pts_l.isdigit() and pts_v.isdigit():
                    marcador = f"{pts_l}-{pts_v}"
                else:
                    textos_estado += [t for t in (pts_l, pts_v) if t]
                grupo.partidos.append(PartidoFuente(
                    grupo_id=gid, competicion=titulo, jornada=jornada,
                    local=local, visitante=visitante, fecha=fecha, hora=hora,
                    pabellon=pabellon, direccion=direccion, marcador=marcador,
                    texto_estado=" ".join(textos_estado) or None,
                ))
        grupos.append(grupo)
    return grupos


def clave_contraste(competicion: str, local: str, visitante: str) -> tuple[str, str, str]:
    return normalizar(competicion), normalizar(local), normalizar(visitante)


def leer_proximos_html(html: str) -> dict[tuple, DatosContraste]:
    """Lee la tabla 'PRÓXIMOS PARTIDOS' (Categoría | Encuentro | Fecha | Campo)."""
    soup = BeautifulSoup(html, "html.parser")
    res = {}
    for tabla in soup.find_all("table"):
        cab = [normalizar(th.get_text()) for th in tabla.find_all("th")]
        if cab[:4] != ["categoria", "encuentro", "fecha", "campo"]:
            continue
        for tr in tabla.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 4:
                continue
            comp = " - ".join(_lineas(tds[0]))
            equipos = _lineas(tds[1])
            if len(equipos) < 2:
                continue
            fecha, hora, _ = _fecha_hora(_lineas(tds[2]))
            pabellon, direccion = _campo(_lineas(tds[3]))
            res[clave_contraste(comp, equipos[0], equipos[1])] = DatosContraste(fecha, hora, pabellon, direccion)
    return res


def leer_proximos_xlsx(datos: bytes) -> dict[tuple, DatosContraste]:
    """Lee el XLSX oficial de próximos partidos del club (cada partido ocupa 2 filas)."""
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(datos), data_only=True)  # read_only pierde filas en este XLSX
    res = {}
    for ws in wb.worksheets:
        filas = [[str(c).strip() for c in fila if c is not None and str(c).strip()]
                 for fila in ws.iter_rows(values_only=True)]
        filas = [f for f in filas if f]  # el informe intercala filas vacías
        for i, f in enumerate(filas):
            if len(f) < 3 or "\n" not in f[0] or not any(RE_FECHA.search(c) for c in f):
                continue
            comp = " - ".join(l.strip() for l in f[0].split("\n") if l.strip())
            local = f[1]
            celda_fecha = next(c for c in f if RE_FECHA.search(c))
            campo = [c for c in f[2:] if c != celda_fecha]
            sig = filas[i + 1] if i + 1 < len(filas) else []
            if not sig:
                continue
            visitante = sig[0]
            fecha, hora, _ = _fecha_hora([celda_fecha] + [c for c in sig[1:] if RE_HORA.fullmatch(c)])
            pabellon, direccion = _campo([l.strip() for l in (campo[-1] if campo else "").split("\n") if l.strip()])
            res[clave_contraste(comp, local, visitante)] = DatosContraste(fecha, hora, pabellon, direccion)
    return res
