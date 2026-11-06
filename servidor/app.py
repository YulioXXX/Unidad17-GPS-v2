# -*- coding: utf-8 -*-
"""Panel de control Unidad 17 (Flask).

Ejecutar:  python app.py
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from functools import wraps
from urllib.parse import quote

from flask import (Flask, Response, abort, flash, jsonify, redirect,
                   render_template, request, send_file, session, url_for)

import actualizaciones as act
import base_datos as bd
import ed25519
from configuracion import CFG, DIR_DATOS, ES_POSTGRES, PG_ESQUEMA, RUTA_DB, VERSION

# --------------------------------------------------------------------------
# Rutas de recursos (compatible con PyInstaller --onefile)
# --------------------------------------------------------------------------
RECURSOS = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

app = Flask(
    __name__,
    template_folder=os.path.join(RECURSOS, "templates"),
    static_folder=os.path.join(RECURSOS, "static"),
)
app.secret_key = CFG["clave_secreta"]
app.json.ensure_ascii = False
app.config.update(
    SESSION_COOKIE_NAME="unidad17_sesion",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(CFG.get("cookie_segura")),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(DIR_DATOS, "servidor.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("unidad17")

# --------------------------------------------------------------------------
# Seguridad
# --------------------------------------------------------------------------
INTENTOS: dict[str, list[float]] = {}
INTENTOS_LOCK = threading.Lock()
MAX_INTENTOS = 6
VENTANA_INTENTOS = 300  # segundos


def login_requerido(funcion):
    @wraps(funcion)
    def envoltura(*args, **kwargs):
        if not session.get("usuario"):
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "error": "no autorizado"}), 401
            return redirect(url_for("login"))
        return funcion(*args, **kwargs)

    return envoltura


def generar_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(24)
    return session["csrf"]


def csrf_valido() -> bool:
    enviado = request.form.get("csrf", "")
    guardado = session.get("csrf", "")
    return bool(enviado) and bool(guardado) and secrets.compare_digest(enviado, guardado)


def clave_agente_valida(clave) -> bool:
    if not isinstance(clave, str):
        return False
    try:
        return secrets.compare_digest(clave, str(CFG["clave_api"]))
    except TypeError:
        return False


MIN_CLAVE = 8
CLAVES_PROHIBIDAS = {"unidad17", "admin", "12345678", "password", "contraseña"}


def clave_nueva_error(nueva: str, repetir: str, actual: str = ""):
    """Devuelve el motivo por el que la nueva contraseña no vale, o None."""
    if len(nueva) < MIN_CLAVE:
        return "La nueva contraseña debe tener al menos %d caracteres." % MIN_CLAVE
    if nueva.lower() in CLAVES_PROHIBIDAS or nueva == str(CFG.get("clave_admin", "")):
        return "Esa contraseña es demasiado previsible. Elige otra."
    if actual and nueva == actual:
        return "La nueva contraseña debe ser distinta de la actual."
    if nueva != repetir:
        return "La nueva contraseña y su repetición no coinciden."
    return None


def limpiar_texto(valor, maximo: int) -> str:
    if valor is None:
        return ""
    limpio = "".join(c for c in str(valor) if c.isprintable())
    return " ".join(limpio.split())[:maximo]


def clave_global_permitida() -> bool:
    return bd.obtener_config("permitir_clave_global", "0") == "1"


def autenticar_agente(cuerpo=None):
    """Identifica al agente que llama a la API.

    Devuelve ``(modo, equipo)`` con modo ``token`` (equipo = fila del equipo),
    ``global`` (clave compartida, solo si el administrador la deja activa) o
    ``None`` si no hay credenciales válidas.
    """
    token = request.headers.get("X-Token-Equipo")
    if token:
        fila = bd.equipo_por_token(token)
        return ("token", fila) if fila is not None else (None, None)
    clave = request.headers.get("X-Clave-Agente") or (cuerpo or {}).get("clave")
    if clave_global_permitida() and clave_agente_valida(clave):
        return "global", None
    return None, None


def rechazo_agente(motivo: str):
    """Respuesta para credenciales inválidas, con límite de intentos por IP."""
    ip = request.remote_addr or "desconocida"
    anotar_intento("api:" + ip)
    if demasiados_intentos("api:" + ip):
        bd.registrar_evento("api_bloqueada", motivo[:120], ip)
        return jsonify({"ok": False, "error": "demasiados intentos"}), 429
    log.warning("API rechazada (%s) desde %s", motivo, ip)
    return jsonify({"ok": False, "error": motivo}), 401


def demasiados_intentos(ip: str) -> bool:
    ahora = time.time()
    with INTENTOS_LOCK:
        marcas = [m for m in INTENTOS.get(ip, []) if ahora - m < VENTANA_INTENTOS]
        INTENTOS[ip] = marcas
        return len(marcas) >= MAX_INTENTOS


def anotar_intento(ip: str) -> None:
    with INTENTOS_LOCK:
        INTENTOS.setdefault(ip, []).append(time.time())


app.jinja_env.globals["csrf_token"] = generar_csrf

app.config["MINUTOS_OFFLINE"] = int(CFG["minutos_offline"])


# --------------------------------------------------------------------------
# Fechas legibles
# --------------------------------------------------------------------------
def humano(segundos: float) -> str:
    if segundos is None or math.isinf(segundos):
        return "—"
    segundos = max(0, int(segundos))
    if segundos < 60:
        return "ahora"
    if segundos < 3600:
        return f"hace {segundos // 60} min"
    if segundos < 86400:
        return f"hace {segundos // 3600} h"
    if segundos < 2592000:
        return f"hace {segundos // 86400} d"
    return f"hace {segundos // 2592000} meses"


def fecha_local(texto: str | None) -> str:
    momento = bd.desde_iso(texto)
    if momento is None:
        return "—"
    return datetime.fromtimestamp(momento.timestamp()).strftime("%d/%m/%Y %H:%M")


def preparar_equipo(fila) -> dict:
    datos = dict(fila)
    segundos = bd.segundos_desde(datos.get("ultima_conexion"))
    datos["segundos"] = segundos
    datos["en_linea"] = segundos <= app.config["MINUTOS_OFFLINE"] * 60
    datos["ultima_texto"] = humano(segundos)
    datos["ultima_exacta"] = fecha_local(datos.get("ultima_conexion"))
    datos["primera_exacta"] = fecha_local(datos.get("primera_conexion"))
    datos["tiene_gps"] = datos.get("fuente") == "gps"
    return datos


def ip_lan() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(0.6)
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"


@app.before_request
def exigir_cambio_de_clave():
    """Mientras la contraseña sea la de fábrica, solo se puede cambiarla o salir."""
    if not session.get("usuario") or not session.get("cambiar_clave"):
        return None
    if request.endpoint in ("cambiar_clave_inicial", "salir", "static"):
        return None
    return redirect(url_for("cambiar_clave_inicial"))


@app.after_request
def cabeceras(respuesta: Response) -> Response:
    respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
    respuesta.headers.setdefault("X-Frame-Options", "DENY")
    respuesta.headers.setdefault("Referrer-Policy", "same-origin")
    return respuesta


@app.context_processor
def contexto_comun() -> dict:
    return {
        "version": VERSION,
        "usuario": session.get("usuario", ""),
        "titulo_panel": CFG.get("titulo_panel", "Unidad 17"),
        "subtitulo_panel": CFG.get("subtitulo_panel", "Control de equipos y ubicación"),
        "minutos_offline": app.config["MINUTOS_OFFLINE"],
    }


# --------------------------------------------------------------------------
# Autenticación
# --------------------------------------------------------------------------
@app.route("/")
def login():
    if session.get("usuario"):
        return redirect(url_for("panel"))
    if session.get("csrf") is None:
        generar_csrf()
    return render_template("login.html", error=None, usuario_intento="")


@app.route("/entrar", methods=["POST"])
def entrar():
    ip = request.remote_addr or "desconocida"
    if demasiados_intentos(ip):
        bd.registrar_evento("login_bloqueado", "demasiados intentos", ip)
        return render_template(
            "login.html",
            error="Demasiados intentos fallidos. Espera unos minutos.",
            usuario_intento=request.form.get("usuario", ""),
        ), 429

    if not csrf_valido():
        abort(400, description="Token de formulario inválido.")

    usuario = request.form.get("usuario", "").strip()
    clave = request.form.get("clave", "")

    if bd.verificar_usuario(usuario, clave):
        session.clear()
        session["usuario"] = usuario
        session.permanent = True
        session["cambiar_clave"] = bd.debe_cambiar_clave(usuario)
        generar_csrf()
        bd.registrar_evento("login_ok", usuario, ip)
        log.info("Acceso correcto de %s desde %s", usuario, ip)
        return redirect(url_for("panel"))

    anotar_intento(ip)
    bd.registrar_evento("login_fallido", usuario[:60], ip)
    log.warning("Acceso fallido para %r desde %s", usuario, ip)
    return render_template(
        "login.html",
        error="Usuario o contraseña incorrectos.",
        usuario_intento=usuario,
    ), 401


@app.route("/cambiar-clave", methods=["GET", "POST"])
@login_requerido
def cambiar_clave_inicial():
    if not session.get("cambiar_clave"):
        return redirect(url_for("panel"))
    error = None
    if request.method == "POST":
        if not csrf_valido():
            abort(400, description="Token de formulario inválido.")
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        repetir = request.form.get("repetir", "")
        if not bd.verificar_usuario(session["usuario"], actual):
            error = "La contraseña actual no es correcta."
        else:
            error = clave_nueva_error(nueva, repetir, actual)
        if error is None:
            bd.cambiar_clave(session["usuario"], nueva)
            bd.registrar_evento("clave_cambiada", session["usuario"] + " (primer acceso)",
                                request.remote_addr or "")
            session["cambiar_clave"] = False
            return redirect(url_for("panel"))
    return render_template("cambiar_clave.html", error=error, min_clave=MIN_CLAVE)


@app.route("/salir", methods=["POST"])
@login_requerido
def salir():
    if csrf_valido():
        bd.registrar_evento("logout", session.get("usuario", ""), request.remote_addr or "")
    session.clear()
    return redirect(url_for("login"))


# --------------------------------------------------------------------------
# Panel
# --------------------------------------------------------------------------
@app.route("/panel")
@login_requerido
def panel():
    equipos = [preparar_equipo(fila) for fila in bd.listar_equipos()]
    stats = bd.resumen()
    actividad = bd.actividad_7_dias()
    dist = bd.distribucion_fuente()

    maximo = max([d["total"] for d in actividad] + [1])
    for dia in actividad:
        dia["alto"] = max(3, round(dia["total"] / maximo * 100))

    total_dist = max(1, sum(dist.values()))
    g, w, i = dist["gps"], dist["wifi"], dist["ip"]
    p1 = round(g / total_dist * 100, 1)
    p2 = round((g + w) / total_dist * 100, 1)
    p3 = round((g + w + i) / total_dist * 100, 1)
    gradiente = (
        f"conic-gradient(#00f2c3 0 {p1}%, #ba54f5 {p1}% {p2}%, "
        f"#1d8cf8 {p2}% {p3}%, #3d3d5c {p3}% 100%)"
        if sum(dist.values()) else "conic-gradient(#3d3d5c 0 100%)"
    )

    return render_template(
        "panel.html",
        activo="panel",
        equipos=equipos,
        stats=stats,
        actividad=actividad,
        dist=dist,
        total_dist=sum(dist.values()),
        gradiente=gradiente,
        pct_gps=round(g / total_dist * 100),
        pct_wifi=round(w / total_dist * 100),
        pct_ip=round(i / total_dist * 100),
        pct_sin=round(dist["sin"] / total_dist * 100),
    )


@app.route("/equipo/<int:equipo_id>")
@login_requerido
def equipo(equipo_id: int):
    fila = bd.obtener_equipo(equipo_id)
    if fila is None:
        abort(404)
    datos = preparar_equipo(fila)
    historial = []
    for punto in bd.historial_equipo(equipo_id):
        registro = dict(punto)
        registro["fecha_texto"] = fecha_local(registro["fecha"])
        historial.append(registro)

    return render_template(
        "equipo.html",
        activo="equipos",
        estado_token=datos.get("estado_token") or "sin",
        equipo=datos,
        historial=historial,
        mapa=[{
            "id": datos["id"],
            "hostname": datos["hostname"],
            "lat": datos["latitud"],
            "lon": datos["longitud"],
            "ciudad": datos["ciudad"],
            "pais": datos["pais"],
            "fuente": datos["fuente"],
            "en_linea": datos["en_linea"],
            "ultima_texto": datos["ultima_texto"],
        }] if datos["latitud"] is not None else [],
    )


@app.route("/equipo/<int:equipo_id>/token", methods=["POST"])
@login_requerido
def equipo_token(equipo_id: int):
    if not csrf_valido():
        abort(400)
    fila = bd.obtener_equipo(equipo_id)
    if fila is None:
        abort(404)
    accion = request.form.get("accion", "")
    ip = request.remote_addr or ""
    if accion == "revocar":
        bd.revocar_token(equipo_id)
        bd.registrar_evento("token_revocado", fila["hostname"], ip)
        flash("Acceso revocado: este equipo ya no puede reportar ni volver a enrolarse "
              "hasta que permitas el re-enrolamiento.", "ok")
    elif accion == "reenrolar":
        bd.permitir_reenrolamiento(equipo_id)
        bd.registrar_evento("token_reenrolar", fila["hostname"], ip)
        flash("Re-enrolamiento permitido: el agente pedirá un token nuevo en su próximo ciclo.", "ok")
    return redirect(url_for("equipo", equipo_id=equipo_id))


@app.route("/mapa")
@login_requerido
def mapa():
    equipos = [preparar_equipo(fila) for fila in bd.listar_equipos()]
    con_ubicacion = [e for e in equipos if e["latitud"] is not None and e["longitud"] is not None]
    mapa_datos = [{
        "id": e["id"],
        "hostname": e["hostname"],
        "lat": e["latitud"],
        "lon": e["longitud"],
        "ciudad": e["ciudad"],
        "pais": e["pais"],
        "fuente": e["fuente"],
        "en_linea": e["en_linea"],
        "ultima_texto": e["ultima_texto"],
    } for e in con_ubicacion]

    return render_template(
        "mapa.html",
        activo="mapa",
        equipos=equipos,
        total=len(equipos),
        con_ubicacion=len(con_ubicacion),
        mapa_datos=mapa_datos,
    )


@app.route("/ajustes", methods=["GET", "POST"])
@login_requerido
def ajustes():
    if request.method == "POST":
        if not csrf_valido():
            abort(400)
        accion = request.form.get("accion", "")

        if accion == "cambiar_clave":
            actual = request.form.get("actual", "")
            nueva = request.form.get("nueva", "")
            repetir = request.form.get("repetir", "")
            if not bd.verificar_usuario(session["usuario"], actual):
                flash("La contraseña actual no es correcta.", "error")
            elif clave_nueva_error(nueva, repetir, actual):
                flash(clave_nueva_error(nueva, repetir, actual), "error")
            else:
                bd.cambiar_clave(session["usuario"], nueva)
                bd.registrar_evento("clave_cambiada", session["usuario"], request.remote_addr or "")
                flash("Contraseña actualizada correctamente.", "ok")

        elif accion == "guardar_google":
            clave_google = request.form.get("google_api_key", "").strip()
            if len(clave_google) < 20:
                flash("La clave de Google no parece válida (empieza por AIza y tiene unos 39 caracteres).", "error")
            else:
                bd.guardar_config("google_api_key", clave_google)
                bd.registrar_evento("google_key_actualizada", session["usuario"], request.remote_addr or "")
                flash("Clave de Google guardada. Los agentes la recibirán en su siguiente ciclo.", "ok")

        elif accion == "clave_global":
            activar = request.form.get("valor") == "1"
            bd.guardar_config("permitir_clave_global", "1" if activar else "0")
            bd.registrar_evento("clave_global_activada" if activar else "clave_global_desactivada",
                                session["usuario"], request.remote_addr or "")
            flash("Los agentes sin token pueden seguir reportando con la clave global."
                  if activar else
                  "La clave global ya no sirve para reportar: solo los agentes con token.", "ok")

        elif accion == "guardar_firma":
            clave_pub = request.form.get("clave_publica_firma", "").strip().lower()
            if not act.CLAVE_PUBLICA_RE.match(clave_pub):
                flash("La clave pública debe tener 64 caracteres hexadecimales.", "error")
            else:
                bd.guardar_config("clave_publica_firma", clave_pub)
                bd.registrar_evento("firma_clave_actualizada", clave_pub[:16], request.remote_addr or "")
                flash("Clave pública de firma guardada. Desde ahora todo paquete debe llevar firma válida.", "ok")

        elif accion == "borrar_firma":
            bd.guardar_config("clave_publica_firma", "")
            bd.registrar_evento("firma_clave_borrada", session["usuario"], request.remote_addr or "")
            flash("Clave pública de firma eliminada. El panel ya no exige firma al publicar.", "ok")

        elif accion == "borrar_google":
            bd.guardar_config("google_api_key", "")
            bd.registrar_evento("google_key_borrada", session["usuario"], request.remote_addr or "")
            flash("Clave de Google eliminada. El agente usará GPS de Windows o IP.", "ok")

        return redirect(url_for("ajustes"))

    url_base = request.host_url.rstrip("/")
    puerto_actual = str(request.environ.get("SERVER_PORT", CFG["puerto"]))
    ejemplo = (
        '{\n'
        '  "url_servidor": "%s",\n'
        '  "clave_agente": "%s",\n'
        '  "intervalo_segundos": 300,\n'
        '  "auto_actualizar": true,\n'
        '  "avisar_al_iniciar": true\n'
        '}' % (url_base, CFG["clave_api"])
    )

    clave_firma = bd.obtener_config("clave_publica_firma", "")
    if clave_firma:
        ejemplo = ejemplo.replace(
            '  "avisar_al_iniciar": true\n}',
            '  "avisar_al_iniciar": true,\n  "clave_publica_firma": "%s"\n}' % clave_firma)

    clave_google = bd.obtener_config("google_api_key", "")
    if len(clave_google) > 14:
        google_vista = clave_google[:7] + "..." + clave_google[-4:]
    elif clave_google:
        google_vista = "••••"
    else:
        google_vista = ""

    return render_template(
        "ajustes.html",
        activo="ajustes",
        clave_api=CFG["clave_api"],
        url_base=url_base,
        ip_lan=ip_lan(),
        puerto=puerto_actual,
        ejemplo=ejemplo,
        ruta_db=("PostgreSQL · esquema %s" % PG_ESQUEMA) if ES_POSTGRES else RUTA_DB,
        minutos_offline=app.config["MINUTOS_OFFLINE"],
        google_configurada=bool(clave_google),
        google_vista=google_vista,
        clave_global=clave_global_permitida(),
        sin_token=bd.contar_sin_token(),
        clave_firma=clave_firma,
    )


@app.route("/exportar.csv")
@login_requerido
def exportar():
    contenido = bd.exportar_csv()
    nombre = "equipos_unidad17_%s.csv" % datetime.now().strftime("%Y%m%d_%H%M")
    return Response(
        contenido,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# --------------------------------------------------------------------------
# API
# --------------------------------------------------------------------------
@app.route("/api/report", methods=["POST"])
def api_report():
    cuerpo = request.get_json(silent=True) or {}
    modo, dueno = autenticar_agente(cuerpo)
    if modo is None:
        return rechazo_agente("credenciales de agente inválidas")

    datos, error = validar_reporte(cuerpo)
    if error:
        return jsonify({"ok": False, "error": error}), 400

    if modo == "global" and bd.estado_token_por_hostname(datos["hostname"]) in ("activo", "revocado"):
        # Un equipo enrolado (o bloqueado) ya no puede reportar con la clave
        # compartida: así nadie puede suplantarlo ni saltarse una revocación.
        return jsonify({"ok": False, "error": "este equipo debe reportar con su token"}), 403

    if modo == "token" and datos["hostname"] != dueno["hostname"]:
        # Un token solo vale para el equipo al que se entregó.
        bd.registrar_evento("token_hostname_distinto", datos["hostname"][:60], request.remote_addr or "")
        return jsonify({"ok": False, "error": "el token no corresponde a este equipo"}), 403

    equipo_id, nuevo = bd.guardar_reporte(datos)
    if nuevo:
        log.info("Equipo nuevo registrado: %s (%s)", datos["hostname"], datos["ip_local"])
        bd.registrar_evento("equipo_nuevo", datos["hostname"], request.remote_addr or "")

    return jsonify({"ok": True, "equipo_id": equipo_id, "nuevo": nuevo})


def validar_reporte(cuerpo: dict):
    if not isinstance(cuerpo, dict):
        return None, "cuerpo JSON inválido"

    def texto(campo: str, maximo: int) -> str:
        return limpiar_texto(cuerpo.get(campo, ""), maximo)

    hostname = texto("hostname", 64)
    if not hostname:
        return None, "hostname obligatorio"

    def numero(campo: str, minimo: float, maximo: float):
        valor = cuerpo.get(campo)
        if valor in (None, "", "None", "Desconocida"):
            return None
        try:
            numero_float = float(valor)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numero_float) or not (minimo <= numero_float <= maximo):
            return None
        return numero_float

    fuente = texto("fuente", 16).lower() or "ip"
    if fuente not in ("gps", "wifi", "ip", "manual"):
        fuente = "ip"

    precision = numero("precision_m", 0, 200000)
    ram = numero("ram_gb", 0, 4096)
    disco = numero("disco_libre_gb", 0, 100000)

    datos = {
        "hostname": hostname,
        "ip_local": texto("ip_local", 45),
        "ip_publica": texto("ip_publica", 45),
        "mac": texto("mac", 32),
        "so": texto("so", 120),
        "procesador": texto("procesador", 120),
        "arquitectura": texto("arquitectura", 32),
        "ram_gb": ram,
        "disco_libre_gb": disco,
        "latitud": numero("latitud", -90, 90),
        "longitud": numero("longitud", -180, 180),
        "ciudad": texto("ciudad", 80),
        "pais": texto("pais", 80),
        "precision_m": int(precision) if precision is not None else None,
        "fuente": fuente,
        "version_agente": texto("version_agente", 20),
    }

    if (datos["latitud"] is None) != (datos["longitud"] is None):
        return None, "latitud y longitud deben enviarse juntas"

    return datos, None


@app.route("/api/equipos")
@login_requerido
def api_equipos():
    equipos = [preparar_equipo(fila) for fila in bd.listar_equipos()]
    return jsonify({
        "ok": True,
        "resumen": bd.resumen(),
        "equipos": [{
            "id": e["id"],
            "hostname": e["hostname"],
            "en_linea": e["en_linea"],
            "ultima_conexion": e["ultima_conexion"],
            "ultima_texto": e["ultima_texto"],
            "fuente": e["fuente"],
        } for e in equipos],
    })


@app.route("/api/registrar", methods=["POST"])
def api_registrar():
    """Enrolamiento: el agente presenta la clave de agente UNA vez y recibe un
    token propio. Después reporta solo con ese token."""
    cuerpo = request.get_json(silent=True) or {}
    if not clave_agente_valida(request.headers.get("X-Clave-Agente")):
        return rechazo_agente("clave de enrolamiento inválida")

    hostname = limpiar_texto(cuerpo.get("hostname"), 64)
    if not hostname:
        return jsonify({"ok": False, "error": "hostname obligatorio"}), 400

    token, motivo = bd.enrolar_equipo(hostname)
    ip = request.remote_addr or ""
    if token is None:
        bd.registrar_evento("enrolamiento_rechazado", "%s (%s)" % (hostname, motivo), ip)
        if motivo == "revocado":
            return jsonify({"ok": False, "error": "acceso revocado por el administrador"}), 403
        return jsonify({"ok": False,
                        "error": "este equipo ya tiene un token; el administrador debe permitir el re-enrolamiento"}), 409

    bd.registrar_evento("equipo_nuevo" if motivo == "nuevo" else "equipo_enrolado", hostname, ip)
    log.info("Equipo enrolado: %s (%s)", hostname, motivo)
    return jsonify({"ok": True, "token": token})


@app.route("/api/config")
def api_config():
    """Clave de Google para los agentes autenticados (no se expone al público)."""
    modo, _dueno = autenticar_agente()
    if modo is None:
        return rechazo_agente("credenciales de agente inválidas")
    return jsonify({
        "ok": True,
        "google_api_key": bd.obtener_config("google_api_key", ""),
    })


@app.route("/api/version")
def api_version():
    """Manifiesto de versiones publicado para los agentes."""
    base = (CFG.get("url_publica") or request.host_url).rstrip("/")

    def publicada(tipo):
        registro = act.entrada(tipo)
        if not registro:
            return None
        return dict(registro, url=base + "/actualizaciones/descargar/" + quote(registro["archivo"]))

    return jsonify({
        "ok": True,
        "servidor": {"version": VERSION, "hora": bd.iso()},
        "agente": publicada("agente"),
        "panel": publicada("panel"),
    })


@app.route("/actualizaciones/descargar/<path:nombre>")
def descargar_actualizacion(nombre: str):
    ruta = act.ruta_archivo(nombre)
    if ruta is None:
        abort(404)
    return send_file(ruta, as_attachment=True, download_name=os.path.basename(ruta))


@app.route("/actualizaciones", methods=["GET", "POST"])
@login_requerido
def actualizaciones():
    if request.method == "POST":
        if not csrf_valido():
            abort(400)
        accion = request.form.get("accion", "")

        try:
            if accion == "subir":
                tipo = request.form.get("tipo", "")
                version = request.form.get("version", "").strip()
                notas = request.form.get("notas", "")
                archivo = request.files.get("archivo")
                if archivo is None or not archivo.filename:
                    raise ValueError("Selecciona el archivo del paquete.")
                firma = ""
                archivo_firma = request.files.get("firma")
                if archivo_firma is not None and archivo_firma.filename:
                    firma = archivo_firma.stream.read(4096).decode("ascii", "ignore")
                clave_firma = bd.obtener_config("clave_publica_firma", "")
                registro = act.guardar_paquete(tipo, version, os.path.basename(archivo.filename),
                                               archivo.stream, firma=firma, clave_publica=clave_firma)
                act.publicar(tipo, registro["version"], notas, firma=registro["firma"])
                if not clave_firma:
                    flash("Publicado sin verificar la firma: configura la clave pública en Ajustes "
                          "para que el panel la exija.", "error")
                bd.registrar_evento("actualizacion_publicada", "%s %s" % (tipo, registro["version"]),
                                    request.remote_addr or "")
                flash("Versión %s del %s publicada (SHA-256 %s...)." %
                      (registro["version"], tipo, registro["sha256"][:12]), "ok")

                if (tipo == "panel" and getattr(sys, "frozen", False)
                        and request.form.get("actualizar_ahora")):
                    ruta = os.path.join(act.DIR_ACTUALIZACIONES, registro["archivo"])
                    correcto, error = iniciar_actualizacion_panel(ruta)
                    if correcto:
                        return render_template("actualizando.html", version=registro["version"])
                    flash(error, "error")

            elif accion == "eliminar":
                tipo = request.form.get("tipo", "")
                act.eliminar(tipo)
                bd.registrar_evento("actualizacion_eliminada", tipo, request.remote_addr or "")
                flash("Se retiró la versión publicada del %s." % tipo, "ok")

            elif accion == "actualizar_panel":
                registro = act.entrada("panel")
                if not registro:
                    raise ValueError("No hay una versión del panel publicada.")
                ruta = os.path.join(act.DIR_ACTUALIZACIONES, registro["archivo"])
                correcto, error = iniciar_actualizacion_panel(ruta)
                if correcto:
                    return render_template("actualizando.html", version=registro["version"])
                flash(error, "error")

        except ValueError as exc:
            flash(str(exc), "error")

        return redirect(url_for("actualizaciones"))

    manifiesto = act.leer()
    panel_publicado = manifiesto.get("panel")
    agente_publicado = manifiesto.get("agente")
    return render_template(
        "actualizaciones.html",
        activo="actualizaciones",
        manifiesto=manifiesto,
        panel_publicado=panel_publicado,
        agente_publicado=agente_publicado,
        archivos=act.archivos(),
        actual=VERSION,
        puede_autoactualizar=bool(getattr(sys, "frozen", False)),
        hay_panel_nuevo=bool(panel_publicado and act.hay_nueva(panel_publicado.get("version"), VERSION)),
        url_version=request.host_url.rstrip("/") + "/api/version",
        exige_firma=bool(bd.obtener_config("clave_publica_firma", "")),
    )


def _lanzar_fuera_del_job(bat: str) -> bool:
    """Arranca el .bat fuera del árbol de procesos actual (WMI) para que
    sobreviva cuando el panel termine. Si WMI no está, usa Popen detached."""
    corto = bat
    try:
        import ctypes

        buffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.kernel32.GetShortPathNameW(bat, buffer, 32768):
            corto = buffer.value or bat
    except (AttributeError, OSError):
        pass

    if " " in corto:
        comando = 'cmd.exe /c ""%s""' % corto
    else:
        comando = 'cmd.exe /c "%s"' % corto

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
        banderas = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd", "/c", bat], creationflags=banderas, close_fds=True)
        return True
    except OSError:
        return False


def iniciar_actualizacion_panel(nuevo: str):
    """Programa el reemplazo del .exe en ejecución y reinicia el panel."""
    if not getattr(sys, "frozen", False):
        return False, ("La actualización automática del panel solo funciona con el .exe. "
                       "En Linux aplica el paquete y reinicia el servicio (ver docs/06_DESPLIEGUE.md).")
    if not os.path.isfile(nuevo):
        return False, "No se encontró el paquete del panel."
    if not nuevo.lower().endswith(".exe"):
        return False, ("En Windows el panel se actualiza con un .exe. "
                       "Para Linux usa deploy/actualizar.sh con el .zip.")

    actual = sys.executable
    bat = os.path.join(act.DIR_ACTUALIZACIONES, "_actualizar_panel.bat")
    argumentos = " ".join('"%s"' % a for a in sys.argv[1:])

    contenido = """@echo off
