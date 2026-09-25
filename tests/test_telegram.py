"""Pruebas de los avisos de Telegram y del tercer calendario (Infantil Masc. Preferente).

Nunca se usa un token real ni se conecta con Telegram: la API se sustituye por funciones falsas.
Ejecutar:  python -m unittest discover -s tests -t . -v
"""
import copy
import io
import json
import os
import re
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

from fbmcal import telegram
from fbmcal.avisos_telegram import aplicar_marcas, preparar_mensajes
from fbmcal.conciliar import conciliar_equipo
from fbmcal.ics import generar_ics
from fbmcal.main import main
from fbmcal.util import TZ
from tests.test_calendarios import CONFIG, GRUPOS, HTML, XLSX

for _var in ("AVISO_ARCHIVO", "GITHUB_STEP_SUMMARY", "PAGES_URL", "ERROR_ARCHIVO",
             "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ.pop(_var, None)

CADETE, INFANTIL, PREF = CONFIG["equipos"]


# Red de seguridad: ninguna prueba puede conectarse a Telegram (ni a ningún otro sitio).
def _sin_red(*args, **kwargs):
    raise AssertionError("Una prueba ha intentado conectarse a Internet")


_bloqueo_red = unittest.mock.patch("urllib.request.urlopen", _sin_red)


def setUpModule():
    _bloqueo_red.start()


def tearDownModule():
    _bloqueo_red.stop()
TOKEN_FALSO = "123456:TOKEN-FALSO-DE-PRUEBA"

JUEVES = datetime(2026, 9, 24, 21, 0, tzinfo=TZ)
MARTES = datetime(2026, 9, 29, 17, 5, tzinfo=TZ)
LUNES = datetime(2026, 9, 28, 17, 5, tzinfo=TZ)
LUNES_RESPALDO = datetime(2026, 9, 28, 18, 45, tzinfo=TZ)
VIERNES = datetime(2026, 10, 2, 17, 5, tzinfo=TZ)
VIERNES_RESPALDO = datetime(2026, 10, 2, 18, 45, tzinfo=TZ)


def grupos():
    return copy.deepcopy(GRUPOS)


def grupo(gs, gid="17743"):
    return next(g for g in gs if g.id == gid)


def partido(g, jornada):
    return next(p for p in g.partidos if p.jornada == jornada and "ARGANDA" in p.local + p.visitante)


def correr(est, gs, ahora, modo="manual", cfg=CADETE, politica=None):
    """Conciliación + preparación de avisos, igual que en main.py."""
    cambios = {cfg["id"]: conciliar_equipo(cfg, est, gs, [], ahora, modo, "2026-27", politica)}
    mensajes, marcas = preparar_mensajes(cambios, {"equipos": {cfg["id"]: est}}, {"equipos": [cfg]},
                                         modo, ahora, "2026-09-24T21:00+02:00")
    aplicar_marcas(marcas)
    return mensajes


def de_clase(mensajes, clase):
    return [m for m in mensajes if m["clase"] == clase]


class AvisosDePartidos(unittest.TestCase):
    def setUp(self):
        self.est = {}
        self.iniciales = correr(self.est, grupos(), JUEVES)

    # ---------------------------------------------------------------- creación
    def test_creacion_de_partido(self):
        nuevos = de_clase(self.iniciales, "NUEVO")
        self.assertEqual(len(nuevos), 20)
        j1 = nuevos[0]["texto"]
        for linea in ("🏀 NUEVO PARTIDO", "Equipo: CB Arganda Cadete 1º Año", "🆚 Rival: C.B. COSLADA",
                      "📅 Fecha: Sábado 03/10/2026", "🕐 Hora: 11:15", "📍 Pabellón: EL PLANTIO, PABELLON",
                      "🏠 Local/Visitante: Visitante", "🏆 Jornada: 1", "📅 Calendario: Cadete 1º Año"):
            self.assertIn(linea, j1)
        self.assertEqual(len(de_clase(self.iniciales, "AVISO")), 1)  # nueva competición detectada

    def test_partidos_que_ya_existian_se_anuncian_una_vez(self):
        for q in self.est["partidos"].values():  # estado creado antes de existir Telegram
            q.pop("avisos_telegram", None)
        self.assertEqual(len(de_clase(correr(self.est, grupos(), MARTES), "NUEVO")), 20)
        self.assertEqual(correr(self.est, grupos(), MARTES), [])

    def test_sin_cambios_no_hay_mensajes(self):
        for _ in range(10):
            self.assertEqual(correr(self.est, grupos(), MARTES), [])

    # ---------------------------------------------------------------- modificaciones
    def test_cambio_de_hora(self):
        gs = grupos()
        partido(grupo(gs), 1).hora = "12:30"
        m = correr(self.est, gs, MARTES)
        self.assertEqual([x["clase"] for x in m], ["MODIFICADO"])
        for linea in ("🔄 CAMBIO DE HORA", "🏀 CB Arganda Cadete 1º Año", "🆚 C.B. COSLADA",
                      "🕐 Antes: 11:15", "🕐 Ahora: 12:30", "📅 Sábado 03/10/2026", "📍 EL PLANTIO, PABELLON",
                      "Calendario: Cadete 1º Año"):
            self.assertIn(linea, m[0]["texto"])
        # La misma modificación vista otra vez (10 ejecuciones): ningún mensaje más.
        for _ in range(10):
            self.assertEqual(correr(self.est, gs, MARTES), [])

    def test_hora_publicada_tras_00_00(self):
        gs = grupos()
        partido(grupo(gs), 2).hora = "17:00"
        m = correr(self.est, gs, MARTES)
        self.assertEqual(len(m), 1)
        self.assertIn("🕐 Antes: Pendiente", m[0]["texto"])
        self.assertIn("🕐 Ahora: 17:00", m[0]["texto"])

    def test_cambio_de_fecha(self):
        gs = grupos()
        partido(grupo(gs), 1).fecha = "2026-10-10"
        m = correr(self.est, gs, MARTES)
        self.assertEqual(len(m), 1)
        for linea in ("📅 CAMBIO DE FECHA", "📅 Antes: Sábado 03/10/2026", "📅 Ahora: Sábado 10/10/2026",
                      "🕐 Hora: 11:15", "📍 Pabellón: EL PLANTIO, PABELLON"):
            self.assertIn(linea, m[0]["texto"])

    def test_cambio_de_pabellon(self):
        gs = grupos()
        p = partido(grupo(gs), 1)
        p.pabellon, p.direccion = "LA CAÑADA, PABELLON", "AVDA. EJEMPLO, 1, Coslada"
        m = correr(self.est, gs, MARTES)
        self.assertEqual(len(m), 1)
        self.assertIn("📍 CAMBIO DE PABELLÓN", m[0]["texto"])
        self.assertIn("📍 Antes:\nEL PLANTIO, PABELLON\nCALLE ALAMEDA, 7, Coslada", m[0]["texto"])
        self.assertIn("📍 Ahora:\nLA CAÑADA, PABELLON\nAVDA. EJEMPLO, 1, Coslada", m[0]["texto"])

    def test_cambio_de_rival(self):
        gs = grupos()
        for p in grupo(gs).partidos:
            p.local = 'LICEO FRANCES "A"' if p.local == "LICEO FRANCES" else p.local
            p.visitante = 'LICEO FRANCES "A"' if p.visitante == "LICEO FRANCES" else p.visitante
        m = correr(self.est, gs, MARTES)
        self.assertEqual(len(m), 2)  # ida y vuelta
        self.assertIn("🔄 INFORMACIÓN ACTUALIZADA", m[0]["texto"])
        self.assertIn("🆚 Antes: LICEO FRANCES", m[0]["texto"])
        self.assertIn('🆚 Ahora: LICEO FRANCES "A"', m[0]["texto"])

    def test_intercambio_local_visitante_mismo_evento(self):
        uid = next(q["uid"] for q in self.est["partidos"].values() if q["jornada"] == 1)
        gs = grupos()
        p = partido(grupo(gs), 1)
        p.local, p.visitante = p.visitante, p.local
        m = correr(self.est, gs, MARTES)
        self.assertEqual([(x["clase"], x["uid"]) for x in m], [("MODIFICADO", uid)])
        self.assertIn("🏠 Local/Visitante: Visitante → Local", m[0]["texto"])
        self.assertEqual(len(self.est["partidos"]), 20)

    # ---------------------------------------------------------------- aplazamientos y cancelaciones
    def test_aplazado_sin_nueva_fecha_y_luego_con_fecha(self):
        gs = grupos()
        partido(grupo(gs), 1).texto_estado = "APLAZADO"
        m = correr(self.est, gs, MARTES)
        self.assertEqual([x["clase"] for x in m], ["APLAZADO"])
        for linea in ("⚠️ PARTIDO APLAZADO", "📅 Fecha anterior: Sábado 03/10/2026", "🕐 Hora anterior: 11:15",
                      "Estado: APLAZADO", "Nueva fecha: pendiente"):
            self.assertIn(linea, m[0]["texto"])
        # Más tarde la FBM publica la nueva fecha (sigue marcado como aplazado): otro aviso con el horario.
        p = partido(grupo(gs), 1)
        p.fecha, p.hora = "2026-10-21", "19:00"
        m = correr(self.est, gs, datetime(2026, 10, 6, 17, 5, tzinfo=TZ))
        self.assertEqual([x["clase"] for x in m], ["APLAZADO"])  # sin avisos sueltos de fecha/hora
        self.assertIn("📅 Nueva fecha: Miércoles 21/10/2026", m[0]["texto"])
        self.assertIn("🕐 Nueva hora: 19:00", m[0]["texto"])

    def test_nuevo_horario_cuando_deja_de_estar_aplazado(self):
        gs = grupos()
        partido(grupo(gs), 1).texto_estado = "APLAZADO"
        correr(self.est, gs, MARTES)
        p = partido(grupo(gs), 1)
        p.texto_estado, p.fecha, p.hora = None, "2026-10-21", "19:00"
        m = correr(self.est, gs, datetime(2026, 10, 6, 17, 5, tzinfo=TZ))
        self.assertEqual(len(m), 1)
        self.assertIn("📅 NUEVO HORARIO TRAS EL APLAZAMIENTO", m[0]["texto"])
        self.assertIn("📅 Fecha: Miércoles 21/10/2026", m[0]["texto"])

    def test_cancelacion(self):
        gs = grupos()
        partido(grupo(gs), 1).texto_estado = "ANULADO"
        m = correr(self.est, gs, MARTES)
        self.assertEqual([x["clase"] for x in m], ["CANCELADO"])
        self.assertIn("❌ PARTIDO CANCELADO", m[0]["texto"])
        self.assertIn("marcado como CANCELADO por la fuente oficial", m[0]["texto"])
        self.assertEqual(correr(self.est, gs, MARTES), [])

    # ---------------------------------------------------------------- desaparición / eliminación
    def _sin_jornada_3(self):
        gs = grupos()
        g = grupo(gs)
        g.partidos.remove(partido(g, 3))
        return gs

    def test_desaparicion_temporal_no_elimina(self):
        m = correr(self.est, self._sin_jornada_3(), MARTES)
        self.assertEqual([x["clase"] for x in m], ["MODIFICADO"])
        self.assertIn("⚠️ POSIBLE DESAPARICIÓN", m[0]["texto"])
        self.assertIn("NO se ha eliminado", m[0]["texto"])
        ics = generar_ics(CADETE, self.est, CONFIG["evento"], "https://x", {}, MARTES)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 20)

    def test_eliminacion_tras_varias_comprobaciones(self):
        gs = self._sin_jornada_3()
        self.assertEqual(len(correr(self.est, gs, MARTES)), 1)                                      # 29/09 ⚠️
        self.assertEqual(correr(self.est, gs, VIERNES, "manual"), [])                              # 02/10
        m = correr(self.est, gs, datetime(2026, 10, 6, 17, 5, tzinfo=TZ))                          # 06/10
        self.assertEqual([x["clase"] for x in m], ["ELIMINADO"])
        self.assertIn("🗑️ PARTIDO ELIMINADO", m[0]["texto"])
        self.assertIn("porque la fuente oficial ya no lo publica", m[0]["texto"])
        ics = generar_ics(CADETE, self.est, CONFIG["evento"], "https://x", {}, MARTES)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 19)
        self.assertEqual(correr(self.est, gs, datetime(2026, 10, 9, 17, 5, tzinfo=TZ)), [])
        # Si vuelve a publicarse, vuelve al calendario con su mismo UID y se avisa.
        m = correr(self.est, grupos(), datetime(2026, 10, 12, 17, 5, tzinfo=TZ))
        self.assertEqual(len(m), 1)
        self.assertIn("PROGRAMADO", m[0]["texto"])
        self.assertEqual(generar_ics(CADETE, self.est, CONFIG["evento"], "https://x", {}, MARTES).count("BEGIN:VEVENT"), 20)

    def test_eliminacion_desactivable(self):
        gs = self._sin_jornada_3()
        for dia in (29, 30, 1, 2, 3, 5, 6, 8, 9):
            ahora = datetime(2026, 9 if dia > 20 else 10, dia, 17, 5, tzinfo=TZ)
            correr(self.est, gs, ahora, politica={"eliminar_tras_comprobaciones": 0})
        self.assertTrue(all(q["estado"] != "eliminado" for q in self.est["partidos"].values()))

    # ---------------------------------------------------------------- lunes / viernes
    def test_verificacion_del_lunes_y_confirmacion_del_viernes(self):
        m = correr(self.est, grupos(), LUNES, "lunes")
        self.assertEqual([x["clase"] for x in m], ["VERIFICADO"])
        for linea in ("🔎 PARTIDO DETECTADO", "📅 Sábado 03/10/2026", "Estado: VERIFICADO", "Viernes 17:05"):
            self.assertIn(linea, m[0]["texto"])
        self.assertEqual(correr(self.est, grupos(), LUNES_RESPALDO, "lunes"), [])  # respaldo 18:45: nada
        m = correr(self.est, grupos(), VIERNES, "viernes")
        self.assertEqual([x["clase"] for x in m], ["CONFIRMADO"])
        for linea in ("✅ PARTIDO CONFIRMADO", "📅 Sábado 03/10/2026", "🕐 11:15", "📍 EL PLANTIO, PABELLON",
                      "comprobada nuevamente en la fuente oficial"):
            self.assertIn(linea, m[0]["texto"])
        self.assertEqual(correr(self.est, grupos(), VIERNES_RESPALDO, "viernes"), [])

    # ---------------------------------------------------------------- errores
    def test_error_de_un_grupo(self):
        gs = grupos()
        for p in grupo(gs).partidos:
            p.local = "CB ARGANDA B" if p.local == "LICEO FRANCES" else p.local
        m = correr({}, gs, MARTES)
        self.assertEqual([x["clase"] for x in m], ["ERROR"])
        for linea in ("🚨 ERROR EN LA AUTOMATIZACIÓN", "Causa:", "Última comprobación correcta:",
                      "24/09/2026 21:00", "Los calendarios anteriores se han conservado."):
            self.assertIn(linea, m[0]["texto"])
        cola, n1 = telegram.encolar(telegram.cola_vacia(), m, MARTES)
        cola, n2 = telegram.encolar(cola, correr({}, gs, VIERNES), VIERNES)  # mismo error 3 días después
        self.assertEqual((n1, n2), (1, 0))


