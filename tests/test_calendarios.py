"""Pruebas con la página REAL de la FBM (guardada el 24/09/2026) y variaciones simuladas.

Ejecutar:  python -m unittest discover -s tests -v
"""
import copy
import gzip
import json
import os
import tempfile
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fbmcal.conciliar import conciliar_equipo, resolver_valores
from fbmcal.fuente import DatosContraste, Grupo, clave_contraste, leer_calendarios, leer_proximos_html, leer_proximos_xlsx
from fbmcal.ics import generar_ics, horario_evento
from fbmcal.main import main, resolver_modo
from fbmcal.util import TZ

# Las pruebas deben ser herméticas: en GitHub Actions estas variables existen y, si no se quitan,
# las ejecuciones simuladas escribirían un aviso falso (que acabaría como Issue) y ensuciarían el resumen.
for _var in ("AVISO_ARCHIVO", "GITHUB_STEP_SUMMARY", "PAGES_URL"):
    os.environ.pop(_var, None)

RAIZ = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
CONFIG = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
CADETE, INFANTIL, INFANTIL_PREF = CONFIG["equipos"]
HTML = gzip.decompress((FIX / "club_arganda_2026-09-24.html.gz").read_bytes()).decode("utf-8-sig")
XLSX = (FIX / "proximos_2026-09-24.xlsx").read_bytes()
GRUPOS = leer_calendarios(HTML)
CONTRASTE = [("próximos", leer_proximos_html(HTML)), ("excel", leer_proximos_xlsx(XLSX))]

LUNES = datetime(2026, 9, 28, 17, 3, tzinfo=TZ)
VIERNES = datetime(2026, 10, 2, 17, 4, tzinfo=TZ)
LUNES_SIG = datetime(2026, 10, 5, 17, 2, tzinfo=TZ)


def grupos():
    return copy.deepcopy(GRUPOS)


def cadete(gs):
    return next(g for g in gs if g.id == "17743")


def partido(g, jornada):
    return next(p for p in g.partidos if p.jornada == jornada and "ARGANDA" in p.local + p.visitante)


def ejecutar(cfg, est, gs, ahora=LUNES, modo="lunes", contraste=None):
    return conciliar_equipo(cfg, est, gs, CONTRASTE if contraste is None else contraste, ahora, modo, "2026-27")


def activos(est):
    return [q for q in est["partidos"].values() if q["estado"] != "cancelado"]


def por_jornada(est, j):
    return next(q for q in est["partidos"].values() if q["jornada"] == j)


class FuenteReal(unittest.TestCase):
    def test_encuentra_el_grupo_correcto_del_cadete(self):
        grupos_cadete_1 = [g for g in GRUPOS if g.categoria == "Cadete Masc. 1ºaño"]
        self.assertEqual([g.id for g in grupos_cadete_1], ["17743"])
        self.assertEqual(cadete(GRUPOS).competicion, "Cadete Masc. 1ºaño - PRIMERA FASE - GRUPO 3")

    def test_partido_jornada_1(self):
        p = partido(cadete(GRUPOS), 1)
        self.assertEqual((p.local, p.visitante, p.fecha, p.hora), ("C.B. COSLADA", "CB ARGANDA", "2026-10-03", "11:15"))
        self.assertEqual((p.pabellon, p.direccion), ("EL PLANTIO, PABELLON", "CALLE ALAMEDA, 7, Coslada"))

    def test_campo_por_determinar_no_se_inventa(self):
        p = partido(cadete(GRUPOS), 17)
        self.assertIsNone(p.pabellon)
        self.assertIsNone(p.direccion)

    def test_tabla_proximos_y_excel(self):
        k = clave_contraste("Cadete Masc. 1ºaño - PRIMERA FASE - GRUPO 3", "C.B. COSLADA", "CB ARGANDA")
        self.assertEqual(CONTRASTE[0][1][k].hora, "11:15")
        self.assertEqual(len(CONTRASTE[1][1]), 4)