setlocal
timeout /t 2 /nobreak >nul
powershell -NoProfile -WindowStyle Hidden -Command "$i=0; while ((Get-Process -Id {pid} -ErrorAction SilentlyContinue) -and $i -lt 60) {{ Start-Sleep -Milliseconds 500; $i++ }}"
copy /Y "{actual}" "{actual}.bak" >nul 2>&1
copy /Y "{nuevo}" "{actual}" >nul 2>&1
if errorlevel 1 copy /Y "{actual}.bak" "{actual}" >nul 2>&1
start "" "{actual}" {args}
del "%~f0"
""".format(pid=os.getpid(), actual=actual, nuevo=nuevo, args=argumentos)

    try:
        with open(bat, "w", encoding="mbcs") as archivo:
            archivo.write(contenido)
    except (OSError, UnicodeError):
        with open(bat, "w", encoding="utf-8") as archivo:
            archivo.write(contenido)

    if not _lanzar_fuera_del_job(bat):
        return False, "No se pudo lanzar el actualizador del panel."

    log.info("Actualizando el panel a la versión publicada; reinicio programado.")
    threading.Timer(2.5, lambda: os._exit(0)).start()
    return True, ""


@app.route("/salud")
def salud():
    return jsonify({"ok": True, "servicio": "Unidad 17", "version": VERSION, "hora": bd.iso()})


# --------------------------------------------------------------------------
# Errores
# --------------------------------------------------------------------------
@app.errorhandler(404)
def no_encontrado(_error):
    return render_template("error.html", activo="", codigo=404,
                           mensaje="La página o el equipo solicitado no existe."), 404


@app.errorhandler(500)
def error_interno(_error):
    log.exception("Error interno")
    return render_template("error.html", activo="", codigo=500,
                           mensaje="Ocurrió un error inesperado en el servidor."), 500


# --------------------------------------------------------------------------
# Arranque
# --------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Panel Unidad 17")
    parser.add_argument("--puerto", type=int, default=int(CFG["puerto"]))
    parser.add_argument("--host", default=str(CFG["host"]))
    parser.add_argument("--sin-navegador", action="store_true")
    args = parser.parse_args()

    bd.inicializar()
    act.asegurar()

    host = args.host
    puerto = args.puerto
    visible = "127.0.0.1" if host in ("0.0.0.0", "::") else host
    url = f"http://{visible}:{puerto}"

    print("=" * 68)
    print("  PANEL UNIDAD 17")
    print("  URL local     :", url)
    print("  Red local     : http://%s:%s" % (ip_lan(), puerto))
    print("  Usuario       :", CFG["usuario_admin"])
    print("  Clave agentes :", CFG["clave_api"])
    print("  Base de datos :", ("PostgreSQL (esquema %s)" % PG_ESQUEMA) if ES_POSTGRES else RUTA_DB)
    print("  Detener       : Ctrl + C")
    print("=" * 68)

    if CFG.get("abrir_navegador", True) and not args.sin_navegador:
        threading.Timer(1.3, lambda: webbrowser.open(url)).start()

    try:
        app.run(host=host, port=puerto, debug=False, threaded=True, use_reloader=False)
    except OSError as exc:
        log.error("No se pudo iniciar el servidor: %s", exc)
        print("\n[ERROR] No se pudo abrir el puerto %s. ¿Ya hay otra copia abierta?" % puerto)


if __name__ == "__main__":
    main()
