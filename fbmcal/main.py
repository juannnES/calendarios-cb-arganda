"""Punto de entrada: python -m fbmcal [--modo auto|lunes|viernes|manual] ..."""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .avisos import componer_informe, enviar_email
from .conciliar import conciliar_equipo
from .fuente import FuenteError, descargar, leer_calendarios, leer_proximos_html, leer_proximos_xlsx
from .ics import generar_ics
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


def guardar_json(ruta: Path, datos) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ejecutar(args) -> int:
    config = cargar_json(Path(args.config), None)
    ahora = datetime.fromisoformat(args.ahora).astimezone(TZ) if args.ahora else ahora_madrid()
    modo = resolver_modo(args.modo, ahora)
    ruta_estado = Path(args.estado)
    estado = cargar_json(ruta_estado, {"version": 1, "equipos": {}, "ejecuciones": {}})
    print(f"▶ {DIAS[ahora.weekday()]} {ahora:%d/%m/%Y %H:%M} (Europe/Madrid) · modo: {modo}")

    if args.programado:
        # El workflow tiene una ejecución principal (17:05) y otra de respaldo (18:45) por si GitHub
        # retrasa o se salta la primera. Si la principal ya terminó bien, la de respaldo no hace nada.
        if modo not in ("lunes", "viernes") or ahora.hour < 17:
            print("Fuera de la ventana programada (lunes/viernes desde las 17:00). No se hace nada.")
            return 0
        if f"{ahora.date()}-{modo}" in estado["ejecuciones"]:
            print("La comprobación de hoy ya se hizo correctamente. No se repite.")
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

    salida = Path(args.salida)
    salida.mkdir(parents=True, exist_ok=True)
    pabellones = {k: v for k, v in cargar_json(RAIZ / "pabellones.json", {}).items() if not k.startswith("_")}
    for cfg in config["equipos"]:
        ics = generar_ics(cfg, estado["equipos"][cfg["id"]], config["evento"], fuente_url, pabellones, ahora)
        (salida / cfg["archivo_ics"]).write_bytes(ics.encode("utf-8"))
    (salida / "index.html").write_text(generar_indice(config, estado, ahora), encoding="utf-8")
    (salida / ".nojekyll").write_text("", encoding="utf-8")
    guardar_json(ruta_estado, estado)

    informe = componer_informe(cambios, avisos, config, modo, ahora, os.environ.get("PAGES_URL"))
    if informe and not args.sin_email:
        enviar_email(*informe)
    elif informe:
        print(f"(sin email) {informe[0]}\n{informe[1]}")
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
    ap.add_argument("--sin-email", action="store_true")
    ap.add_argument("--probar-email", action="store_true", help="solo envía un email de prueba")
    args = ap.parse_args(argv)
    if args.probar_email:
        ok = enviar_email("🏀 Calendarios CB Arganda: email de prueba",
                          "Si lees esto, los avisos por email están bien configurados.")
        return 0 if ok else 1
    try:
        return ejecutar(args)
    except Exception as e:  # noqa: BLE001 - cualquier fallo se notifica por email y marca el workflow en rojo
        traceback.print_exc()
        if not args.sin_email:
            try:
                enviar_email("❌ Calendarios CB Arganda: error en la actualización",
                             "La actualización automática ha fallado y NO se ha modificado ningún calendario.\n\n"
                             f"Error: {e}\n\n{traceback.format_exc()}\n"
                             "Se reintentará en la siguiente ejecución programada. Revisa la pestaña Actions del repositorio.")
            except Exception:  # noqa: BLE001
                traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