class TresEquipos(unittest.TestCase):
    def test_infantil_preferente_real_y_separado(self):
        est_c, est_i, est_p = {}, {}, {}
        mc = correr(est_c, grupos(), JUEVES, cfg=CADETE)
        mi = correr(est_i, grupos(), JUEVES, cfg=INFANTIL)
        mp = correr(est_p, grupos(), JUEVES, cfg=PREF)
        self.assertEqual({q["grupo_id"] for q in est_p["partidos"].values()}, {"17686"})
        self.assertEqual(len(est_p["partidos"]), 22)
        self.assertEqual(est_i.get("partidos"), {})    # Infantil 1º año: aún no publicado
        self.assertEqual(mi, [])
        self.assertFalse({q["uid"] for q in est_c["partidos"].values()} & {q["uid"] for q in est_p["partidos"].values()})
        self.assertTrue(all("Infantil Preferente Masc." in m["texto"] for m in mp))
        self.assertFalse(any("Preferente" in m["texto"] for m in mc))
        self.assertTrue(all(m["equipo"] == "infantil-masc-pref" for m in mp))
        # Un cambio en un equipo no genera avisos en los otros.
        gs = grupos()
        partido(grupo(gs, "17686"), 1).hora = "12:00"
        self.assertEqual(correr(est_c, gs, MARTES, cfg=CADETE), [])
        m = correr(est_p, gs, MARTES, cfg=PREF)
        self.assertEqual(len(m), 1)
        self.assertIn("🏀 CB Arganda Infantil Preferente Masc.", m[0]["texto"])
        self.assertIn("🕐 Antes: 11:30", m[0]["texto"])

    def test_otro_equipo_del_club_en_preferente_no_se_mezcla(self):
        gs = grupos()
        otro = copy.deepcopy(grupo(gs, "17686"))
        otro.id, otro.competicion = "99001", "Infantil Masc. Pref. - PRIMERA 3ª DIVISION - GRUPO 5"
        for p in otro.partidos:
            p.grupo_id, p.competicion = otro.id, otro.competicion
            p.local = "CB ARGANDA B" if p.local == "CB ARGANDA" else p.local
            p.visitante = "CB ARGANDA B" if p.visitante == "CB ARGANDA" else p.visitante
        gs.append(otro)
        est = {}
        m = correr(est, gs, JUEVES, cfg=PREF)
        self.assertEqual({q["grupo_id"] for q in est["partidos"].values()}, {"17686"})
        self.assertIn("otro equipo del club", " ".join(x["texto"] for x in m if x["clase"] == "AVISO"))