class EquiposYCategorias(unittest.TestCase):
    def test_cadete_solo_toma_su_grupo(self):
        est = {}
        ejecutar(CADETE, est, grupos())
        self.assertEqual({q["grupo_id"] for q in est["partidos"].values()}, {"17743"})
        self.assertEqual(len(est["partidos"]), 20)  # 22 jornadas - 2 descansos
        self.assertTrue(all(q["equipo_fbm"] == "CB ARGANDA" for q in est["partidos"].values()))

    def test_infantil_no_se_confunde_con_infantil_preferente(self):
        self.assertTrue(any(g.categoria == "Infantil Masc. Pref." for g in GRUPOS))
        est = {}
        cambios = ejecutar(INFANTIL, est, grupos())
        self.assertEqual(est["partidos"], {})
        self.assertEqual(cambios, [])

    def test_infantil_se_anade_solo_cuando_la_fbm_lo_publique(self):
        gs = grupos()
        nuevo = copy.deepcopy(cadete(gs))
        nuevo.id, nuevo.categoria = "99999", "Infantil Masc. 1ºaño"
        nuevo.competicion = "Infantil Masc. 1ºaño - PRIMERA FASE - GRUPO 6"
        for p in nuevo.partidos:
            p.grupo_id, p.competicion = nuevo.id, nuevo.competicion
        gs.append(nuevo)
        est_c, est_i = {}, {}
        ejecutar(CADETE, est_c, gs)
        cambios = ejecutar(INFANTIL, est_i, gs)
        self.assertIn("grupo_nuevo", [c.tipo for c in cambios])
        self.assertEqual(len(est_i["partidos"]), 20)
        # Calendarios independientes: ni un UID compartido, ni un grupo mezclado.
        self.assertFalse(set(q["uid"] for q in est_c["partidos"].values())
                         & set(q["uid"] for q in est_i["partidos"].values()))
        self.assertEqual({q["grupo_id"] for q in est_c["partidos"].values()}, {"17743"})
        self.assertEqual({q["grupo_id"] for q in est_i["partidos"].values()}, {"99999"})

    def test_dos_equipos_del_club_en_el_mismo_grupo_no_se_adivina(self):
        gs = grupos()
        g = cadete(gs)
        for p in g.partidos:
            if p.local == "LICEO FRANCES":
                p.local = "CB ARGANDA B"
        est = {}
        cambios = ejecutar(CADETE, est, gs)
        self.assertEqual(est["partidos"], {})
        self.assertIn("error", [c.tipo for c in cambios])

    def test_categoria_con_nombre_distinto_avisa(self):
        gs = grupos()
        extra = copy.deepcopy(cadete(gs))
        extra.id, extra.categoria = "88888", "Infantil Masculino 1º año"
        gs.append(extra)
        cambios = ejecutar(INFANTIL, {}, gs)
        self.assertEqual([c.tipo for c in cambios], ["categoria_desconocida"])


