# -*- coding: utf-8 -*-
"""Obtención de ubicación del equipo.

Orden de intentos:
  1. GPS de Windows mediante el paquete opcional ``winsdk``.
  2. GPS de Windows mediante .NET (PowerShell 5.1), sin instalar nada.
  3. Triangulación Wi-Fi con la Geolocation API de Google (si el panel
     entrega una clave configurada por el administrador).
  4. Geolocalización aproximada por IP.

Todas las funciones devuelven un diccionario con las claves:
``latitud``, ``longitud``, ``ciudad``, ``pais``, ``precision_m``, ``fuente``
e ``ip_publica``.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

TIEMPO = 10
UA = "Unidad17-Agente/1.0 (panel interno)"
GOOGLE_URL = "https://www.googleapis.com/geolocation/v1/geolocate"

SERVICIOS_IP = (
    "https://ipapi.co/json/",
    "https://ipwho.is/",
    "http://ip-api.com/json/?fields=status,lat,lon,city,country,query",
)

BSSID_RE = re.compile(r"BSSID\s+\d+\s*:\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})", re.IGNORECASE)
SENAL_RE = re.compile(r"(?:Signal|Se[ñn]al)\s*:\s*(\d+)\s*%", re.IGNORECASE)


def _log(verbose: bool, mensaje: str) -> None:
    if verbose:
        print("   - " + mensaje, flush=True)


def _json(url: str, tiempo: float = TIEMPO) -> dict:
    peticion = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(peticion, timeout=tiempo) as respuesta:
        texto = respuesta.read().decode("utf-8", "replace")
    datos = json.loads(texto)
    return datos if isinstance(datos, dict) else {}


def _texto(valor, maximo: int = 80) -> str:
    if not valor:
        return ""
    return " ".join(str(valor).split())[:maximo]


def _coordenadas_validas(latitud, longitud) -> bool:
    try:
        return (-90 <= float(latitud) <= 90) and (-180 <= float(longitud) <= 180)
    except (TypeError, ValueError):
        return False


# --------------------------------------------------------------------------
# 1 y 2: GPS de Windows
# --------------------------------------------------------------------------
def ubicacion_gps_windows(verbose: bool = False):
    """Usa Windows.Devices.Geolocation a través de winsdk (opcional)."""
    try:
        from winsdk.windows.devices.geolocation import Geolocator
    except Exception:
        _log(verbose, "winsdk no está instalado; se omite el GPS nativo")
        return None

    import asyncio

    async def leer():
        localizador = Geolocator()
        try:
            from winsdk.windows.devices.geolocation import PositionAccuracy

            localizador.desired_accuracy = getattr(PositionAccuracy, "HIGH", None)
        except Exception:
            pass

        try:
            acceso = await localizador.request_access_async()
            nombre = getattr(acceso, "name", str(acceso)).lower()
            if "allowed" not in nombre:
                raise RuntimeError("permiso de ubicación no concedido")
        except AttributeError:
            pass

        posicion = await asyncio.wait_for(localizador.get_geoposition_async(), timeout=TIEMPO)
        coordenada = posicion.coordinate
        punto = coordenada.point.position
        return {
            "latitud": float(punto.latitude),
            "longitud": float(punto.longitude),
            "precision_m": int(coordenada.accuracy) if coordenada.accuracy else None,
            "fuente": "gps",
        }

    try:
        datos = asyncio.run(leer())
    except Exception as exc:
        _log(verbose, f"GPS nativo sin éxito: {exc}")
        return None

    if _coordenadas_validas(datos.get("latitud"), datos.get("longitud")):
        _log(verbose, "GPS nativo (winsdk) OK")
        return datos
    return None


def ubicacion_windows_powershell(verbose: bool = False):
    """Intenta el GPS mediante System.Device.Location (Windows PowerShell)."""
    if sys.platform != "win32":
        return None

    guion = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Device
$reloj = New-Object System.Device.Location.GeoCoordinateWatcher
$reloj.Start()
$limite = (Get-Date).AddSeconds(9)
while ($reloj.Status -ne 'Ready' -and (Get-Date) -lt $limite) { Start-Sleep -Milliseconds 250 }
$punto = $reloj.Position.Location
if ($punto.IsUnknown) { 'SIN_DATOS' } else { '{0}|{1}|{2}' -f $punto.Latitude, $punto.Longitude, $punto.HorizontalAccuracy }
$reloj.Stop()
"""
    banderas = 0x08000000  # CREATE_NO_WINDOW
    try:
        proceso = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", guion],
            capture_output=True,
            text=True,
            timeout=25,
            creationflags=banderas,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(verbose, f"PowerShell no disponible: {exc}")
        return None

    salida = proceso.stdout or ""
    lineas = [linea.strip() for linea in salida.splitlines() if linea.strip()]
    if not lineas or any(linea.upper().startswith("SIN_DATOS") for linea in lineas):
        _log(verbose, "Windows no tiene ubicación disponible (revisa Privacidad > Ubicación)")
        return None

    ultima = lineas[-1]
    partes = ultima.split("|")
    if len(partes) < 2:
        _log(verbose, f"Respuesta inesperada del GPS: {ultima[:80]}")
        return None

    def numero(texto: str) -> float:
        return float(texto.strip().replace(",", "."))

    try:
        latitud = numero(partes[0])
        longitud = numero(partes[1])
        precision = int(numero(partes[2])) if len(partes) > 2 and partes[2].strip() else None
    except ValueError:
        _log(verbose, f"No se pudieron leer las coordenadas: {ultima[:80]}")
        return None

    if not _coordenadas_validas(latitud, longitud):
        return None

    _log(verbose, "GPS de Windows (PowerShell) OK")
    return {"latitud": latitud, "longitud": longitud, "precision_m": precision, "fuente": "gps"}


