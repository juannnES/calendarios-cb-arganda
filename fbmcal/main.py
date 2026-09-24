"""Punto de entrada: python -m fbmcal [--modo auto|lunes|viernes|manual] ...

No necesita ninguna credencial: solo lee la web pública de la FBM y escribe archivos.
Si algo falla, termina con código 1 (el workflow queda en rojo) y NO modifica ningún archivo.
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .conciliar import conciliar_equipo
from .fuente import FuenteError, descargar, leer_calendarios, leer_proximos_html, leer_proximos_xlsx
from .ics import generar_ics
from .informe import componer_aviso, escribir_aviso, escribir_resumen, estado_publico, resumen_ejecucion
from .util import DIAS, TZ, ahora_madrid, temporada_de
from .web import generar_indice

RAIZ = Path(__file__).resolve().parent.parent


def resolver_modo(modo: str, ahora: datetime) -> str:
    if modo != "auto":
        return modo
    return {0: "lunes", 4: "viernes"}.get(ahora.weekday(), "manual")


def cargar_json(ruta: Path, defecto):
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return defecto


def a_json(datos) -> bytes:
    return (json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def escribir_todo(archivos: dict[Path, bytes]) -> None:
    """Escribe cada archivo en un .tmp y lo sustituye de golpe (os.replace es atómico).

    Todo el contenido se ha generado ANTES de llamar a esta función, así que un error de la FBM,
    del análisis o de la conciliación nunca deja un calendario a medias ni vacío."""
    temporales = []
    try:
        for ruta, datos in archivos.items():
            ruta.parent.mkdir(parents=True, exist_ok=True)
            tmp = ruta.with_name(ruta.name + ".tmp")
            tmp.write_bytes(datos)
            temporales.append((tmp, ruta))
        for tmp, ruta in temporales:
            os.replace(tmp, ruta)
    finally:
        for tmp, _ in temporales:
            tmp.unlink(missing_ok=True)


def ejecutar(args) -> int:
    config = cargar_json(Path(args.config), None)
    ahora = datetime.fromisoformat(args.ahora).astimezone(TZ) if args.ahora else ahora_madrid()
    modo = resolver_modo(args.modo, ahora)
    ruta_estado = Path(args.estado)
    estado = cargar_json(ruta_estado, {"version": 1, "equipos": {}, "ejecuciones": {}})
    print(f"▶ {DIAS[ahora.weekday()]} {ahora:%d/%m/%Y %H:%M} (Europe/Madrid) · modo: {modo}")

    if args.programado:
        # La «comprobación de las 17:00» se lanza a las 17:05 (GitHub retrasa más las tareas en punto) y
        # hay otra de respaldo a las 18:45. Si la principal ya terminó bien, la de respaldo no repite nada.
        if modo not in ("lunes", "viernes") or ahora.hour < 17:
            print("Fuera de la ventana programada (lunes/viernes desde las 17:00). No se hace nada.")
            return 0
        if f"{ahora.date()}-{modo}" in estado["ejecuciones"]:
            print("La comprobación de hoy ya se hizo correctamente. No se repite.")
            escribir_resumen(f"ℹ️ La comprobación del {modo} ya se había completado hoy; "
                             "esta ejecución de respaldo no hace nada.\n")
            return 0

    fuente_url = config["fuente"]["club_url"]
    avisos: list[str] = []
    html = (Path(args.html).read_text(encoding="utf-8-sig") if args.html
            else descargar(fuente_url).decode("utf-8", errors="replace"))
    grupos = leer_calendarios(html)
    if not grupos:
        raise FuenteError("La página del club no contiene ningún calendario: probablemente la web de la FBM ha "
                          "cambiado de formato. No se ha modificado nada.")
    contraste = [("tabla «Próximos partidos» de fbm.es", leer_proximos_html(html))]
    try:
        datos_xlsx = Path(args.xlsx).read_bytes() if args.xlsx else descargar(config["fuente"]["xlsx_url"])
        contraste.append(("Excel oficial de próximos partidos", leer_proximos_xlsx(datos_xlsx)))
    except Exception as e:  # noqa: BLE001 - el Excel es solo una fuente de contraste
        avisos.append(f"No se pudo leer el Excel oficial de próximos partidos (se sigue sin él): {e}")

    temporada = temporada_de(ahora.date())
    cambios = {}
    for cfg in config["equipos"]:
        est = estado["equipos"].setdefault(cfg["id"], {})
        cambios[cfg["id"]] = conciliar_equipo(cfg, est, grupos, contraste, ahora, modo, temporada)
        n = len([q for q in est["partidos"].values() if q["estado"] != "cancelado"])
        print(f"  · {cfg['nombre_calendario']}: {n} partidos · {len(cambios[cfg['id']])} cambios")
        for c in cambios[cfg["id"]]:
            if c.tipo != "nuevo":
                print(f"      - {c.tipo}: {c.titulo} {c.detalle}")

    if modo in ("lunes", "viernes"):
        estado["ejecuciones"][f"{ahora.date()}-{modo}"] = ahora.isoformat(timespec="minutes")
        estado["ejecuciones"] = dict(sorted(estado["ejecuciones"].items())[-40:])
    estado["ultima_ejecucion"] = {"en": ahora.isoformat(timespec="minutes"), "modo": modo, "temporada": temporada}

    # 1) Generar TODO en memoria.
    salida = Path(args.salida)
    pabellones = {k: v for k, v in cargar_json(RAIZ / "pabellones.json", {}).items() if not k.startswith("_")}
    archivos: dict[Path, bytes] = {}
    for cfg in config["equipos"]:
        ics = generar_ics(cfg, estado["equipos"][cfg["id"]], config["evento"], fuente_url, pabellones, ahora)
        archivos[salida / cfg["archivo_ics"]] = ics.encode("utf-8")
    publico = estado_publico(cambios, avisos, config, estado, modo, ahora)
    archivos[salida / "estado.json"] = a_json(publico)
    archivos[salida / "index.html"] = generar_indice(config, estado, ahora).encode("utf-8")
    archivos[salida / ".nojekyll"] = b""
    archivos[ruta_estado] = a_json(estado)

    # 2) Escribir de golpe.
    escribir_todo(archivos)

    escribir_resumen(resumen_ejecucion(cambios, avisos, config, estado, modo, ahora))
    aviso = componer_aviso(cambios, avisos, config, modo, ahora, os.environ.get("PAGES_URL"))
    if aviso:
        escribir_aviso(*aviso)
    print("✔ Terminado.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Actualiza los calendarios de CB Arganda desde la FBM.")
    ap.add_argument("--modo", choices=["auto", "lunes", "viernes", "manual"], default="auto")
    ap.add_argument("--programado", action="store_true", help="ejecución del cron (evita repetir la del día)")
    ap.add_argument("--config", default=str(RAIZ / "config.json"))
    ap.add_argument("--estado", default=str(RAIZ / "data" / "estado.json"))
    ap.add_argument("--salida", default=str(RAIZ / "docs"))
    ap.add_argument("--html", help="usar un HTML guardado en vez de descargar (pruebas)")
    ap.add_argument("--xlsx", help="usar un XLSX guardado en vez de descargar (pruebas)")
    ap.add_argument("--ahora", help="simular fecha/hora ISO, p. ej. 2026-09-28T17:00+02:00 (pruebas)")
    ap.add_argument("--probar-aviso", action="store_true", help="solo prepara un aviso de prueba (Issue)")
    args = ap.parse_args(argv)
    if args.probar_aviso:
        escribir_aviso("🏀 Aviso de prueba de los calendarios CB Arganda",
                       "Si te ha llegado esta notificación, los avisos funcionan. Ya puedes cerrar este Issue.")
        return 0
    try:
        return ejecutar(args)
    except Exception as e:  # noqa: BLE001 - cualquier fallo deja el workflow en rojo sin tocar los calendarios
        traceback.print_exc()
        print(f"\n❌ ERROR: {e}\nNo se ha modificado ningún calendario. Se reintentará en la próxima ejecución.")
        escribir_resumen(f"## ❌ Error en la actualización\n\n`{e}`\n\n"
                         "No se ha modificado ningún calendario; siguen publicados los de la última ejecución correcta.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