class InfantilPreferenteDeExtremoAExtremo(unittest.TestCase):
    """El tercer equipo con la misma conciliación y los mismos avisos que los otros dos (grupo FBM 17686)."""

    def setUp(self):
        self.est = {}
        self.iniciales = correr(self.est, grupos(), JUEVES, cfg=PREF)
        self.uid_j1 = next(q["uid"] for q in self.est["partidos"].values() if q["jornada"] == 1)

    def cambiar(self, **campos):
        gs = grupos()
        p = partido(grupo(gs, "17686"), 1)
        for k, v in campos.items():
            setattr(p, k, v)
        return gs

    def un_aviso(self, gs, ahora=MARTES, clase="MODIFICADO"):
        m = correr(self.est, gs, ahora, cfg=PREF)
        self.assertEqual([(x["clase"], x["uid"], x["equipo"]) for x in m], [(clase, self.uid_j1, "infantil-masc-pref")])
        self.assertIn("🏀 CB Arganda Infantil Preferente Masc.", m[0]["texto"])
        self.assertIn("🆚 C.B. MORATALAZ \"A\"", m[0]["texto"])
        self.assertEqual(correr(self.est, gs, ahora, cfg=PREF), [])  # misma actualización otra vez: nada
        self.assertEqual(len(self.est["partidos"]), 22)              # nunca duplica
        return m[0]["texto"]

    def test_fuente_equipo_y_partidos(self):
        g = grupo(GRUPOS, "17686")
        self.assertEqual((g.categoria, g.fase, g.grupo), ("Infantil Masc. Pref.", "PRIMERA 1ª DIVISION", "GRUPO 2"))
        self.assertEqual({q["equipo_fbm"] for q in self.est["partidos"].values()}, {"CB ARGANDA"})
        self.assertEqual({q["grupo_id"] for q in self.est["partidos"].values()}, {"17686"})
        self.assertTrue(all("CB ARGANDA" in (q["local"], q["visitante"]) for q in self.est["partidos"].values()))

    def test_nuevo_partido(self):
        nuevos = de_clase(self.iniciales, "NUEVO")
        self.assertEqual(len(nuevos), 22)
        for linea in ("🏀 NUEVO PARTIDO", "Equipo: CB Arganda Infantil Preferente Masc.", "🆚 Rival: C.B. MORATALAZ \"A\"",
                      "📅 Fecha: Sábado 03/10/2026", "🕐 Hora: 11:30", "📍 Pabellón: VIRGEN DEL CARMEN, Pista 3"):
            self.assertIn(linea, nuevos[0]["texto"])

    def test_cambio_de_hora(self):
        t = self.un_aviso(self.cambiar(hora="12:15"))
        self.assertIn("🔄 CAMBIO DE HORA", t)
        self.assertIn("🕐 Antes: 11:30", t)
        self.assertIn("🕐 Ahora: 12:15", t)

    def test_cambio_de_fecha(self):
        t = self.un_aviso(self.cambiar(fecha="2026-10-04"))
        self.assertIn("📅 Antes: Sábado 03/10/2026", t)
        self.assertIn("📅 Ahora: Domingo 04/10/2026", t)

    def test_cambio_de_pabellon(self):
        t = self.un_aviso(self.cambiar(pabellon="VIRGEN DEL CARMEN, PABELLON (PISTA CENTRAL)"))
        self.assertIn("📍 CAMBIO DE PABELLÓN", t)
        self.assertIn("Pista 3", t)
        self.assertIn("PISTA CENTRAL", t)

    def test_aplazamiento(self):
        t = self.un_aviso(self.cambiar(texto_estado="APLAZADO"), clase="APLAZADO")
        self.assertIn("⚠️ PARTIDO APLAZADO", t)
        ics = generar_ics(PREF, self.est, CONFIG["evento"], "https://x", {}, MARTES)
        self.assertIn("⏸️ APLAZADO · CB Arganda vs C.B. MORATALAZ", ics.replace("\r\n ", ""))

    def test_cancelacion(self):
        t = self.un_aviso(self.cambiar(texto_estado="ANULADO"), clase="CANCELADO")
        self.assertIn("❌ PARTIDO CANCELADO", t)
        ics = generar_ics(PREF, self.est, CONFIG["evento"], "https://x", {}, MARTES)
        self.assertNotIn(self.uid_j1, ics)
        self.assertEqual(ics.count("BEGIN:VEVENT"), 21)

    def test_eliminacion_segura(self):
        gs = grupos()
        g = grupo(gs, "17686")
        g.partidos.remove(partido(g, 3))
        uid_j3 = next(q["uid"] for q in self.est["partidos"].values() if q["jornada"] == 3)
        m = correr(self.est, gs, MARTES, cfg=PREF)
        self.assertIn("⚠️ POSIBLE DESAPARICIÓN", m[0]["texto"])
        self.assertEqual(generar_ics(PREF, self.est, CONFIG["evento"], "https://x", {}, MARTES).count("BEGIN:VEVENT"), 22)
        self.assertEqual(correr(self.est, gs, VIERNES, cfg=PREF), [])
        m = correr(self.est, gs, datetime(2026, 10, 6, 17, 5, tzinfo=TZ), cfg=PREF)
        self.assertEqual([(x["clase"], x["uid"]) for x in m], [("ELIMINADO", uid_j3)])
        self.assertNotIn(uid_j3, generar_ics(PREF, self.est, CONFIG["evento"], "https://x", {}, MARTES))

    def test_confirmacion_del_viernes(self):
        m = correr(self.est, grupos(), VIERNES, "viernes", cfg=PREF)
        self.assertEqual([(x["clase"], x["uid"]) for x in m], [("CONFIRMADO", self.uid_j1)])
        self.assertIn("✅ PARTIDO CONFIRMADO", m[0]["texto"])
        self.assertEqual(correr(self.est, grupos(), VIERNES_RESPALDO, "viernes", cfg=PREF), [])

    def test_uid_deterministas_y_distintos_de_los_otros_equipos(self):
        otro = {}
        correr(otro, grupos(), MARTES, cfg=PREF)  # generación independiente desde cero
        self.assertEqual({q["uid"] for q in otro["partidos"].values()}, {q["uid"] for q in self.est["partidos"].values()})
        cadete = {}
        correr(cadete, grupos(), JUEVES, cfg=CADETE)
        self.assertFalse({q["uid"] for q in cadete["partidos"].values()} & {q["uid"] for q in self.est["partidos"].values()})


