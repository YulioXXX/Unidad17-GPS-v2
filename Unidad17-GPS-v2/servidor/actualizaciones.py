# -*- coding: utf-8 -*-
"""Paquetes de actualización del agente y del panel.

Los archivos viven en ``actualizaciones/`` junto a la base de datos y se
describen en ``versiones.json``. Cada entrada incluye el SHA-256, el tamaño y,
opcionalmente, una firma Ed25519 hecha FUERA del servidor con la clave privada
del publicador (``herramientas/firmar_paquete.py``). Los agentes verifican esa
firma con la clave pública, así que un servidor comprometido no puede repartir
un ejecutable propio.

Con Postgres (DATABASE_URL) el disco del servicio puede ser efímero: el
manifiesto y los paquetes se copian también a la base de datos y se restauran
al arrancar. El resto del módulo sigue trabajando con archivos locales.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time

import base_datos as bd
import ed25519
from configuracion import DIR_DATOS, ES_POSTGRES, VERSION

DIR_ACTUALIZACIONES = os.path.join(DIR_DATOS, "actualizaciones")
RUTA_MANIFIESTO = os.path.join(DIR_ACTUALIZACIONES, "versiones.json")

TIPOS = {"agente": "Agente", "panel": "Panel"}
EXTENSIONES = {".exe", ".zip"}
VERSION_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}$")
NOMBRE_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
# Con Postgres cada paquete vive también en la base (500 MB en el plan gratis).
MAX_TAMANO = (80 if ES_POSTGRES else 300) * 1024 * 1024
CLAVE_PUBLICA_RE = re.compile(r"^[0-9a-fA-F]{64}$")
FIRMA_RE = re.compile(r"^[0-9a-fA-F]{128}$")


def ahora_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def version_tupla(texto) -> tuple:
    try:
        partes = [int(p) for p in str(texto).split(".")]
    except (TypeError, ValueError):
        return (0, 0, 0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:3])


def hay_nueva(publicada, actual=VERSION) -> bool:
    return version_tupla(publicada) > version_tupla(actual)


log = logging.getLogger("unidad17")

# Estado de la copia en base de datos (solo Postgres).
_BD = {"restaurado": False, "ultimo_intento": 0.0}
REINTENTO_RESTAURAR = 60  # segundos entre intentos si la base no responde


def _restaurar_desde_bd() -> None:
    """Recupera manifiesto y paquetes desde Postgres tras un reinicio."""
    if _BD["ultimo_intento"] and time.monotonic() - _BD["ultimo_intento"] < REINTENTO_RESTAURAR:
        return
    _BD["ultimo_intento"] = time.monotonic()
    try:
        crudo = bd.obtener_config("versiones_json", "")
        guardado = json.loads(crudo) if crudo else {}
        if isinstance(guardado, dict) and guardado:
            _escribir_manifiesto(guardado)
            for tipo in TIPOS:
                entrada_bd = guardado.get(tipo)
                if not isinstance(entrada_bd, dict) or not entrada_bd.get("archivo"):
                    continue
                nombre = os.path.basename(entrada_bd["archivo"])
                ruta = os.path.join(DIR_ACTUALIZACIONES, nombre)
                if NOMBRE_RE.match(nombre) and not os.path.isfile(ruta):
                    contenido = bd.leer_paquete_blob(nombre)
                    if contenido:
                        with open(ruta, "wb") as archivo:
                            archivo.write(contenido)
        _BD["restaurado"] = True
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo restaurar las actualizaciones desde la base de datos: %s", exc)


def asegurar() -> None:
    os.makedirs(DIR_ACTUALIZACIONES, exist_ok=True)
    if ES_POSTGRES and not _BD["restaurado"]:
        _restaurar_desde_bd()
    if not os.path.exists(RUTA_MANIFIESTO):
        _escribir_manifiesto({"agente": None, "panel": None})


def _escribir_manifiesto(datos: dict) -> None:
    temporal = RUTA_MANIFIESTO + ".tmp"
    with open(temporal, "w", encoding="utf-8") as archivo:
        json.dump(datos, archivo, indent=2, ensure_ascii=False)
        archivo.write("\n")
    os.replace(temporal, RUTA_MANIFIESTO)


def _guardar(datos: dict) -> None:
    _escribir_manifiesto(datos)
    # Si la base no se pudo leer al arrancar, no se pisa con un manifiesto vacío.
    if ES_POSTGRES and _BD["restaurado"]:
        try:
            bd.guardar_config("versiones_json", json.dumps(datos, ensure_ascii=False))
            bd.conservar_paquetes([(datos.get(t) or {}).get("archivo") for t in TIPOS])
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo copiar el manifiesto a la base de datos: %s", exc)


def leer() -> dict:
    asegurar()
    datos = {"agente": None, "panel": None}
    try:
        with open(RUTA_MANIFIESTO, "r", encoding="utf-8-sig") as archivo:
            guardado = json.load(archivo)
        if isinstance(guardado, dict):
            for tipo in datos:
                entrada = guardado.get(tipo)
                if isinstance(entrada, dict):
                    datos[tipo] = entrada
    except (OSError, ValueError):
        pass
    return datos


def entrada(tipo: str):
    return leer().get(tipo)


def sha256(ruta: str) -> str:
    resumen = hashlib.sha256()
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            resumen.update(bloque)
    return resumen.hexdigest()


def normalizar_firma(texto) -> str:
    """Devuelve la firma en hexadecimal minúscula o lanza ValueError."""
    firma = "".join(str(texto or "").split()).lower()
    if not firma:
        return ""
    if not FIRMA_RE.match(firma):
        raise ValueError("El archivo de firma no es válido (se esperan 128 caracteres hexadecimales).")
    return firma


def guardar_paquete(tipo: str, version: str, nombre_original: str, flujo,
                    firma: str = "", clave_publica: str = "") -> dict:
    """Guarda el archivo subido y devuelve la entrada del manifiesto.

    Si hay ``clave_publica`` configurada, la firma es obligatoria y se verifica
    ANTES de reemplazar ningún archivo: un paquete mal firmado no pisa al que
    ya está publicado.
    """
    if tipo not in TIPOS:
        raise ValueError("Tipo de paquete inválido.")
    if not VERSION_RE.match(str(version).strip()):
        raise ValueError("La versión debe tener el formato 1.2.3.")
    extension = os.path.splitext(nombre_original or "")[1].lower()
    if extension not in EXTENSIONES:
        raise ValueError("Solo se aceptan archivos .exe o .zip.")
    if tipo == "agente" and extension != ".exe":
        raise ValueError("El paquete del agente debe ser un .exe.")

    asegurar()
    nombre = "Unidad17-%s-%s%s" % (TIPOS[tipo], version.strip(), extension)
    destino = os.path.join(DIR_ACTUALIZACIONES, nombre)
    temporal = destino + ".parte"

    resumen = hashlib.sha256()
    tamano = 0
    with open(temporal, "wb") as archivo:
        while True:
            bloque = flujo.read(1024 * 1024)
            if not bloque:
                break
            tamano += len(bloque)
            if tamano > MAX_TAMANO:
                archivo.close()
                os.remove(temporal)
                raise ValueError("El archivo supera el tamaño máximo permitido.")
            resumen.update(bloque)
            archivo.write(bloque)

    if tamano == 0:
        os.remove(temporal)
        raise ValueError("El archivo está vacío.")

    try:
        firma = normalizar_firma(firma)
    except ValueError:
        os.remove(temporal)
        raise
    if clave_publica:
        if not firma:
            os.remove(temporal)
            raise ValueError("Hay una clave pública de firma configurada: sube también el archivo .firma del paquete.")
        if not ed25519.firma_valida(clave_publica, firma, tipo, version.strip(),
                                    resumen.hexdigest(), tamano):
            os.remove(temporal)
            raise ValueError("La firma NO corresponde a este archivo, componente y versión. No se publicó.")

    os.replace(temporal, destino)
    if ES_POSTGRES:
        try:
            bd.guardar_paquete_blob(nombre, destino)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("No se pudo guardar el paquete en la base de datos: %s" % exc) from exc
    return {
        "version": version.strip(),
        "archivo": nombre,
        "sha256": resumen.hexdigest(),
        "tamano": tamano,
        "firma": firma,
        "fecha": ahora_iso(),
        "notas": "",
    }


def publicar(tipo: str, version: str, notas: str = "", firma: str = "") -> dict:
    """Marca como publicada la última versión guardada de ese tipo."""
    if tipo not in TIPOS:
        raise ValueError("Tipo de paquete inválido.")
    if not VERSION_RE.match(str(version).strip()):
        raise ValueError("Versión inválida.")

    nombre = "Unidad17-%s-%s" % (TIPOS[tipo], version.strip())
    candidatos = [nombre + ".exe", nombre + ".zip"]
    ruta = next((os.path.join(DIR_ACTUALIZACIONES, c) for c in candidatos
                 if os.path.exists(os.path.join(DIR_ACTUALIZACIONES, c))), None)
    if ruta is None:
        raise ValueError("No existe un paquete para esa versión.")

    datos = leer()
    datos[tipo] = {
        "version": version.strip(),
        "archivo": os.path.basename(ruta),
        "sha256": sha256(ruta),
        "tamano": os.path.getsize(ruta),
        "firma": firma or "",
        "fecha": ahora_iso(),
        "notas": (notas or "").strip()[:300],
    }
    _guardar(datos)
    return datos[tipo]


def eliminar(tipo: str, borrar_archivo: bool = True) -> None:
    if tipo not in TIPOS:
        raise ValueError("Tipo de paquete inválido.")
    datos = leer()
    actual = datos.get(tipo)
    if actual and borrar_archivo:
        ruta = os.path.join(DIR_ACTUALIZACIONES, actual.get("archivo", ""))
        if os.path.isfile(ruta):
            try:
                os.remove(ruta)
            except OSError:
                pass
    datos[tipo] = None
    _guardar(datos)


def ruta_archivo(nombre: str):
    """Devuelve la ruta de un archivo publicado, o None si no es válido."""
    nombre = os.path.basename(nombre or "")
    if not NOMBRE_RE.match(nombre):
        return None
    if not any((entrada(tipo) or {}).get("archivo") == nombre for tipo in TIPOS):
        return None
    ruta = os.path.join(DIR_ACTUALIZACIONES, nombre)
    return ruta if os.path.isfile(ruta) else None


def archivos() -> list[dict]:
    asegurar()
    datos = leer()
    publicados = {(datos[t] or {}).get("archivo"): t for t in TIPOS}
    lista = []
    for nombre in sorted(os.listdir(DIR_ACTUALIZACIONES)):
        ruta = os.path.join(DIR_ACTUALIZACIONES, nombre)
        if not os.path.isfile(ruta) or not NOMBRE_RE.match(nombre):
            continue
        if not nombre.lower().endswith((".exe", ".zip")):
            continue
        lista.append({
            "archivo": nombre,
            "tamano": os.path.getsize(ruta),
            "fecha": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime(os.path.getmtime(ruta))),
            "publicado": publicados.get(nombre),
        })
    lista.sort(key=lambda item: item["fecha"], reverse=True)
    return lista
