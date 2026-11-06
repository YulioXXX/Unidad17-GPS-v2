# -*- coding: utf-8 -*-
"""Prueba la conexión y las consultas del panel contra TU base Postgres/Supabase.

Ejecútalo desde tu PC ANTES de desplegar en Render. Crea un esquema temporal
(u17_prueba), recorre las operaciones principales y lo borra al terminar:
no toca el esquema real ni otras tablas de tu proyecto.

    pip install flask "psycopg[binary]"
    python herramientas/probar_postgres.py "postgresql://usuario:CLAVE@host:5432/postgres"

(También acepta la variable de entorno DATABASE_URL.)
Si la clave tiene símbolos (@ : / # ?) hay que escribirlos codificados (%40, %3A...).
"""
from __future__ import annotations

import os
import sys
import tempfile
import traceback

AQUI = os.path.dirname(os.path.abspath(__file__))
SERVIDOR = os.path.join(AQUI, "..", "servidor")

url = (sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DATABASE_URL", "")).strip()
if not url.startswith(("postgres://", "postgresql://")):
    print(__doc__)
    sys.exit(2)

ESQUEMA = "u17_prueba"
os.environ["DATABASE_URL"] = url
os.environ["UNIDAD17_PG_SCHEMA"] = ESQUEMA
os.environ["UNIDAD17_DATOS"] = tempfile.mkdtemp(prefix="u17_prueba_")  # config.json temporal
sys.path.insert(0, SERVIDOR)

try:
    import psycopg  # noqa: F401
except ImportError:
    print('Falta el driver:  pip install "psycopg[binary]"')
    sys.exit(2)

import base_datos as bd  # noqa: E402

fallos = []


def paso(nombre, funcion):
    try:
        resultado = funcion()
        print("  OK     %s" % nombre)
        return resultado
    except Exception as exc:  # noqa: BLE001
        fallos.append(nombre)
        print("  FALLÓ  %s -> %s: %s" % (nombre, type(exc).__name__, exc))
        if os.environ.get("VERBOSE"):
            traceback.print_exc()
        return None


def comprobar(nombre, condicion, detalle=None):
    if condicion:
        print("  OK     %s" % nombre)
    else:
        fallos.append(nombre)
        print("  FALLÓ  %s%s" % (nombre, ("  (obtenido: %r)" % (detalle,)) if detalle is not None else ""))


def borrar_esquema_temporal():
    import psycopg as _p
    with _p.connect(url, connect_timeout=10, sslmode=os.environ.get("UNIDAD17_PG_SSLMODE", "require"),
                    prepare_threshold=None) as con:
        con.execute('DROP SCHEMA IF EXISTS "%s" CASCADE' % ESQUEMA)


print("Probando contra Postgres (esquema temporal %s)..." % ESQUEMA)
try:
    # Si una prueba anterior se cortó (VPN, red...) pudo dejar datos: se parte de cero.
    try:
        borrar_esquema_temporal()
    except Exception as exc:  # noqa: BLE001
        print("  (no se pudo limpiar un esquema anterior: %s)" % exc)

    paso("conexión y creación del esquema", bd.inicializar)
    if fallos:
        raise SystemExit(1)

    comprobar("usuario admin creado con cambio obligatorio", bd.debe_cambiar_clave("admin"))
    comprobar("contraseña inicial verificable", bd.verificar_usuario("admin", "unidad17"))

    reporte = {
        "hostname": "PC-PRUEBA-ÑÁ", "ip_local": "192.168.0.10", "ip_publica": "1.2.3.4",
        "mac": "AA:BB:CC:DD:EE:FF", "so": "Windows 11", "procesador": "Intel", "arquitectura": "AMD64",
        "ram_gb": 15.8, "disco_libre_gb": 120.5, "latitud": 10.0678, "longitud": -69.3467,
        "ciudad": "Barquisimeto", "pais": "Venezuela", "precision_m": 25, "fuente": "gps",
        "version_agente": "1.0.11",
    }
    resultado = paso("guardar reporte nuevo (RETURNING id)", lambda: bd.guardar_reporte(reporte))
    comprobar("el equipo se marca como nuevo", bool(resultado) and resultado[1] is True, resultado)
    equipo_id = resultado[0] if resultado else 1
    resultado2 = paso("guardar reporte repetido", lambda: bd.guardar_reporte(dict(reporte, ram_gb=16)))
    comprobar("el segundo reporte no es nuevo", bool(resultado2) and resultado2[1] is False)

    fila = paso("obtener equipo", lambda: bd.obtener_equipo(equipo_id))
    comprobar("campos por nombre y tildes correctas",
              bool(fila) and fila["hostname"] == "PC-PRUEBA-ÑÁ" and fila["total_reportes"] == 2,
              (fila["hostname"], fila["total_reportes"]) if fila else None)
    paso("listar equipos", bd.listar_equipos)
    paso("resumen del panel", lambda: bd.resumen()["total"] == 1 or (_ for _ in ()).throw(AssertionError("total != 1")))
    paso("actividad 7 días", bd.actividad_7_dias)
    paso("distribución por fuente", bd.distribucion_fuente)
    paso("historial del equipo", lambda: bd.historial_equipo(equipo_id))
    paso("exportar CSV", bd.exportar_csv)

    token = paso("enrolar equipo nuevo", lambda: bd.enrolar_equipo("PC-TOKEN"))
    comprobar("token entregado", bool(token) and bool(token[0]))
    comprobar("token reconocido", bool(token) and bd.equipo_por_token(token[0]) is not None)
    paso("revocar token", lambda: bd.revocar_token(bd.equipo_por_token(token[0])["id"]))
    comprobar("token revocado deja de valer", bool(token) and bd.equipo_por_token(token[0]) is None)
    paso("estado y conteo de tokens", lambda: (bd.estado_token_por_hostname("PC-TOKEN"), bd.contar_sin_token()))

    paso("guardar y leer configuración", lambda: (bd.guardar_config("prueba", "valor"),
         bd.obtener_config("prueba") == "valor" or (_ for _ in ()).throw(AssertionError("no coincide"))))
    paso("registrar evento", lambda: bd.registrar_evento("prueba", "detalle", "127.0.0.1"))
    paso("cambiar contraseña", lambda: bd.cambiar_clave("admin", "OtraClaveSegura9"))
    comprobar("ya no exige cambiar la contraseña", not bd.debe_cambiar_clave("admin"))

    binario = bytes(range(256)) * 100
    ruta = os.path.join(os.environ["UNIDAD17_DATOS"], "paquete.bin")
    with open(ruta, "wb") as archivo:
        archivo.write(binario)
    paso("guardar paquete binario (bytea)", lambda: bd.guardar_paquete_blob("Unidad17-Agente-9.9.9.exe", ruta))
    comprobar("el paquete vuelve idéntico", bd.leer_paquete_blob("Unidad17-Agente-9.9.9.exe") == binario)
    paso("conservar paquetes", lambda: bd.conservar_paquetes([]))
    comprobar("paquete sin referencia eliminado", bd.leer_paquete_blob("Unidad17-Agente-9.9.9.exe") is None)

    paso("depurar historial", lambda: bd.depurar_historial(0))
    paso("depurar eventos", lambda: bd.depurar_eventos(0))
finally:
    try:
        borrar_esquema_temporal()
        print("Esquema temporal eliminado.")
    except Exception as exc:  # noqa: BLE001
        print("AVISO: no se pudo borrar el esquema temporal %s: %s" % (ESQUEMA, exc))

print()
if fallos:
    print("RESULTADO: %d prueba(s) fallaron: %s" % (len(fallos), ", ".join(fallos)))
    print("Pásame el mensaje completo (sin la contraseña) y lo corrijo.")
    sys.exit(1)
print("RESULTADO: TODO OK. Ya puedes desplegar en Render con esta base de datos.")