class ColaYEnvio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ruta = Path(self.tmp.name) / "telegram.json"
        mensajes = [{"id": f"m{i}", "equipo": "cadete-masc-1-ano", "clase": "NUEVO", "uid": None,
                     "texto": f"mensaje {i}"} for i in range(3)]
        cola, _ = telegram.encolar(telegram.cola_vacia(), mensajes, MARTES)
        telegram.guardar_cola(self.ruta, cola)
        self.enviados, self.pausas = [], []

    def tearDown(self):
        self.tmp.cleanup()

    def api_ok(self, token, metodo, datos):
        self.enviados.append(datos["text"])
        return {"ok": True}

    def test_encolar_no_duplica(self):
        cola = telegram.cargar_cola(self.ruta)
        cola, n = telegram.encolar(cola, [{"id": "m1", "equipo": "x", "clase": "NUEVO", "uid": None, "texto": "otra vez"}], MARTES)
        self.assertEqual(n, 0)

    def test_envio_correcto(self):
        r = telegram.enviar_cola(self.ruta, (TOKEN_FALSO, "42"), self.api_ok, self.pausas.append, MARTES)
        self.assertEqual((r["enviados"], r["pendientes"], r["error"]), (3, 0, None))
        self.assertEqual(self.enviados, ["mensaje 0", "mensaje 1", "mensaje 2"])
        self.assertEqual(self.pausas, [telegram.PAUSA_ENTRE_MENSAJES] * 2)
        self.assertEqual(telegram.enviar_cola(self.ruta, (TOKEN_FALSO, "42"), self.api_ok, self.pausas.append)["enviados"], 0)

    def test_telegram_caido_conserva_la_cola_y_no_duplica(self):
        llamadas = []

        def api_cae(token, metodo, datos):
            llamadas.append(datos["text"])
            if len(llamadas) == 2:
                raise telegram.TelegramError("No se pudo conectar con Telegram: timeout")
            return {"ok": True}

        r = telegram.enviar_cola(self.ruta, (TOKEN_FALSO, "42"), api_cae, self.pausas.append, MARTES)
        self.assertEqual((r["enviados"], r["pendientes"]), (1, 2))
        self.assertIn("timeout", telegram.cargar_cola(self.ruta)["ultimo_error"]["detalle"])
        telegram.enviar_cola(self.ruta, (TOKEN_FALSO, "42"), self.api_ok, self.pausas.append, VIERNES)
        self.assertEqual(self.enviados, ["mensaje 1", "mensaje 2"])  # el 0 no se repite
        self.assertIsNone(telegram.cargar_cola(self.ruta)["ultimo_error"])

    def test_limite_429_espera_y_reintenta(self):
        respuestas = [{"ok": False, "error_code": 429, "parameters": {"retry_after": 3}}, {"ok": True}]
        telegram.enviar_mensaje(TOKEN_FALSO, "42", "hola", lambda *a: respuestas.pop(0), self.pausas.append)
        self.assertEqual(self.pausas, [4])

    def test_sin_token_la_cola_se_conserva_y_se_registra(self):
        r = telegram.enviar_cola(self.ruta, None, self.api_ok, self.pausas.append, MARTES)
        self.assertEqual((r["enviados"], r["pendientes"]), (0, 3))
        self.assertIn("no está configurado", telegram.cargar_cola(self.ruta)["ultimo_error"]["detalle"])
        with redirect_stdout(io.StringIO()) as salida:
            self.assertEqual(telegram.main(["enviar", "--cola", str(self.ruta)]), 0)  # nunca rompe el workflow
        self.assertIn("::warning::", salida.getvalue())

    def test_el_token_nunca_aparece(self):
        def api_rechaza(token, metodo, datos):
            raise telegram.TelegramError(telegram._limpiar(f"fallo con {token}", token))

        with unittest.mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN_FALSO, "TELEGRAM_CHAT_ID": "42"}), \
                unittest.mock.patch("fbmcal.telegram.llamar_api", api_rechaza), redirect_stdout(io.StringIO()) as salida:
            self.assertEqual(telegram.main(["enviar", "--cola", str(self.ruta)]), 0)
        self.assertNotIn(TOKEN_FALSO, salida.getvalue())
        self.assertNotIn(TOKEN_FALSO, self.ruta.read_text(encoding="utf-8"))
        self.assertIn("***", salida.getvalue())

    def test_aviso_de_error_del_workflow(self):
        causa = Path(self.tmp.name) / "error.txt"
        causa.write_text("FuenteError: La página de la FBM ha llegado incompleta", encoding="utf-8")
        estado = Path(self.tmp.name) / "estado.json"
        estado.write_text(json.dumps({"ultima_ejecucion": {"en": "2026-09-28T17:05+02:00"}}), encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN_FALSO, "TELEGRAM_CHAT_ID": "42"}), \
                unittest.mock.patch("fbmcal.telegram.llamar_api", self.api_ok), redirect_stdout(io.StringIO()):
            self.assertEqual(telegram.main(["error", "--causa-archivo", str(causa), "--estado", str(estado)]), 0)
        texto = self.enviados[0]
        for linea in ("🚨 ERROR EN LA AUTOMATIZACIÓN", "Causa:\nFuenteError: La página de la FBM ha llegado incompleta",
                      "Última comprobación correcta:\n28/09/2026 17:05", "Los calendarios anteriores se han conservado."):
            self.assertIn(linea, texto)

    def test_prueba_sin_token_falla_de_forma_visible(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(telegram.main(["prueba"]), 1)


class Integracion(unittest.TestCase):
    """main.py completo: los calendarios nunca dependen de Telegram."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "club.html").write_text(HTML, encoding="utf-8")
        (self.dir / "prox.xlsx").write_bytes(XLSX)

    def tearDown(self):
        self.tmp.cleanup()

    def correr(self, ahora):
        with redirect_stdout(io.StringIO()):
            return main(["--html", str(self.dir / "club.html"), "--xlsx", str(self.dir / "prox.xlsx"),
                         "--estado", str(self.dir / "estado.json"), "--salida", str(self.dir / "docs"),
                         "--ahora", ahora])

    def eventos(self, cfg):
        return (self.dir / "docs" / cfg["archivo_ics"]).read_bytes().decode("utf-8").count("BEGIN:VEVENT")

    def test_tres_calendarios_y_sus_avisos(self):
        self.assertEqual(self.correr("2026-09-28T17:05:00+02:00"), 0)
        self.assertEqual([self.eventos(c) for c in (CADETE, INFANTIL, PREF)], [20, 0, 22])
        cola = telegram.cargar_cola(self.dir / "telegram.json")
        por_equipo = {}
        for m in cola["pendientes"]:
            por_equipo.setdefault(m["equipo"], []).append(m["clase"])
        self.assertEqual(por_equipo["cadete-masc-1-ano"].count("NUEVO"), 20)
        self.assertEqual(por_equipo["infantil-masc-pref"].count("NUEVO"), 22)
        self.assertNotIn("infantil-masc-1-ano", por_equipo)
        index = (self.dir / "docs" / "index.html").read_text(encoding="utf-8")
        enlaces = re.findall(r'<h2>([^<]*)</h2>\s*<a class="btn" data-ics="([^"]+)" href="([^"]+)"', index)
        self.assertEqual([(t, d) for t, d, _ in enlaces],
                         [("CB Arganda · Cadete Masc. 1º año", "cadete-masculino-1-ano.ics"),
                          ("CB Arganda · Infantil Masc. 1º año", "infantil-masculino-1-ano.ics"),
                          ("CB Arganda · Infantil Masc. Preferente", "infantil-masculino-preferente.ics")])
        self.assertEqual(len({h for _, _, h in enlaces}), 3)  # tres URLs distintas
        for _, _, href in enlaces:
            self.assertTrue((self.dir / "docs" / href).is_file())
        # Ejecuciones repetidas sin cambios: la cola no crece.
        antes = len(cola["pendientes"])
        self.assertEqual(self.correr("2026-09-29T17:05:00+02:00"), 0)
        self.assertEqual(len(telegram.cargar_cola(self.dir / "telegram.json")["pendientes"]), antes)

    def test_fallo_de_telegram_no_afecta_a_los_calendarios(self):
        with unittest.mock.patch("fbmcal.main.preparar_mensajes", side_effect=RuntimeError("Telegram roto")):
            self.assertEqual(self.correr("2026-09-28T17:05:00+02:00"), 0)
        self.assertEqual([self.eventos(c) for c in (CADETE, INFANTIL, PREF)], [20, 0, 22])
        self.assertFalse((self.dir / "telegram.json").exists())

    def test_ningun_archivo_publicado_contiene_secretos(self):
        with unittest.mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": TOKEN_FALSO, "TELEGRAM_CHAT_ID": "42"}):
            self.correr("2026-09-28T17:05:00+02:00")
        for p in [*(self.dir / "docs").iterdir(), self.dir / "estado.json", self.dir / "telegram.json"]:
            self.assertNotIn("TOKEN-FALSO", p.read_text(encoding="utf-8"), p.name)

    def test_workflow_telegram_despues_de_publicar_y_sin_bloquear(self):
        wf = (Path(__file__).resolve().parent.parent / ".github/workflows/actualizar-calendarios.yml").read_text(encoding="utf-8")
        bloque = wf[wf.index("\n  telegram:"):]
        self.assertIn("needs: [actualizar, publicar]", bloque)
        self.assertIn("continue-on-error: true", bloque)
        self.assertNotIn("needs: [actualizar, publicar, telegram]", wf)
        calendarios = wf[:wf.index("\n  telegram:")]
        paso = calendarios[calendarios.index("Consultar la FBM y actualizar calendarios"):]
        paso = paso[:paso.index("- name:")]
        self.assertNotIn("TELEGRAM_BOT_TOKEN", paso)  # el paso de calendarios no recibe el token


if __name__ == "__main__":
    unittest.main()
