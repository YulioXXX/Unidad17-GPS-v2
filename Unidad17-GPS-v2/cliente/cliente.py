# -*- coding: utf-8 -*-
"""Agente de ubicación Unidad 17.

Envía periódicamente la ubicación y los datos básicos del equipo al panel.
El agente se ejecuta con una ventana visible: su funcionamiento es trasparente
para la persona que usa el equipo.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

import actualizador
from cola import Cola
from geolocalizacion import escanear_wifi_windows, obtener_ubicacion
from hardware import VERSION_AGENTE, info_equipo

RUTA_BASE = (
    os.path.dirname(sys.executable)
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)
RUTA_CONFIG = os.path.join(RUTA_BASE, "config.json")
RUTA_LOG = os.path.join(RUTA_BASE, "agente.log")
RUTA_AVISO = os.path.join(RUTA_BASE, ".aviso_mostrado")
RUTA_COLA = os.path.join(RUTA_BASE, "datos_agente", "cola.jsonl")
RUTA_TOKEN = os.path.join(RUTA_BASE, ".token_equipo")

DEFECTOS = {
    "url_servidor": "http://127.0.0.1:5000",
    "clave_agente": "",
    "intervalo_segundos": 300,
    "tiempo_limite": 15,
    "avisar_al_iniciar": True,
    "auto_actualizar": True,
    "horas_actualizacion": 6,
    "max_cola": 5000,
    "clave_publica_firma": "",
    "permitir_sin_firma": False,
}

BANNER = """============================================================
  UNIDAD 17 - AGENTE DE UBICACION
  Equipo    : {equipo}
  Servidor  : {servidor}
  Intervalo : {intervalo} segundos
------------------------------------------------------------
  Este equipo reporta su ubicacion y datos basicos al panel.
  Deja esta ventana abierta mientras el agente este activo.
  Detener: Ctrl + C
