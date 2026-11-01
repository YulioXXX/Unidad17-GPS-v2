# -*- coding: utf-8 -*-
"""Mantenimiento de la base de datos: recorta el historial antiguo.

    python mantenimiento.py --dias 90
    python mantenimiento.py --dias 30 --compactar     (solo SQLite)

Funciona con SQLite y con Postgres (si está definida DATABASE_URL).
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys

import base_datos as bd
from configuracion import ES_POSTGRES, PG_ESQUEMA, RUTA_DB


def main() -> int:
    analizador = argparse.ArgumentParser(description="Mantenimiento de la base de datos de Unidad 17")
    analizador.add_argument("--dias", type=int, default=90,
                            help="conservar solo el historial de los últimos N días (0 = borrar todo)")
    analizador.add_argument("--compactar", action="store_true",
                            help="ejecutar VACUUM para reducir el tamaño del archivo (solo SQLite)")
    argumentos = analizador.parse_args()

    if argumentos.dias < 0:
        print("El número de días no puede ser negativo.")
        return 2

    if ES_POSTGRES:
        borrados = bd.depurar_historial(argumentos.dias)
        print("Base de datos : PostgreSQL (esquema %s)" % PG_ESQUEMA)
        print("Puntos borrados: %d (historial anterior a %d días)" % (borrados, argumentos.dias))
        return 0

    if not os.path.exists(RUTA_DB):
        print("No existe la base de datos: %s" % RUTA_DB)
        return 1

    anterior = os.path.getsize(RUTA_DB)
    borrados = bd.depurar_historial(argumentos.dias)
    if argumentos.compactar:
        conexion = sqlite3.connect(RUTA_DB, timeout=20)
        try:
            conexion.execute("VACUUM")
        finally:
            conexion.close()

    actual = os.path.getsize(RUTA_DB)
    print("Base de datos : %s" % RUTA_DB)
    print("Puntos borrados: %d" % borrados)
    print("Tamaño        : %.1f MB -> %.1f MB" % (anterior / 1048576, actual / 1048576))
    return 0


if __name__ == "__main__":
    sys.exit(main())