class DeteccionDeCambios(unittest.TestCase):
    def setUp(self):
        self.est = {}
        ejecutar(CADETE, self.est, grupos())
        self.uids = {q["clave"]: q["uid"] for q in self.est["partidos"].values()}

    def assertSinDuplicados(self):
        self.assertEqual(len(self.est["partidos"]), 20)
        self.assertEqual(len({q["uid"] for q in self.est["partidos"].values()}), 20)

    def test_sin_cambios_no_hace_nada(self):
        cambios = ejecutar(CADETE, self.est, grupos(), VIERNES, "viernes")
        self.assertEqual(cambios, [])
        self.assertSinDuplicados()
        self.assertTrue(all(q["secuencia"] == 0 for q in self.est["partidos"].values()))

    def test_cambio_de_hora_modifica_el_mismo_evento(self):
        gs = grupos()
        partido(cadete(gs), 1).hora = "12:30"
        cambios = ejecutar(CADETE, self.est, gs, VIERNES, "viernes", contraste=[])
        self.assertEqual([(c.tipo, c.detalle) for c in cambios], [("cambio_hora", "11:15 → 12:30")])
        self.assertTrue(cambios[0].notificar)
        q = por_jornada(self.est, 1)
        self.assertEqual((q["hora"], q["secuencia"], q["uid"]), ("12:30", 1, self.uids[q["clave"]]))
        self.assertSinDuplicados()

    def test_hora_de_0000_a_oficial_no_avisa(self):
        gs = grupos()
        partido(cadete(gs), 2).hora = "17:00"
        cambios = ejecutar(CADETE, self.est, gs, LUNES_SIG, "lunes", contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["hora_confirmada"])
        self.assertFalse(cambios[0].notificar)

    def test_cambio_de_fecha(self):
        gs = grupos()
        partido(cadete(gs), 1).fecha = "2026-10-04"
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["cambio_fecha"])
        self.assertEqual(por_jornada(self.est, 1)["fecha"], "2026-10-04")
        self.assertSinDuplicados()

    def test_cambio_de_pabellon(self):
        gs = grupos()
        p = partido(cadete(gs), 1)
        p.pabellon, p.direccion = "LA CAÑADA, PABELLON", "AVDA. EJEMPLO, 1, Coslada"
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["cambio_pabellon"])
        self.assertSinDuplicados()

    def test_aplazado_sin_nueva_fecha(self):
        gs = grupos()
        partido(cadete(gs), 1).texto_estado = "APLAZADO"
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["aplazado"])
        ics = generar_ics(CADETE, self.est, CONFIG["evento"], "https://x", {}, LUNES)
        self.assertIn("SUMMARY:⏸️ APLAZADO · C.B. COSLADA vs CB Arganda", ics)

    def test_aplazado_con_nueva_fecha_mueve_el_evento(self):
        gs = grupos()
        p = partido(cadete(gs), 1)
        p.texto_estado, p.fecha, p.hora = "APLAZADO", "2026-10-21", "19:00"
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["aplazado", "cambio_hora"])
        q = por_jornada(self.est, 1)
        self.assertEqual((q["fecha"], q["hora"]), ("2026-10-21", "19:00"))
        self.assertSinDuplicados()

    def test_cancelado_se_elimina_del_calendario(self):
        gs = grupos()
        partido(cadete(gs), 1).texto_estado = "ANULADO"
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["cancelado"])
        ics = generar_ics(CADETE, self.est, CONFIG["evento"], "https://x", {}, LUNES)
        self.assertNotIn(por_jornada(self.est, 1)["uid"], ics)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 19)
        # Una segunda pasada no lo vuelve a crear ni vuelve a avisar.
        self.assertEqual(ejecutar(CADETE, self.est, gs, contraste=[]), [])

    def test_desaparece_no_se_borra_y_se_avisa(self):
        gs = grupos()
        g = cadete(gs)
        g.partidos.remove(partido(g, 3))
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["desaparecido"])
        ics = generar_ics(CADETE, self.est, CONFIG["evento"], "https://x", {}, LUNES)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 20)
        self.assertIn("SUMMARY:⚠️ ⏳ JANSEN BT \"B\" vs CB Arganda", ics)
        # Si vuelve a aparecer, se quita el aviso.
        cambios = ejecutar(CADETE, self.est, grupos(), contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["reaparecido"])
        self.assertSinDuplicados()

    def test_cambio_de_nombre_del_rival_no_duplica(self):
        gs = grupos()
        for p in cadete(gs).partidos:
            if p.local == "LICEO FRANCES":
                p.local = "LICEO FRANCES \"A\""
            if p.visitante == "LICEO FRANCES":
                p.visitante = "LICEO FRANCES \"A\""
        antes = por_jornada(self.est, 2)["uid"]
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["rival_renombrado", "rival_renombrado"])
        self.assertEqual(por_jornada(self.est, 2)["uid"], antes)
        self.assertSinDuplicados()

    def test_web_sin_partidos_del_equipo_no_toca_nada(self):
        gs = grupos()
        g = cadete(gs)
        g.partidos = [p for p in g.partidos if "ARGANDA" not in p.local + p.visitante]
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["error"])
        self.assertFalse(any(q.get("desaparecido_desde") for q in self.est["partidos"].values()))

    def test_grupo_retirado_de_la_web_mantiene_partidos(self):
        gs = [g for g in grupos() if g.id != "17743"]
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios], ["grupo_desaparecido"])
        self.assertEqual(len(activos(self.est)), 20)

    def test_segunda_fase_se_anade_como_competicion_nueva(self):
        gs = grupos()
        fase2 = copy.deepcopy(cadete(gs))
        fase2.id, fase2.fase = "18000", "SEGUNDA FASE"
        fase2.competicion = "Cadete Masc. 1ºaño - SEGUNDA FASE - GRUPO 1"
        for p in fase2.partidos:
            p.grupo_id, p.competicion = fase2.id, fase2.competicion
        gs.append(fase2)
        cambios = ejecutar(CADETE, self.est, gs, contraste=[])
        self.assertEqual([c.tipo for c in cambios if c.notificar], ["grupo_nuevo"])
        self.assertEqual(len(self.est["partidos"]), 40)


