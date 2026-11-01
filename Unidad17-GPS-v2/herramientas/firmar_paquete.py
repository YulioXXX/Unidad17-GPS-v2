# -*- coding: utf-8 -*-
"""Firma de paquetes de actualización (Ed25519). Solo librería estándar.

Ejecútalo en TU equipo de confianza, nunca en el servidor del panel: la clave
privada es lo que impide que alguien con acceso al servidor reparta un
ejecutable propio a todos los agentes.

  1) Una sola vez, generar el par de claves:
       python firmar_paquete.py claves

  2) Por cada versión, después de compilar el .exe:
       python firmar_paquete.py firmar --tipo agente --version 1.0.12 ^
              ..\\cliente\\dist\\Unidad17-Agente.exe
     Crea  Unidad17-Agente.exe.firma  (súbelo al panel junto al .exe).

  3) Comprobar un paquete ya firmado:
       python firmar_paquete.py verificar --tipo agente --version 1.0.12 ^
              Unidad17-Agente.exe
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))
for candidato in (os.path.join(AQUI, "..", "servidor"), AQUI):
    if os.path.exists(os.path.join(candidato, "ed25519.py")):
        sys.path.insert(0, candidato)
        break

import ed25519  # noqa: E402

RUTA_PRIVADA = os.path.join(AQUI, "firma_privada.key")
RUTA_PUBLICA = os.path.join(AQUI, "firma_publica.txt")


def resumen_archivo(ruta: str):
    sha = hashlib.sha256()
    total = 0
    with open(ruta, "rb") as archivo:
        for bloque in iter(lambda: archivo.read(1024 * 1024), b""):
            sha.update(bloque)
            total += len(bloque)
    return sha.hexdigest(), total


def cmd_claves(args) -> int:
    if os.path.exists(args.privada) and not args.forzar:
        print("Ya existe %s. No se sobrescribe (usa --forzar si de verdad quieres otra clave:\n"
              "los agentes ya compilados con la clave anterior dejarían de aceptar tus paquetes)." % args.privada)
        return 1
    semilla = os.urandom(32)
    publica = ed25519.clave_publica(semilla).hex()
    with open(args.privada, "w", encoding="ascii") as archivo:
        archivo.write(semilla.hex() + "\n")
    try:
        os.chmod(args.privada, 0o600)
    except OSError:
        pass
    with open(args.publica, "w", encoding="ascii") as archivo:
        archivo.write(publica + "\n")
    print("Clave PRIVADA : %s" % args.privada)
    print("   Guárdala fuera del servidor y haz una copia de seguridad. Quien la tenga puede")
    print("   publicar actualizaciones para todos tus agentes. NO la subas al panel ni a un repositorio.")
    print("Clave PÚBLICA : %s" % args.publica)
    print("   %s" % publica)
    print("\nSiguientes pasos:")
    print("  - Pega la clave pública en cliente/firma_publica.py (CLAVE_PUBLICA_HEX) y recompila el agente.")
    print("  - Pégala también en el panel: Ajustes > Firma de actualizaciones.")
    return 0


def leer_privada(ruta: str) -> bytes:
    with open(ruta, "r", encoding="ascii") as archivo:
        return bytes.fromhex(archivo.read().strip())


def cmd_firmar(args) -> int:
    if not os.path.isfile(args.archivo):
        print("No existe el archivo: %s" % args.archivo)
        return 1
    if not os.path.isfile(args.clave):
        print("No encuentro la clave privada (%s). Genérala con:  python firmar_paquete.py claves" % args.clave)
        return 1
    sha, tamano = resumen_archivo(args.archivo)
    semilla = leer_privada(args.clave)
    firma = ed25519.firmar(semilla, ed25519.mensaje_actualizacion(args.tipo, args.version, sha, tamano))
    salida = args.salida or (args.archivo + ".firma")
    with open(salida, "w", encoding="ascii") as archivo:
        archivo.write(firma.hex() + "\n")
    print("Archivo   : %s" % args.archivo)
    print("Componente: %s   Versión: %s" % (args.tipo, args.version))
    print("SHA-256   : %s" % sha)
    print("Tamaño    : %d bytes" % tamano)
    print("Firma     : %s" % salida)
    print("Sube el archivo y su .firma en el panel (Actualizaciones > Publicar una versión).")
    return 0


def cmd_verificar(args) -> int:
    sha, tamano = resumen_archivo(args.archivo)
    ruta_firma = args.firma or (args.archivo + ".firma")
    with open(ruta_firma, "r", encoding="ascii") as archivo:
        firma = archivo.read().strip()
    if args.publica_hex:
        publica = args.publica_hex.strip()
    else:
        with open(args.publica, "r", encoding="ascii") as archivo:
            publica = archivo.read().strip()
    if ed25519.firma_valida(publica, firma, args.tipo, args.version, sha, tamano):
        print("Firma VÁLIDA.")
        return 0
    print("Firma NO válida para este archivo, componente y versión.")
    return 2


def main() -> int:
    analizador = argparse.ArgumentParser(description="Firma de paquetes de actualización Unidad 17")
    sub = analizador.add_subparsers(dest="orden", required=True)

    c = sub.add_parser("claves", help="genera el par de claves (una sola vez)")
    c.add_argument("--privada", default=RUTA_PRIVADA)
    c.add_argument("--publica", default=RUTA_PUBLICA)
    c.add_argument("--forzar", action="store_true")
    c.set_defaults(funcion=cmd_claves)

    f = sub.add_parser("firmar", help="firma un .exe o .zip")
    f.add_argument("archivo")
    f.add_argument("--tipo", required=True, choices=("agente", "panel"))
    f.add_argument("--version", required=True, help="por ejemplo 1.0.12")
    f.add_argument("--clave", default=RUTA_PRIVADA)
    f.add_argument("--salida")
    f.set_defaults(funcion=cmd_firmar)

    v = sub.add_parser("verificar", help="comprueba una firma")
    v.add_argument("archivo")
    v.add_argument("--tipo", required=True, choices=("agente", "panel"))
    v.add_argument("--version", required=True)
    v.add_argument("--firma")
    v.add_argument("--publica", default=RUTA_PUBLICA)
    v.add_argument("--publica-hex")
    v.set_defaults(funcion=cmd_verificar)

    args = analizador.parse_args()
    return args.funcion(args)


if __name__ == "__main__":
    sys.exit(main())
