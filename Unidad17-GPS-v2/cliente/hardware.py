# -*- coding: utf-8 -*-
"""Datos de hardware y red del equipo. Solo librería estándar."""
from __future__ import annotations

import ctypes
import os
import platform
import shutil
import socket
import uuid

VERSION_AGENTE = "1.0.11"


def ip_local() -> str:
    """IP de la interfaz que se usa para salir a la red."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.8)
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def mac() -> str:
    try:
        numero = uuid.getnode()
        partes = ["{:02X}".format((numero >> (8 * i)) & 0xFF) for i in reversed(range(6))]
        direccion = ":".join(partes)
        if (numero >> 40) & 1:
            direccion += " (aleatoria)"
        return direccion
    except (ValueError, OSError):
        return ""


def procesador() -> str:
    try:
        import winreg

        ruta = r"HARDWARE\DESCRIPTION\System\CentralProcessor\0"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, ruta) as clave:
            valor, _tipo = winreg.QueryValueEx(clave, "ProcessorNameString")
        return " ".join(str(valor).split())[:120]
    except (OSError, ImportError):
        return (platform.processor() or platform.machine() or "")[:120]


def sistema_operativo() -> str:
    partes = [platform.system(), platform.release()]
    if platform.system() == "Windows":
        partes.append("(build %s)" % platform.version())
    return " ".join(p for p in partes if p)[:120]


def _memoria_gb():
    """RAM instalada en GB (solo Windows)."""
    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        estado = MEMORYSTATUSEX()
        estado.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
            return round(estado.ullTotalPhys / (1024 ** 3), 1)
    except (AttributeError, OSError, ValueError):
        pass
    return None


def _disco_libre_gb():
    try:
        unidad = os.environ.get("SystemDrive", "C:") + os.sep
        uso = shutil.disk_usage(unidad)
        return round(uso.free / (1024 ** 3), 1)
    except (OSError, ValueError):
        return None


def info_equipo() -> dict:
    return {
        "hostname": socket.gethostname(),
        "ip_local": ip_local(),
        "mac": mac(),
        "so": sistema_operativo(),
        "procesador": procesador(),
        "arquitectura": platform.machine(),
        "ram_gb": _memoria_gb(),
        "disco_libre_gb": _disco_libre_gb(),
        "version_agente": VERSION_AGENTE,
    }