class Contraste(unittest.TestCase):
    def _p(self):
        return partido(cadete(grupos()), 1)

    def _k(self, p):
        return clave_contraste(p.competicion, p.local, p.visitante)

    def test_coinciden(self):
        valores, disc = resolver_valores(self._p(), CONTRASTE)
        self.assertEqual((valores["hora"], disc), ("11:15", []))

    def test_mayoria_de_fuentes(self):
        p = self._p()
        otras = [("próximos", {self._k(p): DatosContraste("2026-10-03", "12:00", p.pabellon, p.direccion)}),
                 ("excel", {self._k(p): DatosContraste("2026-10-03", "12:00", p.pabellon, p.direccion)})]
        valores, disc = resolver_valores(p, otras)
        self.assertEqual(valores["hora"], "12:00")
        self.assertIn("mayoría", disc[0])

    def test_empate_manda_el_calendario_oficial_y_se_indica(self):
        p = self._p()
        otras = [("próximos", {self._k(p): DatosContraste("2026-10-03", "12:00", p.pabellon, p.direccion)})]
        valores, disc = resolver_valores(p, otras)
        self.assertEqual(valores["hora"], "11:15")
        self.assertIn("prioridad del calendario oficial", disc[0])

    def test_dato_sin_publicar_no_es_contradiccion(self):
        p = self._p()
        p.hora = None
        valores, disc = resolver_valores(p, CONTRASTE)
        self.assertEqual((valores["hora"], disc), ("11:15", []))


class HorariosYZonaHoraria(unittest.TestCase):
    def test_modo_segun_el_dia(self):
        self.assertEqual(resolver_modo("auto", LUNES), "lunes")
        self.assertEqual(resolver_modo("auto", VIERNES), "viernes")
        self.assertEqual(resolver_modo("auto", datetime(2026, 9, 30, 17, tzinfo=TZ)), "manual")

    def test_evento_45_min_antes_y_2_horas(self):
        ini, fin = horario_evento({"fecha": "2026-10-03", "hora": "16:45"}, CONFIG["evento"])
        self.assertEqual((ini.strftime("%H:%M"), fin.strftime("%H:%M")), ("16:00", "18:45"))

    def test_hora_pendiente_a_las_0000(self):
        ini, fin = horario_evento({"fecha": "2026-10-10", "hora": None}, CONFIG["evento"])
        self.assertEqual((ini.strftime("%H:%M"), fin.strftime("%H:%M")), ("00:00", "02:00"))

    def test_horario_de_verano_e_invierno(self):
        # 24/10/2026 aún es CEST (UTC+2); 31/10/2026 ya es CET (UTC+1).
        v, _ = horario_evento({"fecha": "2026-10-24", "hora": "11:15"}, CONFIG["evento"])
        i, _ = horario_evento({"fecha": "2026-10-31", "hora": "11:15"}, CONFIG["evento"])
        self.assertEqual((v.utcoffset().seconds, i.utcoffset().seconds), (7200, 3600))
        self.assertEqual((v.strftime("%H:%M"), i.strftime("%H:%M")), ("10:30", "10:30"))

    def test_verificacion_lunes_y_confirmacion_viernes(self):
        est = {}
        ejecutar(CADETE, est, grupos(), LUNES, "lunes")
        self.assertEqual(por_jornada(est, 1)["verificacion"]["tipo"], "lunes")      # sábado 03/10
        self.assertEqual(por_jornada(est, 2)["verificacion"]["tipo"], "provisional")  # semana siguiente
        ejecutar(CADETE, est, grupos(), VIERNES, "viernes")
        self.assertEqual(por_jornada(est, 1)["verificacion"]["tipo"], "viernes")
        ics = generar_ics(CADETE, est, CONFIG["evento"], "https://x", {}, VIERNES)
        self.assertIn("CONFIRMADO en la comprobación final del viernes 02/10/2026", ics.replace("\r\n ", ""))


