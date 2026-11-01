# -*- coding: utf-8 -*-
"""Configuración del panel Unidad 17.

La configuración vive en ``config.json`` junto a ``app.py`` (o junto al .exe
cuando está compilado). La primera vez se crea automáticamente con una clave
de agente aleatoria.
"""
from __future__ import annotations

import json
import os
import secrets
import sys

VERSION = "1.0.11"


def _carpeta_programa() -> str:
    """Carpeta de recursos (código o carpeta temporal del .exe)."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


#: Carpeta donde se guardan config.json, la base de datos y los registros.
#: En contenedores o servidores se puede fijar con la variable UNIDAD17_DATOS.
DIR_DATOS = (
    os.environ.get("UNIDAD17_DATOS")
    or (os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else _carpeta_programa())
)

#: Si hay DATABASE_URL (Postgres, por ejemplo Supabase) el panel usa esa base en
#: lugar del archivo SQLite. Así funciona en servicios con disco efímero (Render).
DATABASE_URL = (os.environ.get("DATABASE_URL") or os.environ.get("UNIDAD17_DATABASE_URL") or "").strip()
ES_POSTGRES = DATABASE_URL.startswith(("postgres://", "postgresql://"))
#: Esquema propio dentro de Postgres (no se mezcla con otras tablas ni queda en
#: el esquema "public", que Supabase expone por su API REST).
PG_ESQUEMA = os.environ.get("UNIDAD17_PG_SCHEMA", "unidad17").strip() or "unidad17"

RUTA_CONFIG = os.path.join(DIR_DATOS, "config.json")
RUTA_DB = os.environ.get("UNIDAD17_DB") or os.path.join(DIR_DATOS, "datos", "unidad17.db")

DEFECTOS = {
    "host": "0.0.0.0",
    "puerto": 5000,
    "abrir_navegador": True,
    "usuario_admin": "admin",
    "clave_admin": "unidad17",
    "clave_api": "",
    "clave_secreta": "",
    "minutos_offline": 15,
    "titulo_panel": "Unidad 17",
    "subtitulo_panel": "Control de equipos y ubicación",
    "url_publica": "",
    # Poner en true cuando el panel se sirva por HTTPS (la cookie de sesión
    # solo viajará cifrada).
    "cookie_segura": False,
    # Depuración automática del historial (días). Por defecto solo con Postgres,
    # para no llenar el plan gratis; 0 la desactiva.
    "depuracion_automatica": ES_POSTGRES,
    "historial_dias": 90,
}


def _nueva_clave_api() -> str:
    return "U17-" + secrets.token_urlsafe(18)


def cargar() -> dict:
    cfg = dict(DEFECTOS)
    if os.path.exists(RUTA_CONFIG):
        try:
            with open(RUTA_CONFIG, "r", encoding="utf-8-sig") as fh:
                guardado = json.load(fh)
            if isinstance(guardado, dict):
                cfg.update(guardado)
        except (OSError, ValueError) as exc:
            print(f"[config] No se pudo leer {RUTA_CONFIG}: {exc}")

    cambiado = False
    if not cfg.get("clave_api"):
        cfg["clave_api"] = _nueva_clave_api()
        cambiado = True
    if not cfg.get("clave_secreta"):
        cfg["clave_secreta"] = secrets.token_hex(32)
        cambiado = True

    if not os.path.exists(RUTA_CONFIG) or cambiado:
        guardar(cfg)

    # Ajustes por variable de entorno (despliegue en contenedor). No se guardan
    # en config.json: mandan solo mientras la variable exista.
    # Secretos por variable de entorno: en servicios sin disco permanente
    # config.json se pierde en cada reinicio, y con él las claves.
    for variable, campo in (("UNIDAD17_CLAVE_API", "clave_api"),
                            ("UNIDAD17_CLAVE_SECRETA", "clave_secreta"),
                            ("UNIDAD17_CLAVE_ADMIN", "clave_admin")):
        if os.environ.get(variable):
            cfg[campo] = os.environ[variable].strip()
    if os.environ.get("UNIDAD17_URL_PUBLICA"):
        cfg["url_publica"] = os.environ["UNIDAD17_URL_PUBLICA"].strip()
    if os.environ.get("UNIDAD17_COOKIE_SEGURA"):
        cfg["cookie_segura"] = os.environ["UNIDAD17_COOKIE_SEGURA"].strip().lower() in ("1", "true", "si", "sí")
    return cfg


def guardar(cfg: dict) -> None:
    try:
        os.makedirs(DIR_DATOS, exist_ok=True)
        temporal = RUTA_CONFIG + ".tmp"
        with open(temporal, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, indent=2, ensure_ascii=False)
        os.replace(temporal, RUTA_CONFIG)
    except OSError as exc:
        print(f"[config] No se pudo guardar la configuración: {exc}")


CFG = cargar()
