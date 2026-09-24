"""Pruebas con la página REAL de la FBM (guardada el 24/09/2026) y variaciones simuladas.

Ejecutar:  python -m unittest discover -s tests -v
"""
import copy
import gzip
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fbmcal.conciliar import conciliar_equipo, resolver_valores
from fbmcal.fuente import DatosContraste, Grupo, clave_contraste, leer_calendarios, leer_proximos_html, leer_proximos_xlsx
from fbmcal.ics import generar_ics, horario_evento
from fbmcal.main import main, resolver_modo
from fbmcal.util import TZ

RAIZ = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures"
CONFIG = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
CADETE, INFANTIL = CONFIG["equipos"]
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
                     "--ahora", ahora, "--sin-email", *extra])

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


if __name__ == "__main__":
    unittest.main()