class HoraDeExtremoAExtremo(unittest.TestCase):
    """Hora en la FBM → Python → evento → .ics → lo que calcula un cliente de calendario (Apple).

    Única transformación permitida: el evento empieza `minutos_antes` (45) antes del partido, como se
    pidió («partido 16:45 → evento 16:00-18:45»). La hora del partido se conserva en la descripción."""

    def generar(self, html, config=None):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            (d / "c.html").write_text(html, encoding="utf-8")
            (d / "x.xlsx").write_bytes(XLSX)
            args = ["--html", str(d / "c.html"), "--xlsx", str(d / "x.xlsx"), "--estado", str(d / "e.json"),
                    "--salida", str(d / "docs"), "--ahora", "2026-09-28T17:03:00+02:00"]
            if config:
                (d / "cfg.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
                args += ["--config", str(d / "cfg.json")]
            self.assertEqual(main(args), 0)
            ics = (d / "docs" / CADETE["archivo_ics"]).read_bytes().decode("utf-8")  # conservar CRLF
        eventos = []
        for bloque in ics.replace("\r\n ", "").split("BEGIN:VEVENT")[1:]:
            eventos.append(dict(l.split(":", 1) for l in bloque.split("END:VEVENT")[0].split("\r\n") if ":" in l))
        return eventos

    @staticmethod
    def evento(eventos, dia):
        return next(e for e in eventos if e["DTSTART;TZID=Europe/Madrid"].startswith(dia))

    @staticmethod
    def como_cliente(valor):
        """Lo que hace Apple Calendar: hora local + TZID=Europe/Madrid -> instante real."""
        return datetime.strptime(valor, "%Y%m%dT%H%M%S").replace(tzinfo=TZ)

    def test_fbm_1230_se_conserva(self):
        html = HTML.replace("03/10/2026<br />11:15", "03/10/2026<br />12:30").replace("03/10/2026 11:15", "03/10/2026 12:30")
        ev = self.evento(self.generar(html), "20261003")
        ini = self.como_cliente(ev["DTSTART;TZID=Europe/Madrid"])
        fin = self.como_cliente(ev["DTEND;TZID=Europe/Madrid"])
        self.assertIn("🕐 Hora: 12:30", ev["DESCRIPTION"])
        self.assertEqual(ini + timedelta(minutes=45), datetime(2026, 10, 3, 12, 30, tzinfo=TZ))  # partido 12:30
        self.assertEqual((f"{ini:%H:%M}", f"{fin:%H:%M}"), ("11:45", "14:30"))
        self.assertEqual(f"{ini.astimezone(timezone.utc):%H:%M}", "09:45")  # 11:45 CEST = 09:45 UTC

    def test_sin_margen_el_evento_empieza_a_la_hora_exacta_de_la_fbm(self):
        cfg = copy.deepcopy(CONFIG)
        cfg["evento"]["minutos_antes"] = 0
        html = HTML.replace("03/10/2026<br />11:15", "03/10/2026<br />12:30").replace("03/10/2026 11:15", "03/10/2026 12:30")
        ev = self.evento(self.generar(html, cfg), "20261003")
        self.assertEqual(f"{self.como_cliente(ev['DTSTART;TZID=Europe/Madrid']):%H:%M}", "12:30")

    def test_horas_reales_en_verano_e_invierno(self):
        eventos = self.generar(HTML)
        #          día        hora FBM  inicio evento  desfase UTC (h)
        casos = [("20261003", "11:15", "10:30", 2),   # CEST (verano)
                 ("20261107", "14:30", "13:45", 1),   # CET (invierno, tras el 25/10/2026)
                 ("20270403", "16:00", "15:15", 2)]   # CEST de nuevo (tras el 28/03/2027)
        for dia, hora_fbm, inicio, desfase in casos:
            with self.subTest(dia=dia):
                ev = self.evento(eventos, dia)
                ini = self.como_cliente(ev["DTSTART;TZID=Europe/Madrid"])
                self.assertIn(f"🕐 Hora: {hora_fbm}", ev["DESCRIPTION"])
                self.assertEqual(f"{ini:%H:%M}", inicio)
                self.assertEqual(f"{ini + timedelta(minutes=45):%H:%M}", hora_fbm)
                self.assertEqual(ini.utcoffset(), timedelta(hours=desfase))

    def test_vtimezone_coincide_con_la_base_de_datos_oficial(self):
        # El VTIMEZONE del .ics dice: último domingo de marzo 02:00 -> UTC+2; último domingo de octubre 03:00 -> UTC+1.
        for anio in range(2026, 2031):
            for mes, antes, despues in ((3, 1, 2), (10, 2, 1)):
                dia = max(d for d in range(25, 32) if date(anio, mes, d).weekday() == 6)
                self.assertEqual(datetime(anio, mes, dia, 1, 0, tzinfo=TZ).utcoffset(), timedelta(hours=antes))
                self.assertEqual(datetime(anio, mes, dia, 4, 0, tzinfo=TZ).utcoffset(), timedelta(hours=despues))


class EjecucionCompleta(unittest.TestCase):
    """Simula el workflow: lunes y viernes programados, sin intervención manual."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "club.html").write_text(HTML, encoding="utf-8")
        (self.dir / "prox.xlsx").write_bytes(XLSX)

    def tearDown(self):
        self.tmp.cleanup()

    def correr(self, ahora, *extra):
        return main(["--html", str(self.dir / "club.html"), "--xlsx", str(self.dir / "prox.xlsx"),
                     "--estado", str(self.dir / "estado.json"), "--salida", str(self.dir / "docs"),
                     "--ahora", ahora, *extra])

    def test_lunes_y_viernes_programados(self):
        # Lunes 28/09/2026 15:03 UTC = 17:03 en Madrid (horario de verano).
        self.assertEqual(self.correr("2026-09-28T15:03:00+00:00", "--programado"), 0)
        estado = json.loads((self.dir / "estado.json").read_text(encoding="utf-8"))
        self.assertIn("2026-09-28-lunes", estado["ejecuciones"])
        # La ejecución de respaldo de las 18:45 no repite el trabajo.
        antes = (self.dir / "estado.json").read_text(encoding="utf-8")
        self.assertEqual(self.correr("2026-09-28T16:45:00+00:00", "--programado"), 0)
        self.assertEqual((self.dir / "estado.json").read_text(encoding="utf-8"), antes)
        # Viernes 02/10/2026 17:04 Madrid.
        self.assertEqual(self.correr("2026-10-02T15:04:00+00:00", "--programado"), 0)
        estado = json.loads((self.dir / "estado.json").read_text(encoding="utf-8"))
        self.assertIn("2026-10-02-viernes", estado["ejecuciones"])

    def test_respaldo_hace_el_trabajo_si_la_principal_no_se_ejecuto(self):
        # Viernes 02/10/2026: GitHub se salta la de las 17:05 -> la de las 18:45 hace la confirmación.
        self.assertEqual(self.correr("2026-10-02T16:45:00+00:00", "--programado"), 0)
        estado = json.loads((self.dir / "estado.json").read_text(encoding="utf-8"))
        self.assertIn("2026-10-02-viernes", estado["ejecuciones"])
        j1 = next(q for q in estado["equipos"]["cadete-masc-1-ano"]["partidos"].values() if q["jornada"] == 1)
        self.assertEqual(j1["verificacion"]["tipo"], "viernes")

    def test_pagina_apunta_a_los_ics_reales(self):
        self.correr("2026-09-28T17:03:00+02:00")
        docs = self.dir / "docs"
        index = (docs / "index.html").read_text(encoding="utf-8")
        for cfg in (CADETE, INFANTIL, INFANTIL_PREF):
            self.assertTrue((docs / cfg["archivo_ics"]).exists())
            self.assertIn(f'data-ics="{cfg["archivo_ics"]}" href="{cfg["archivo_ics"]}"', index)
        self.assertEqual(sorted(p.name for p in docs.iterdir()),
                         [".nojekyll", "cadete-masculino-1-ano.ics", "estado.json", "index.html",
                          "infantil-masculino-1-ano.ics", "infantil-masculino-preferente.ics"])

    def test_invierno_cron_en_hora_de_madrid(self):
        # Lunes 26/10/2026 (ya en CET): 15:30 UTC = 16:30 Madrid -> no toca; 16:05 UTC = 17:05 -> sí.
        self.assertEqual(self.correr("2026-10-26T15:30:00+00:00", "--programado"), 0)
        self.assertFalse((self.dir / "estado.json").exists())
        self.assertEqual(self.correr("2026-10-26T16:05:00+00:00", "--programado"), 0)
        self.assertTrue((self.dir / "estado.json").exists())

    def test_ics_valido_y_calendarios_separados(self):
        self.correr("2026-09-28T17:03:00+02:00")
        cad = (self.dir / "docs" / CADETE["archivo_ics"]).read_bytes()
        inf = (self.dir / "docs" / INFANTIL["archivo_ics"]).read_bytes()
        for datos in (cad, inf):
            texto = datos.decode("utf-8")
            self.assertTrue(texto.startswith("BEGIN:VCALENDAR\r\n") and texto.endswith("END:VCALENDAR\r\n"))
            self.assertTrue(all(len(l) <= 75 for l in datos.split(b"\r\n")))
            self.assertEqual(texto.count("BEGIN:VEVENT"), texto.count("END:VEVENT"))
        self.assertEqual(cad.decode().count("BEGIN:VEVENT"), 20)
        self.assertEqual(inf.decode().count("BEGIN:VEVENT"), 0)
        self.assertIn("X-WR-CALNAME:CB Arganda · Infantil Masc. 1º año", inf.decode())
        # Repetir la ejecución no duplica eventos.
        self.correr("2026-10-02T17:04:00+02:00")
        cad2 = (self.dir / "docs" / CADETE["archivo_ics"]).read_text(encoding="utf-8")
        self.assertEqual(cad2.count("BEGIN:VEVENT"), 20)

    def test_fuente_rota_no_modifica_nada(self):
        (self.dir / "club.html").write_text("<html><body>Mantenimiento</body></html>", encoding="utf-8")
        self.assertEqual(self.correr("2026-09-28T17:03:00+02:00"), 1)
        self.assertFalse((self.dir / "estado.json").exists())
        self.assertFalse((self.dir / "docs").exists())

    def instantanea(self):
        archivos = [self.dir / "estado.json", *sorted((self.dir / "docs").iterdir())]
        return {p.name: p.read_bytes() for p in archivos}

    def test_fallo_posterior_conserva_los_calendarios_buenos(self):
        self.assertEqual(self.correr("2026-09-28T17:03:00+02:00"), 0)
        buenos = self.instantanea()
        # 1) La web de la FBM devuelve una página sin calendarios.
        (self.dir / "club.html").write_text("<html><body>Error 500</body></html>", encoding="utf-8")
        self.assertEqual(self.correr("2026-10-02T17:04:00+02:00"), 1)
        self.assertEqual(self.instantanea(), buenos)
        # 2) La web devuelve HTML truncado a mitad de un calendario.
        (self.dir / "club.html").write_text(HTML[: HTML.index("capa_calendario_17743") - 200], encoding="utf-8")
        self.assertEqual(self.correr("2026-10-02T17:04:00+02:00"), 1)
        self.assertEqual(self.instantanea(), buenos)
        # 2b) La descarga se corta DENTRO del calendario del cadete (faltan jornadas): no se marca
        #     ningún partido como desaparecido; se detecta la página incompleta y no se toca nada.
        (self.dir / "club.html").write_text(HTML[: HTML.index("capa_calendario_17743") + 20000], encoding="utf-8")
        self.assertEqual(self.correr("2026-10-02T17:04:00+02:00"), 1)
        self.assertEqual(self.instantanea(), buenos)
        # 3) Fallo al generar un calendario: no se escribe nada a medias.
        (self.dir / "club.html").write_text(HTML, encoding="utf-8")
        from unittest import mock
        with mock.patch("fbmcal.main.generar_ics", side_effect=["BEGIN:VCALENDAR", RuntimeError("fallo simulado")]) as m:
            self.assertEqual(self.correr("2026-10-02T17:04:00+02:00"), 1)
        self.assertEqual(m.call_count, 2)  # el 1er .ics se generó, el 2º falló: aun así nada se escribió
        self.assertEqual(self.instantanea(), buenos)
        self.assertFalse(list(self.dir.rglob("*.tmp")))

    def test_sin_credenciales_y_estado_publico(self):
        import os
        import re
        # El código de los calendarios solo lee variables NO sensibles (rutas y la URL pública).
        # Los secretos de Telegram solo los lee fbmcal/telegram.py (el paso de envío, que va DESPUÉS de publicar).
        leidas = {}
        for py in (RAIZ / "fbmcal").glob("*.py"):
            leidas[py.name] = set(re.findall(r'environ\.get\("([A-Z_]+)"', py.read_text(encoding="utf-8")))
        calendarios = set().union(*(v for k, v in leidas.items() if k != "telegram.py"))
        self.assertEqual(calendarios, {"AVISO_ARCHIVO", "GITHUB_STEP_SUMMARY", "PAGES_URL", "ERROR_ARCHIVO"})
        self.assertEqual(leidas["telegram.py"] - {"GITHUB_STEP_SUMMARY", "ERROR_ARCHIVO"},
                         {"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"})
        aviso = self.dir / "aviso.md"
        resumen = self.dir / "resumen.md"
        with unittest.mock.patch.dict(os.environ, {"AVISO_ARCHIVO": str(aviso), "GITHUB_STEP_SUMMARY": str(resumen)}):
            self.assertEqual(self.correr("2026-09-28T17:03:00+02:00"), 0)
        estado = json.loads((self.dir / "docs" / "estado.json").read_text(encoding="utf-8"))
        self.assertEqual(estado["resultado"], "ok")
        self.assertEqual(estado["equipos"]["cadete-masc-1-ano"]["partidos_en_calendario"], 20)
        self.assertEqual(estado["equipos"]["infantil-masc-1-ano"]["partidos_en_calendario"], 0)
        self.assertEqual(estado["equipos"]["infantil-masc-pref"]["partidos_en_calendario"], 22)
        self.assertIn("Cadete Masc. 1ºaño - PRIMERA FASE - GRUPO 3", resumen.read_text(encoding="utf-8"))
        # Primera ejecución: avisa de la competición detectada (no de cada partido nuevo).
        titulo = aviso.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(titulo.startswith("🏀 2 novedades"))  # cadete + infantil preferente
        # Sin cambios -> sin aviso.
        aviso.unlink()
        with unittest.mock.patch.dict(os.environ, {"AVISO_ARCHIVO": str(aviso)}):
            self.assertEqual(self.correr("2026-10-02T17:04:00+02:00"), 0)
        self.assertFalse(aviso.exists())
        # Ningún archivo publicado contiene emails ni credenciales.
        for p in (self.dir / "docs").iterdir():
            texto = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"[\w.+-]+@(?!calendarios-cb-arganda)[\w-]+\.[a-z]{2,}", texto), p.name)


if __name__ == "__main__":
    unittest.main()
