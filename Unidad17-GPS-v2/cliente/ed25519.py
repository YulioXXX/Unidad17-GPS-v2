# -*- coding: utf-8 -*-
"""Firmas Ed25519 (RFC 8032) en Python puro, sin dependencias.

Se usa para firmar y verificar los paquetes de actualización. Este mismo
archivo vive en ``servidor/``, ``cliente/`` y se reutiliza desde
``herramientas/firmar_paquete.py``: mantén las tres copias idénticas.

Solo es una implementación de referencia: sirve para firmar y verificar
mensajes pequeños (aquí, un texto de ~150 bytes), no para uso general.
"""
from __future__ import annotations

import hashlib

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_RAIZ_M1 = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _sha512(datos: bytes) -> bytes:
    return hashlib.sha512(datos).digest()


def _sha512_modq(datos: bytes) -> int:
    return int.from_bytes(_sha512(datos), "little") % _Q


def _sumar(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _multiplicar(s: int, punto):
    resultado = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            resultado = _sumar(resultado, punto)
        punto = _sumar(punto, punto)
        s >>= 1
    return resultado


def _iguales(a, b) -> bool:
    if (a[0] * b[2] - b[0] * a[2]) % _P != 0:
        return False
    return (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _recuperar_x(y: int, signo: int):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if signo else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _RAIZ_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != signo:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recuperar_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _comprimir(punto) -> bytes:
    zinv = _inv(punto[2])
    x = punto[0] * zinv % _P
    y = punto[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _descomprimir(datos: bytes):
    if len(datos) != 32:
        return None
    y = int.from_bytes(datos, "little")
    signo = y >> 255
    y &= (1 << 255) - 1
    x = _recuperar_x(y, signo)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expandir(semilla: bytes):
    if len(semilla) != 32:
        raise ValueError("La clave privada debe tener 32 bytes.")
    h = _sha512(semilla)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def clave_publica(semilla: bytes) -> bytes:
    a, _ = _expandir(semilla)
    return _comprimir(_multiplicar(a, _G))


def firmar(semilla: bytes, mensaje: bytes) -> bytes:
    a, prefijo = _expandir(semilla)
    publica = _comprimir(_multiplicar(a, _G))
    r = _sha512_modq(prefijo + mensaje)
    Rs = _comprimir(_multiplicar(r, _G))
    h = _sha512_modq(Rs + publica + mensaje)
    s = (r + h * a) % _Q
    return Rs + int.to_bytes(s, 32, "little")


def verificar(publica: bytes, mensaje: bytes, firma: bytes) -> bool:
    """True solo si ``firma`` es una firma válida de ``mensaje``."""
    if len(publica) != 32 or len(firma) != 64:
        return False
    A = _descomprimir(publica)
    if A is None:
        return False
    Rs = firma[:32]
    R = _descomprimir(Rs)
    if R is None:
        return False
    s = int.from_bytes(firma[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_modq(Rs + publica + mensaje)
    return _iguales(_multiplicar(s, _G), _sumar(R, _multiplicar(h, A)))


# --------------------------------------------------------------------------
# Formato del mensaje que se firma en cada actualización
# --------------------------------------------------------------------------
def mensaje_actualizacion(tipo: str, version: str, sha256: str, tamano) -> bytes:
    """Texto que se firma. Incluye componente, versión, hash y tamaño: así una
    firma no sirve para otro componente, otra versión ni otro archivo."""
    return ("U17-UPDATE\n%s\n%s\n%s\n%d" % (
        str(tipo).strip(), str(version).strip(), str(sha256).strip().lower(), int(tamano)
    )).encode("utf-8")


def firma_valida(clave_publica_hex: str, firma_hex: str, tipo: str, version: str,
                 sha256: str, tamano) -> bool:
    """Atajo que acepta todo en hexadecimal y nunca lanza excepciones."""
    try:
        publica = bytes.fromhex(str(clave_publica_hex).strip())
        firma = bytes.fromhex(str(firma_hex).strip())
        mensaje = mensaje_actualizacion(tipo, version, sha256, tamano)
        return verificar(publica, mensaje, firma)
    except (ValueError, TypeError):
        return False
