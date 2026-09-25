"""Cola y envío de avisos por Telegram (Telegram Bot API, gratuita). Capa SECUNDARIA de notificaciones.

    python -m fbmcal.telegram enviar            envía la cola data/telegram.json
    python -m fbmcal.telegram error --causa X   envía un aviso de error inmediato
    python -m fbmcal.telegram prueba            envía un mensaje de prueba

* Solo usa la biblioteca estándar de Python: funciona aunque falle la instalación de dependencias.
* El token (TELEGRAM_BOT_TOKEN) y el chat (TELEGRAM_CHAT_ID) se leen SOLO de variables de entorno
  (GitHub Secrets). Nunca se escriben en archivos ni se imprimen.
* Si Telegram falla o no está configurado, los avisos siguen en la cola y se reintentan en la
  siguiente ejecución; el comando termina sin error para no afectar nunca a los calendarios.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from .util import TZ, ahora_madrid

RAIZ = Path(__file__).resolve().parent.parent
COLA = RAIZ / "data" / "telegram.json"
ESTADO = RAIZ / "data" / "estado.json"
API = "https://api.telegram.org"
PAUSA_ENTRE_MENSAJES = 1.1   # Telegram recomienda no pasar de ~1 mensaje por segundo en un mismo chat
MAX_ENVIADOS = 5000          # ids recordados para no repetir avisos
MAX_LONGITUD = 4000          # límite de Telegram: 4096 caracteres
REPETIR_AVISO_SISTEMA = timedelta(days=3)


class TelegramError(Exception):
    pass


def cola_vacia() -> dict:
    return {"pendientes": [], "enviados": [], "avisos_sistema": {}, "ultimo_envio": None, "ultimo_error": None}


def cargar_cola(ruta: Path) -> dict:
    try:
        return {**cola_vacia(), **json.loads(ruta.read_text(encoding="utf-8"))}
    except FileNotFoundError:
        return cola_vacia()


def guardar_cola(ruta: Path, cola: dict) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_text(json.dumps(cola, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, ruta)


def encolar(cola: dict, mensajes: list[dict], ahora: datetime) -> tuple[dict, int]:
    """Añade mensajes nuevos a la cola sin duplicar. Devuelve (cola, nº añadidos)."""
    ya = {m["id"] for m in cola["pendientes"]} | set(cola["enviados"])
    añadidos = 0
    for m in mensajes:
        if m["id"] in ya:
            continue
        if m["id"].startswith("sistema|"):
            ultimo = cola["avisos_sistema"].get(m["id"])
            if ultimo and ahora - datetime.fromisoformat(ultimo) < REPETIR_AVISO_SISTEMA:
                continue
            cola["avisos_sistema"][m["id"]] = ahora.isoformat(timespec="minutes")
        cola["pendientes"].append({**m, "creado": ahora.isoformat(timespec="minutes")})
        ya.add(m["id"])
        añadidos += 1
    # Los avisos del sistema se recuerdan 30 días como máximo.
    limite = ahora - timedelta(days=30)
    cola["avisos_sistema"] = {k: v for k, v in cola["avisos_sistema"].items() if datetime.fromisoformat(v) >= limite}
    return cola, añadidos


def texto_error(causa: str, ultima_ok: str | None, ambito: str = "los calendarios") -> str:
    ultima = datetime.fromisoformat(ultima_ok).astimezone(TZ).strftime("%d/%m/%Y %H:%M") if ultima_ok else "sin datos"
    return "\n".join([
        "🚨 ERROR EN LA AUTOMATIZACIÓN", "",
        f"No se ha podido actualizar correctamente {ambito}.", "",
        "Causa:", causa.strip()[:1500], "",
        "Última comprobación correcta:", ultima, "",
        "Los calendarios anteriores se han conservado.",
    ])


# ---------------------------------------------------------------- API de Telegram

def credenciales() -> tuple[str, str] | None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    return (token, chat) if token and chat else None


def _limpiar(texto: str, token: str) -> str:
    """Nunca mostrar el token, ni aunque aparezca dentro de un mensaje de error."""
    return texto.replace(token, "***") if token else texto


def llamar_api(token: str, metodo: str, datos: dict, timeout: int = 20) -> dict:
    req = urllib.request.Request(f"{API}/bot{token}/{metodo}", data=json.dumps(datos).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            cuerpo = json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            cuerpo = {"ok": False, "description": f"HTTP {e.code}"}
        return {**cuerpo, "ok": False, "error_code": e.code}
    except Exception as e:  # noqa: BLE001 - red caída, DNS, timeout…
        raise TelegramError(_limpiar(f"No se pudo conectar con Telegram: {type(e).__name__}: {e}", token)) from None


def enviar_mensaje(token: str, chat: str, texto: str, api=None, dormir=None) -> None:
    api, dormir = api or llamar_api, dormir or time.sleep  # se resuelven al llamar (permite sustituirlas en pruebas)
    datos = {"chat_id": chat, "text": texto[:MAX_LONGITUD], "disable_web_page_preview": True}
    for _ in range(3):
        r = api(token, "sendMessage", datos)
        if r.get("ok"):
            return
        espera = (r.get("parameters") or {}).get("retry_after")
        if r.get("error_code") == 429 and espera:
            dormir(min(int(espera), 60) + 1)  # Telegram pide esperar: se respeta y se reintenta
            continue
        raise TelegramError(_limpiar(f"Telegram rechazó el mensaje ({r.get('error_code')}): {r.get('description')}", token))
    raise TelegramError("Telegram sigue limitando el envío (429). Se reintentará en la próxima ejecución.")


def enviar_cola(ruta: Path, cred: tuple[str, str] | None, api=None, dormir=None,
                ahora: datetime | None = None) -> dict:
    """Envía los pendientes en orden. Lo enviado sale de la cola; lo demás se queda para la próxima vez."""
    ahora = ahora or ahora_madrid()
    dormir = dormir or time.sleep
    cola = cargar_cola(ruta)
    resultado = {"enviados": 0, "pendientes": len(cola["pendientes"]), "error": None}
    if not cola["pendientes"]:
        return resultado
    if cred is None:
        resultado["error"] = ("Telegram no está configurado (faltan los secrets TELEGRAM_BOT_TOKEN y/o "
                              "TELEGRAM_CHAT_ID). Los avisos quedan en cola.")
    else:
        token, chat = cred
        try:
            while cola["pendientes"]:
                m = cola["pendientes"][0]
                enviar_mensaje(token, chat, m["texto"], api, dormir)
                cola["pendientes"].pop(0)
                cola["enviados"] = (cola["enviados"] + [m["id"]])[-MAX_ENVIADOS:]
                cola["ultimo_envio"] = ahora.isoformat(timespec="minutes")
                resultado["enviados"] += 1
                if cola["pendientes"]:
                    dormir(PAUSA_ENTRE_MENSAJES)
        except TelegramError as e:
            resultado["error"] = str(e)
    cola["ultimo_error"] = ({"en": ahora.isoformat(timespec="minutes"), "detalle": resultado["error"]}
                            if resultado["error"] else None)
    resultado["pendientes"] = len(cola["pendientes"])
    guardar_cola(ruta, cola)
    return resultado


# ---------------------------------------------------------------- línea de comandos (workflow)

def _anotar_en_actions(texto: str, aviso: bool) -> None:
    print(f"::warning::{texto}" if aviso else texto)
    resumen = os.environ.get("GITHUB_STEP_SUMMARY")
    if resumen:
        with open(resumen, "a", encoding="utf-8") as f:
            f.write(f"### 📱 Telegram\n{'⚠️ ' if aviso else ''}{texto}\n\n")


def _ultima_ok(ruta_estado: Path) -> str | None:
    try:
        return json.loads(ruta_estado.read_text(encoding="utf-8")).get("ultima_ejecucion", {}).get("en")
    except (FileNotFoundError, ValueError):
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Avisos de Telegram de los calendarios CB Arganda.")
    sub = ap.add_subparsers(dest="orden", required=True)
    p_env = sub.add_parser("enviar")
    p_env.add_argument("--cola", default=str(COLA))
    p_err = sub.add_parser("error")
    p_err.add_argument("--causa", default="")
    p_err.add_argument("--causa-archivo", default=os.environ.get("ERROR_ARCHIVO", ""))
    p_err.add_argument("--estado", default=str(ESTADO))
    sub.add_parser("prueba")
    args = ap.parse_args(argv)
    cred = credenciales()

    if args.orden == "enviar":
        r = enviar_cola(Path(args.cola), cred)
        if r["error"]:
            _anotar_en_actions(f"Avisos NO enviados: {r['error']} Enviados: {r['enviados']} · "
                               f"en cola: {r['pendientes']}. Los calendarios no se ven afectados.", aviso=True)
        else:
            _anotar_en_actions(f"✅ Avisos enviados: {r['enviados']} · en cola: {r['pendientes']}.", aviso=False)
        return 0  # Telegram nunca marca como fallida la actualización de los calendarios

    if args.orden == "error":
        causa = args.causa
        if args.causa_archivo and Path(args.causa_archivo).is_file():
            causa = Path(args.causa_archivo).read_text(encoding="utf-8").strip() or causa
        texto = texto_error(causa or "Ha fallado un paso del workflow (ver GitHub Actions).", _ultima_ok(Path(args.estado)))
        if cred is None:
            _anotar_en_actions("No se pudo avisar del error por Telegram: faltan los secrets.", aviso=True)
            return 0
        try:
            enviar_mensaje(*cred, texto)
            _anotar_en_actions("🚨 Aviso de error enviado por Telegram.", aviso=False)
        except TelegramError as e:
            _anotar_en_actions(f"No se pudo avisar del error por Telegram: {e}", aviso=True)
        return 0

    # prueba: aquí sí se devuelve error, para que la prueba manual muestre claramente si falla.
    if cred is None:
        _anotar_en_actions("Faltan los secrets TELEGRAM_BOT_TOKEN y/o TELEGRAM_CHAT_ID.", aviso=True)
        return 1
    try:
        enviar_mensaje(*cred, "🏀 Prueba de avisos de los calendarios CB Arganda\n\n"
                              "✅ Si lees esto, el bot de Telegram está bien configurado.")
    except TelegramError as e:
        _anotar_en_actions(f"La prueba de Telegram ha fallado: {e}", aviso=True)
        return 1
    _anotar_en_actions("✅ Mensaje de prueba enviado por Telegram.", aviso=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
