# -*- coding: utf-8 -*-
"""Punto de entrada para producción (Gunicorn / Waitress).

    gunicorn --workers 2 --threads 4 --bind 127.0.0.1:5000 wsgi:application
    waitress-serve --listen=127.0.0.1:5000 wsgi:application
"""
import logging
import os

import actualizaciones as act
import base_datos as bd
from app import app as application

try:
    bd.inicializar()
except Exception:  # noqa: BLE001
    # Si la base de datos no responde (p. ej. un proyecto de Supabase pausado) el
    # panel arranca igualmente y crea el esquema en la primera conexión válida.
    logging.getLogger("unidad17").exception("No se pudo inicializar la base de datos al arrancar")
act.asegurar()

# Detrás de un proxy inverso (Caddy, Nginx): sin esto el panel vería siempre la
# IP del proxy, y el límite de intentos y el registro de eventos serían inútiles.
# Activar SOLO si el proxy es de confianza y el puerto del panel no es público.
if os.environ.get("UNIDAD17_PROXY") == "1":
    from werkzeug.middleware.proxy_fix import ProxyFix

    application.wsgi_app = ProxyFix(application.wsgi_app, x_for=1, x_proto=1, x_host=1)
