# -*- coding: utf-8 -*-
"""Actualización silenciosa del agente.

Consulta ``/api/version`` en el panel, comprueba la FIRMA Ed25519 del paquete
publicado con la clave pública del agente, descarga el paquete, comprueba su
SHA-256 y programa el reemplazo del .exe en ejecución mediante un .bat.

Sin una clave pública de firma el agente no se actualiza solo (a menos que
``permitir_sin_firma`` esté activado en config.json).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

import ed25519
import firma_publica
from hardware import VERSION_AGENTE

UA = "Unidad17-Agente/1.0"
MAX_TAMANO = 300 * 1024 * 1024


def _tupla(texto) -> tuple:
    try:
        partes = [int(p) for p in str(texto).split(".")]
    except (TypeError, ValueError):
        return (0, 0, 0)
    while len(partes) < 3:
        partes.append(0)
    return tuple(partes[:3])


def consultar(url_base: str, timeout: float = 10.0) -> dict:
    peticion = urllib.request.Request(
        url_base.rstrip("/") + "/api/version",
        headers={"User-Agent": UA, "Accept": "application/json"},
    )
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return json.loads(respuesta.read().decode("utf-8", "replace"))


def clave_publica_efectiva(clave_config: str = "") -> str:
    """La clave incrustada en el .exe manda; si está vacía, la de config.json."""
    embebida = str(firma_publica.CLAVE_PUBLICA_HEX or "").strip().lower()
    return embebida or str(clave_config or "").strip().lower()


def verificar_firma(info: dict, clave_hex: str, tipo: str = "agente") -> None:
    """Lanza ValueError si la firma del manifiesto no es válida."""
    firma = str(info.get("firma") or "").strip()
    if not firma:
        raise ValueError("el paquete publicado no está firmado")
    if not ed25519.firma_valida(clave_hex, firma, tipo, info.get("version", ""),
                                info.get("sha256", ""), info.get("tamano") or 0):
        raise ValueError("la firma del paquete no es válida")


def descargar_verificar(info: dict, destino: str, timeout: float = 120.0) -> str:
    """Descarga el .exe y comprueba tamaño y SHA-256."""
    url = str(info.get("url") or "")
    esperado = str(info.get("sha256") or "").lower()
    if not url.startswith(("http://", "https://")) or not esperado:
        raise ValueError("El manifiesto no trae una URL o un SHA-256 válidos.")

    peticion = urllib.request.Request(url, headers={"User-Agent": UA})
    resumen = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta, open(destino, "wb") as archivo:
        while True:
            bloque = respuesta.read(65536)
            if not bloque:
                break
            total += len(bloque)
            if total > MAX_TAMANO:
                raise ValueError("El paquete supera el tamaño máximo.")
            resumen.update(bloque)
            archivo.write(bloque)

    if total == 0:
        raise ValueError("El paquete descargado está vacío.")
    if resumen.hexdigest().lower() != esperado:
        raise ValueError("El SHA-256 no coincide con el publicado.")
    tamano = info.get("tamano")
    if tamano not in (None, "") and int(tamano) != total:
        raise ValueError("El tamaño descargado no coincide con el publicado.")
    return destino


def _escribir_bat(nuevo: str, actual: str) -> str:
    bat = os.path.join(os.path.dirname(actual), "_actualizar_agente.bat")
    contenido = (
        "@echo off\n"
        "setlocal\n"
        "timeout /t 2 /nobreak >nul\n"
        "powershell -NoProfile -WindowStyle Hidden -Command "
        '"$i=0; while ((Get-Process -Id {pid} -ErrorAction SilentlyContinue) '
        '-and $i -lt 60) {{ Start-Sleep -Milliseconds 500; $i++ }}"\n'
        'copy /Y "{actual}" "{actual}.bak" >nul 2>&1\n'
        'copy /Y "{nuevo}" "{actual}" >nul 2>&1\n'
        'if errorlevel 1 copy /Y "{actual}.bak" "{actual}" >nul 2>&1\n'
        'start "" "{actual}"\n'
        'del "{nuevo}" >nul 2>&1\n'
        'del "%~f0"\n'
    ).format(pid=os.getpid(), actual=actual, nuevo=nuevo)

    try:
        with open(bat, "w", encoding="mbcs") as archivo:
            archivo.write(contenido)
    except (LookupError, UnicodeError):
        with open(bat, "w", encoding="utf-8") as archivo:
            archivo.write(contenido)
    return bat


def _lanzar_fuera_del_job(bat: str) -> bool:
    """Lanza el .bat con WMI para que sobreviva a la salida del agente."""
    corto = bat
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(bat, buffer, 32768):
            corto = buffer.value or bat
    except (AttributeError, OSError):
        pass

    comando = ('cmd.exe /c ""%s""' if " " in corto else 'cmd.exe /c "%s"') % corto
    try:
        proceso = subprocess.run(
            ["wmic", "process", "call", "create", comando],
            capture_output=True, text=True, timeout=25,
            creationflags=0x08000000,
        )
        salida = (proceso.stdout or "") + (proceso.stderr or "")
        if "ReturnValue = 0" in salida:
            return True
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        banderas = 0x00000008 | 0x00000200
        subprocess.Popen(["cmd", "/c", bat], creationflags=banderas, close_fds=True)
        return True
    except OSError:
        return False


def comprobar(url_base: str, log=print, timeout: float = 10.0,
              clave_config: str = "", permitir_sin_firma: bool = False) -> bool:
    """Devuelve True solo si hay una versión nueva (no aplica si no es .exe)."""
    if not url_base:
        return False

    try:
        manifiesto = consultar(url_base, timeout=timeout)
    except (OSError, ValueError, TimeoutError, urllib.error.URLError):
        return False

    info = manifiesto.get("agente") or {}
    publicada = str(info.get("version") or "")
    if not publicada or _tupla(publicada) <= _tupla(VERSION_AGENTE):
        return False

    if not str(info.get("archivo") or "").lower().endswith(".exe"):
        log("El paquete publicado del agente no es un .exe; se ignora.")
        return False

    if not getattr(sys, "frozen", False):
        log("Hay una version %s del agente disponible; actualiza el .exe manualmente." % publicada)
        return False

    # La firma se comprueba ANTES de descargar nada.
    clave = clave_publica_efectiva(clave_config)
    if clave:
        try:
            verificar_firma(info, clave)
        except ValueError as exc:
            log("Actualizacion %s RECHAZADA: %s." % (publicada, exc))
            return False
    elif not permitir_sin_firma:
        log("Hay una version %s del agente, pero no se instala: este agente no tiene clave "
            "publica de firma (firma_publica.py o clave_publica_firma en config.json)." % publicada)
        return False
    else:
        log("AVISO: se actualiza sin verificar firma (permitir_sin_firma activado).")

    actual = sys.executable
    destino = os.path.join(os.path.dirname(actual), "_actualizacion_agente.exe")

    try:
        descargar_verificar(info, destino)
    except (OSError, ValueError, TimeoutError, urllib.error.URLError) as exc:
        log("No se pudo descargar la actualizacion %s: %s" % (publicada, exc))
        return False

    try:
        bat = _escribir_bat(destino, actual)
        if not _lanzar_fuera_del_job(bat):
            log("No se pudo lanzar el actualizador del agente.")
            return False
    except OSError as exc:
        log("No se pudo programar la actualizacion: %s" % exc)
        return False

    log("Actualizando el agente a la version %s..." % publicada)
    time.sleep(0.8)
    os._exit(0)
    return True