============================================================"""

_clave_google = None
_clave_google_hora = 0.0

_token = ""                    # token propio de este equipo (lo entrega el panel)
_proximo_enrolamiento = 0.0    # espera entre intentos de enrolamiento
_servidor_antiguo = False      # el panel no tiene /api/registrar
ESPERA_ENROLAMIENTO = 900      # segundos tras un rechazo


# --------------------------------------------------------------------------
# Configuración y registro
# --------------------------------------------------------------------------
def guardar_config(cfg: dict) -> None:
    try:
        with open(RUTA_CONFIG, "w", encoding="utf-8") as archivo:
            json.dump(cfg, archivo, indent=2, ensure_ascii=False)
            archivo.write("\n")
    except OSError as exc:
        print("No se pudo guardar config.json: %s" % exc)


def cargar_config() -> dict:
    if not os.path.exists(RUTA_CONFIG):
        guardar_config(dict(DEFECTOS))
        print("\nSe creo %s" % RUTA_CONFIG)
        print("Editalo antes de continuar:")
        print("  url_servidor -> http://IP_DEL_SERVIDOR:5000")
        print("  clave_agente -> la clave que aparece en Ajustes del panel\n")
        return dict(DEFECTOS)

    try:
        with open(RUTA_CONFIG, "r", encoding="utf-8-sig") as archivo:
            cfg = json.load(archivo)
        if not isinstance(cfg, dict):
            raise ValueError("el contenido no es un objeto JSON")
    except (OSError, ValueError) as exc:
        print("No se pudo leer config.json (%s). Se usan valores por defecto." % exc)
        cfg = dict(DEFECTOS)

    for clave, valor in DEFECTOS.items():
        cfg.setdefault(clave, valor)
    return cfg


def registrar(texto: str) -> None:
    linea = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), texto)
    print(linea, flush=True)
    try:
        if os.path.exists(RUTA_LOG) and os.path.getsize(RUTA_LOG) > 1_000_000:
            os.replace(RUTA_LOG, RUTA_LOG + ".1")
        with open(RUTA_LOG, "a", encoding="utf-8") as archivo:
            archivo.write(linea + "\n")
    except OSError:
        pass


def config_valida(cfg: dict) -> bool:
    clave = (cfg.get("clave_agente") or "").strip()
    url = (cfg.get("url_servidor") or "").strip()

    if not clave or "PEGA" in clave.upper():
        print("\n[!] Falta la clave de agente en %s" % RUTA_CONFIG)
        print("    Copiala desde el panel: Ajustes > Clave de agente.\n")
        return False

    if not url.startswith(("http://", "https://")):
        print("\n[!] La url_servidor debe empezar por http:// o https://\n")
        return False

    return True


def url_base(cfg: dict) -> str:
    return cfg["url_servidor"].strip().rstrip("/")


def url_reporte(cfg: dict) -> str:
    return url_base(cfg) + "/api/report"


# --------------------------------------------------------------------------
# Token propio del equipo
# --------------------------------------------------------------------------
def cargar_token_guardado() -> str:
    try:
        with open(RUTA_TOKEN, "r", encoding="utf-8") as archivo:
            return archivo.read().strip()
    except OSError:
        return ""


def guardar_token(token: str) -> bool:
    try:
        with open(RUTA_TOKEN, "w", encoding="utf-8") as archivo:
            archivo.write(token + "\n")
        try:
            os.chmod(RUTA_TOKEN, 0o600)
        except OSError:
            pass
        return True
    except OSError as exc:
        registrar("No se pudo guardar el token en %s: %s" % (RUTA_TOKEN, exc))
        return False


def cabeceras_auth(cfg: dict) -> dict:
    """Con token solo se envía el token; la clave compartida queda en reposo."""
    if _token:
        return {"X-Token-Equipo": _token}
    return {"X-Clave-Agente": str(cfg["clave_agente"]).strip()}


def intentar_enrolar(cfg: dict) -> bool:
    """Pide un token propio al panel presentando la clave de agente una vez.

    Devuelve True si se obtuvo un token nuevo. Respeta una espera entre
    intentos para no insistir cuando el panel lo rechaza."""
    global _token, _proximo_enrolamiento, _servidor_antiguo
    if _servidor_antiguo or time.time() < _proximo_enrolamiento:
        return False

    cuerpo = json.dumps({"hostname": socket.gethostname()}).encode("utf-8")
    peticion = urllib.request.Request(
        url_base(cfg) + "/api/registrar",
        data=cuerpo,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-Clave-Agente": str(cfg["clave_agente"]).strip(),
            "User-Agent": "Unidad17-Agente/%s" % VERSION_AGENTE,
        },
    )
    try:
        with urllib.request.urlopen(peticion, timeout=float(cfg["tiempo_limite"])) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", "replace"))
        nuevo = str(datos.get("token") or "").strip()
        if not nuevo:
            raise ValueError("respuesta sin token")
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            _servidor_antiguo = True
            registrar("El panel no admite tokens por equipo (version anterior); se usa la clave de agente.")
        else:
            detalle = exc.read().decode("utf-8", "replace")[:160]
            registrar("Enrolamiento rechazado (HTTP %s): %s" % (exc.code, detalle))
            _proximo_enrolamiento = time.time() + ESPERA_ENROLAMIENTO
        return False
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        registrar("No se pudo enrolar el equipo todavia: %s" % exc)
        return False

    _token = nuevo
    guardar_token(nuevo)
    registrar("Equipo enrolado: desde ahora reporta con un token propio.")
    return True


def asegurar_token(cfg: dict) -> None:
    global _token
    if _token:
        return
    guardado = cargar_token_guardado()
    if guardado:
        _token = guardado
        return
    intentar_enrolar(cfg)


# --------------------------------------------------------------------------
# Clave de Google (la entrega el panel a los agentes autenticados)
# --------------------------------------------------------------------------
def obtener_clave_google(cfg: dict, forzar: bool = False) -> str:
    global _clave_google, _clave_google_hora

    ahora = time.time()
    if not forzar and _clave_google is not None and (ahora - _clave_google_hora) < 600:
        return _clave_google

    peticion = urllib.request.Request(
        url_base(cfg) + "/api/config",
        headers=dict(cabeceras_auth(cfg), **{
            "User-Agent": "Unidad17-Agente/%s" % VERSION_AGENTE,
            "Accept": "application/json",
        }),
    )
    try:
        with urllib.request.urlopen(peticion, timeout=float(cfg["tiempo_limite"])) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", "replace"))
        nueva = str(datos.get("google_api_key") or "").strip()
        if nueva != (_clave_google or ""):
            registrar("Clave de Google actualizada desde el panel." if nueva
                      else "El panel no tiene clave de Google configurada.")
        _clave_google = nueva
        _clave_google_hora = ahora
    except (OSError, ValueError, TimeoutError, urllib.error.URLError):
        if _clave_google is None:
            _clave_google = ""
            _clave_google_hora = ahora

    return _clave_google or ""


# --------------------------------------------------------------------------
# Aviso inicial al usuario del equipo
# --------------------------------------------------------------------------
def aviso_inicial(cfg: dict) -> None:
    if not cfg.get("avisar_al_iniciar", True) or os.path.exists(RUTA_AVISO):
        return
    if sys.platform == "win32":
        mensaje = (
            "Este equipo reporta su ubicacion y datos basicos al panel de control "
            "de Unidad 17.\n\n"
            "La ventana del agente permanece visible mientras esta en ejecucion.\n\n"
            "Si no reconoces esta instalacion, cierra esta ventana y avisa a tu "
            "administrador."
        )
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None, mensaje, "Unidad 17 - Aviso de ubicacion", 0x00000040
            )
        except (AttributeError, OSError):
            pass
    try:
        with open(RUTA_AVISO, "w", encoding="utf-8") as archivo:
            archivo.write(datetime.now().isoformat())
    except OSError:
        pass


# --------------------------------------------------------------------------
# Envío y cola
# --------------------------------------------------------------------------
def resumen_ubicacion(datos: dict) -> str:
    if datos.get("latitud") is None or datos.get("longitud") is None:
        return "sin coordenadas"
    lugar = " | ".join(x for x in (datos.get("ciudad"), datos.get("pais")) if x)
    origen = (datos.get("fuente") or "?").upper()
    texto = "%s %.5f, %.5f" % (origen, datos["latitud"], datos["longitud"])
    return texto + (" | " + lugar if lugar else "")


def publicar(cfg: dict, datos: dict):
    """Envía un reporte. Devuelve (ok, mensaje, motivo) con motivo en
    ``ok``, ``red``, ``clave`` o ``datos``."""
    cuerpo = json.dumps(datos, ensure_ascii=False).encode("utf-8")
    peticion = urllib.request.Request(
        url_reporte(cfg),
        data=cuerpo,
        method="POST",
        headers=dict(cabeceras_auth(cfg), **{
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "Unidad17-Agente/%s" % VERSION_AGENTE,
        }),
    )

    try:
        with urllib.request.urlopen(peticion, timeout=float(cfg["tiempo_limite"])) as respuesta:
            texto = respuesta.read().decode("utf-8", "replace")
            respuesta_json = json.loads(texto) if texto.strip() else {}
        equipo_id = respuesta_json.get("equipo_id", "?")
        return True, "reporte aceptado (equipo #%s)" % equipo_id, "ok"
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:200]
        if exc.code in (401, 403):
            if _token:
                return False, ("el panel rechazo el token de este equipo (HTTP %s): puede estar "
                               "revocado o no ser reconocido. %s" % (exc.code, detalle)), "clave"
            return False, "clave de agente rechazada (HTTP %s). Revisa config.json. %s" % (exc.code, detalle), "clave"
        if exc.code == 400:
            return False, "el servidor rechazo los datos (400): %s" % detalle, "datos"
        return False, "el servidor respondio HTTP %s" % exc.code, "red"
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        return False, "no se pudo conectar con %s (%s)" % (url_reporte(cfg), exc), "red"


def recolectar(cfg: dict) -> dict:
    clave_google = obtener_clave_google(cfg)
    datos = dict(info_equipo())
    datos.update(obtener_ubicacion(api_key_google=clave_google))
    return datos


def enviar_reporte(cfg: dict, cola: Cola):
    asegurar_token(cfg)
    datos = recolectar(cfg)
    correcto, mensaje, motivo = publicar(cfg, datos)
    if not correcto and motivo == "clave" and _token and intentar_enrolar(cfg):
        # El token estaba revocado o el panel lo olvidó y el administrador
        # permitió un re-enrolamiento: se reintenta con el token nuevo.
        correcto, mensaje, motivo = publicar(cfg, datos)
    if not correcto and motivo == "red":
        if cola.agregar(datos):
            mensaje += " | guardado en cola (%d pendientes)" % cola.tamano()
    return correcto, mensaje, datos, motivo


def vaciar_cola(cfg: dict, cola: Cola) -> int:
    enviados = 0
    for datos in cola.pendientes(10):
        correcto, mensaje, motivo = publicar(cfg, datos)
        if correcto:
            enviados += 1
            continue
        if motivo == "datos":
            # El reporte viejo no volvera a ser valido: se descarta para no
            # bloquear el resto de la cola.
            enviados += 1
            continue
        break

    if enviados:
        cola.quitar(enviados)
        registrar("Reenviados %d reportes pendientes." % enviados)
    return enviados


# --------------------------------------------------------------------------
# Actualización y ciclo principal
# --------------------------------------------------------------------------
def comprobar_actualizacion(cfg: dict) -> None:
    if not cfg.get("auto_actualizar", True):
        return
    try:
        actualizador.comprobar(
            url_base(cfg), registrar,
            clave_config=str(cfg.get("clave_publica_firma") or ""),
            permitir_sin_firma=bool(cfg.get("permitir_sin_firma")),
        )
    except Exception as exc:  # la actualización nunca debe tumbar el agente
        registrar("Actualizacion: %s" % exc)


def bucle(cfg: dict, cola: Cola) -> None:
    intervalo = max(20, int(cfg.get("intervalo_segundos") or 300))
    horas = max(1.0, float(cfg.get("horas_actualizacion") or 6))
    ultima_comprobacion = time.time()

    while True:
        inicio = time.monotonic()

        if cola.tamano():
            vaciar_cola(cfg, cola)

        try:
            correcto, mensaje, datos, _motivo = enviar_reporte(cfg, cola)
            registrar(("OK   " if correcto else "ERROR") + "  " + mensaje + "  ->  " + resumen_ubicacion(datos))
        except KeyboardInterrupt:
            raise
        except Exception as exc:  # nunca detener el agente por un fallo puntual
            registrar("ERROR  fallo inesperado: %r" % exc)

        if (time.time() - ultima_comprobacion) >= horas * 3600:
            comprobar_actualizacion(cfg)
            ultima_comprobacion = time.time()

        espera = intervalo - (time.monotonic() - inicio)
        espera = max(5.0, espera) * random.uniform(0.95, 1.05)
        time.sleep(espera)


# --------------------------------------------------------------------------
# Diagnóstico y arranque
# --------------------------------------------------------------------------
def diagnostico(cfg: dict) -> None:
    print("=== Diagnostico del agente Unidad 17 ===")
    print("Version       : %s" % VERSION_AGENTE)
    print("Config        : %s" % RUTA_CONFIG)
    print("Clave agente  : %s" % ("configurada" if cfg.get("clave_agente") else "PENDIENTE"))
    print("Servidor      : %s" % cfg.get("url_servidor"))
    print("Token equipo  : %s" % ("presente" if (_token or cargar_token_guardado()) else "no enrolado todavia"))
    clave_firma = actualizador.clave_publica_efectiva(str(cfg.get("clave_publica_firma") or ""))
    print("Firma updates : %s" % (("clave publica %s..." % clave_firma[:12]) if clave_firma
                                  else "SIN clave publica (no se actualiza solo)"))

    print("\nEquipo:")
    for clave, valor in info_equipo().items():
        print("  %-16s %s" % (clave, valor))

    print("\nServidor:")
    try:
        with urllib.request.urlopen(url_base(cfg) + "/salud", timeout=8) as respuesta:
            print("  /salud -> HTTP %s  %s" % (respuesta.status, respuesta.read().decode("utf-8", "replace")[:160]))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        print("  sin respuesta: %s" % exc)

    print("\nGoogle Geolocation:")
    clave_google = obtener_clave_google(cfg, forzar=True)
    print("  clave en el panel: %s" % ("configurada" if clave_google else "no configurada"))
    puntos_wifi = escanear_wifi_windows(verbose=True) or []
    print("  redes Wi-Fi      : %d (Google requiere al menos 2)" % len(puntos_wifi))

    print("\nUbicacion:")
    ubicacion = obtener_ubicacion(verbose=True, api_key_google=clave_google)
    for clave, valor in ubicacion.items():
        print("  %-16s %s" % (clave, valor))

    print("\nCola de reportes: %d pendientes" % Cola(RUTA_COLA, int(cfg.get("max_cola") or 5000)).tamano())


def main() -> int:
    analizador = argparse.ArgumentParser(description="Agente de ubicacion Unidad 17")
    analizador.add_argument("--una-vez", action="store_true", help="envia un solo reporte y termina")
    analizador.add_argument("--diagnostico", action="store_true", help="prueba el equipo, la red y la ubicacion")
    analizador.add_argument("--version", action="version", version="Unidad17 Agente %s" % VERSION_AGENTE)
    argumentos = analizador.parse_args()

    cfg = cargar_config()

    if argumentos.diagnostico:
        diagnostico(cfg)
        return 0

    if not config_valida(cfg):
        return 2

    cola = Cola(RUTA_COLA, int(cfg.get("max_cola") or 5000))
    asegurar_token(cfg)

    if not argumentos.una_vez:
        comprobar_actualizacion(cfg)
        print(BANNER.format(
            equipo=socket.gethostname(),
            servidor=cfg["url_servidor"],
            intervalo=cfg["intervalo_segundos"],
        ))

    aviso_inicial(cfg)

    try:
        if argumentos.una_vez:
            correcto, mensaje, datos, _motivo = enviar_reporte(cfg, cola)
            registrar(("OK   " if correcto else "ERROR") + "  " + mensaje + "  ->  " + resumen_ubicacion(datos))
            return 0 if correcto else 1
        bucle(cfg, cola)
    except KeyboardInterrupt:
        print("\nAgente detenido por el usuario.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