# --------------------------------------------------------------------------
# 3: Wi-Fi + Google Geolocation
# --------------------------------------------------------------------------
def _decodificar(datos: bytes) -> str:
    for codificacion in ("utf-8", "cp850", "cp1252", "latin-1"):
        try:
            return datos.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return datos.decode("latin-1", "replace")


def _mac_aleatoria(mac: str) -> bool:
    """Descarta MAC localmente administradas (Google no las usa)."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError):
        return True


def escanear_wifi_windows(verbose: bool = False):
    """Devuelve una lista de puntos de acceso compatible con Google."""
    if sys.platform != "win32":
        return None

    banderas = 0x08000000  # CREATE_NO_WINDOW
    try:
        subprocess.run(["netsh", "wlan", "scan"], capture_output=True,
                       timeout=8, creationflags=banderas)
    except (OSError, subprocess.SubprocessError):
        pass

    try:
        proceso = subprocess.run(
            ["netsh", "wlan", "show", "networks", "mode=bssid"],
            capture_output=True,
            timeout=12,
            creationflags=banderas,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        _log(verbose, f"Wi-Fi: netsh no disponible ({exc})")
        return None

    salida = _decodificar(proceso.stdout or b"")
    if not salida.strip():
        _log(verbose, "Wi-Fi: el adaptador no devolvió redes")
        return None

    senales: dict[str, int | None] = {}
    actual = None
    for linea in salida.splitlines():
        encontrado = BSSID_RE.search(linea)
        if encontrado:
            actual = encontrado.group(1).upper()
            senales.setdefault(actual, None)
            continue
        senal = SENAL_RE.search(linea)
        if senal and actual:
            senales[actual] = int(senal.group(1))

    puntos = []
    for mac, porcentaje in senales.items():
        if porcentaje is None or _mac_aleatoria(mac):
            continue
        dbm = round(porcentaje / 2 - 100)
        dbm = max(-128, min(-10, dbm))
        puntos.append({"macAddress": mac, "signalStrength": int(dbm)})

    if len(puntos) < 2:
        _log(verbose, f"Wi-Fi: {len(puntos)} red(es) utilizables; Google requiere al menos 2")
        return None

    _log(verbose, f"Wi-Fi: {len(puntos)} redes escaneadas")
    return puntos


def ubicacion_google(api_key: str, puntos: list[dict], verbose: bool = False):
    if not api_key or not puntos:
        return None

    cuerpo = json.dumps({"considerIp": False, "wifiAccessPoints": puntos}).encode("utf-8")
    peticion = urllib.request.Request(
        GOOGLE_URL,
        data=cuerpo,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "User-Agent": UA,
        },
    )

    try:
        with urllib.request.urlopen(peticion, timeout=12) as respuesta:
            datos = json.loads(respuesta.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detalle = exc.read().decode("utf-8", "replace")[:180]
        _log(verbose, f"Google Geolocation HTTP {exc.code}: {detalle}")
        return None
    except (OSError, ValueError, TimeoutError, urllib.error.URLError) as exc:
        _log(verbose, f"Google Geolocation: {exc}")
        return None

    posicion = datos.get("location") or {}
    latitud, longitud = posicion.get("lat"), posicion.get("lng")
    if not _coordenadas_validas(latitud, longitud):
        _log(verbose, "Google Geolocation: respuesta sin coordenadas")
        return None

    precision = datos.get("accuracy")
    _log(verbose, "Ubicación Wi-Fi (Google) OK")
    return {
        "latitud": float(latitud),
        "longitud": float(longitud),
        "precision_m": int(precision) if precision else None,
        "fuente": "wifi",
    }


# --------------------------------------------------------------------------
# 4: Respaldo por IP
# --------------------------------------------------------------------------
def _normalizar(datos: dict) -> dict | None:
    latitud, longitud = datos.get("latitud"), datos.get("longitud")
    if not _coordenadas_validas(latitud, longitud):
        return None
    return {
        "latitud": float(latitud),
        "longitud": float(longitud),
        "ciudad": _texto(datos.get("ciudad")),
        "pais": _texto(datos.get("pais")),
        "precision_m": 15000,
        "fuente": "ip",
        "ip_publica": _texto(datos.get("ip_publica"), 45),
    }


def _interpretar(url: str, datos: dict) -> dict | None:
    if "ipapi.co" in url:
        if datos.get("error"):
            return None
        return _normalizar({
            "latitud": datos.get("latitude"),
            "longitud": datos.get("longitude"),
            "ciudad": datos.get("city"),
            "pais": datos.get("country_name"),
            "ip_publica": datos.get("ip"),
        })

    if "ipwho.is" in url:
        if not datos.get("success", True):
            return None
        return _normalizar({
            "latitud": datos.get("latitude"),
            "longitud": datos.get("longitude"),
            "ciudad": datos.get("city"),
            "pais": datos.get("country"),
            "ip_publica": datos.get("ip"),
        })

    if "ip-api.com" in url:
        if datos.get("status") != "success":
            return None
        return _normalizar({
            "latitud": datos.get("lat"),
            "longitud": datos.get("lon"),
            "ciudad": datos.get("city"),
            "pais": datos.get("country"),
            "ip_publica": datos.get("query"),
        })

    return None


def ubicacion_por_ip(verbose: bool = False):
    for url in SERVICIOS_IP:
        try:
            datos = _json(url)
            normalizado = _interpretar(url, datos)
        except (OSError, urllib.error.URLError, ValueError, TimeoutError) as exc:
            _log(verbose, f"{urllib.parse.urlsplit(url).hostname}: {exc}")
            continue

        if normalizado:
            _log(verbose, f"Ubicación por IP OK ({urllib.parse.urlsplit(url).hostname})")
            return normalizado
        _log(verbose, f"{urllib.parse.urlsplit(url).hostname}: sin datos útiles")

    return None


def ip_publica() -> str:
    try:
        datos = _json("https://api.ipify.org?format=json", tiempo=8)
        if datos.get("ip"):
            return _texto(datos["ip"], 45)
    except (OSError, ValueError, TimeoutError):
        pass

    try:
        peticion = urllib.request.Request("https://icanhazip.com", headers={"User-Agent": UA})
        with urllib.request.urlopen(peticion, timeout=8) as respuesta:
            return _texto(respuesta.read().decode("utf-8", "replace"), 45)
    except (OSError, TimeoutError):
        return ""


def _reversa(latitud: float, longitud: float, verbose: bool = False):
    """Convierte coordenadas en ciudad/país con Nominatim (OpenStreetMap)."""
    parametros = urllib.parse.urlencode({
        "format": "jsonv2",
        "lat": latitud,
        "lon": longitud,
        "zoom": 10,
        "accept-language": "es",
    })
    try:
        datos = _json("https://nominatim.openstreetmap.org/reverse?" + parametros, tiempo=9)
    except (OSError, ValueError, TimeoutError) as exc:
        _log(verbose, f"Sin dirección aproximada: {exc}")
        return "", ""

    direccion = datos.get("address") or {}
    ciudad = (direccion.get("city") or direccion.get("town") or direccion.get("village")
              or direccion.get("municipality") or direccion.get("county") or direccion.get("state") or "")
    pais = direccion.get("country") or ""
    return _texto(ciudad), _texto(pais)


# --------------------------------------------------------------------------
# Orquestador
# --------------------------------------------------------------------------
def obtener_ubicacion(verbose: bool = False, api_key_google: str = "") -> dict:
    resultado = {
        "latitud": None,
        "longitud": None,
        "ciudad": "",
        "pais": "",
        "precision_m": None,
        "fuente": "",
        "ip_publica": "",
    }

    gps = ubicacion_gps_windows(verbose)
    if gps is None:
        gps = ubicacion_windows_powershell(verbose)

    if gps:
        resultado.update(gps)
        ciudad, pais = _reversa(gps["latitud"], gps["longitud"], verbose)
        resultado["ciudad"], resultado["pais"] = ciudad, pais
    else:
        wifi = None
        if api_key_google:
            puntos = escanear_wifi_windows(verbose)
            if puntos:
                wifi = ubicacion_google(api_key_google, puntos, verbose)
        else:
            _log(verbose, "Sin clave de Google; se omite la triangulación Wi-Fi")

        if wifi:
            resultado.update(wifi)
            ciudad, pais = _reversa(wifi["latitud"], wifi["longitud"], verbose)
            resultado["ciudad"], resultado["pais"] = ciudad, pais
        else:
            por_ip = ubicacion_por_ip(verbose)
            if por_ip:
                resultado.update(por_ip)
            else:
                _log(verbose, "No se pudo obtener ubicación por ninguna vía")

    resultado["ip_publica"] = ip_publica() or resultado.get("ip_publica", "")
    return resultado
