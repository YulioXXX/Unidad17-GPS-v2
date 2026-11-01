# -*- coding: utf-8 -*-
"""Base de datos del panel Unidad 17 (SQLite o Postgres).

Tablas:
  * equipos   -> un registro por computadora (se actualiza en cada reporte)
  * historial -> recorrido de ubicaciones (solo puntos relevantes)
  * usuarios  -> credenciales del panel (hash scrypt de Werkzeug)
  * eventos   -> auditoría de accesos y cambios

Por defecto usa un archivo SQLite. Si existe la variable DATABASE_URL usa
Postgres (p. ej. Supabase): ``_ConexionPG`` adapta las consultas, que se
escriben una sola vez con marcadores ``?``.
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
import math
import os
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from configuracion import CFG, DATABASE_URL, ES_POSTGRES, PG_ESQUEMA, RUTA_DB

log = logging.getLogger("unidad17")

ESQUEMA = """
CREATE TABLE IF NOT EXISTS equipos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    hostname         TEXT NOT NULL UNIQUE,
    ip_local         TEXT DEFAULT '',
    ip_publica       TEXT DEFAULT '',
    mac              TEXT DEFAULT '',
    so               TEXT DEFAULT '',
    procesador       TEXT DEFAULT '',
    arquitectura     TEXT DEFAULT '',
    ram_gb           REAL,
    disco_libre_gb   REAL,
    latitud          REAL,
    longitud         REAL,
    ciudad           TEXT DEFAULT '',
    pais             TEXT DEFAULT '',
    precision_m      INTEGER,
    fuente           TEXT DEFAULT 'ip',
    version_agente   TEXT DEFAULT '',
    primera_conexion TEXT,
    ultima_conexion  TEXT,
    total_reportes   INTEGER DEFAULT 0,
    token_hash       TEXT,
    estado_token     TEXT DEFAULT 'sin',
    token_creado     TEXT
);

CREATE TABLE IF NOT EXISTS historial (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    equipo_id   INTEGER NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
    latitud     REAL NOT NULL,
    longitud    REAL NOT NULL,
    ciudad      TEXT DEFAULT '',
    pais        TEXT DEFAULT '',
    precision_m INTEGER,
    fuente      TEXT DEFAULT 'ip',
    fecha       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuarios (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario    TEXT NOT NULL UNIQUE,
    clave_hash TEXT NOT NULL,
    creado     TEXT,
    debe_cambiar INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS eventos (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    tipo    TEXT NOT NULL,
    detalle TEXT DEFAULT '',
    ip      TEXT DEFAULT '',
    fecha   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('google_api_key', '');

CREATE INDEX IF NOT EXISTS idx_historial_equipo ON historial(equipo_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_historial_fecha  ON historial(fecha);
CREATE INDEX IF NOT EXISTS idx_equipos_ultima   ON equipos(ultima_conexion);
"""

# Mismo esquema para Postgres. Las fechas son texto ISO-8601 de ancho fijo; con
# COLLATE "C" se ordenan y comparan byte a byte, igual que en SQLite.
ESQUEMA_PG = """
CREATE TABLE IF NOT EXISTS equipos (
    id               BIGSERIAL PRIMARY KEY,
    hostname         TEXT NOT NULL UNIQUE,
    ip_local         TEXT DEFAULT '',
    ip_publica       TEXT DEFAULT '',
    mac              TEXT DEFAULT '',
    so               TEXT DEFAULT '',
    procesador       TEXT DEFAULT '',
    arquitectura     TEXT DEFAULT '',
    ram_gb           DOUBLE PRECISION,
    disco_libre_gb   DOUBLE PRECISION,
    latitud          DOUBLE PRECISION,
    longitud         DOUBLE PRECISION,
    ciudad           TEXT DEFAULT '',
    pais             TEXT DEFAULT '',
    precision_m      INTEGER,
    fuente           TEXT DEFAULT 'ip',
    version_agente   TEXT DEFAULT '',
    primera_conexion TEXT COLLATE "C",
    ultima_conexion  TEXT COLLATE "C",
    total_reportes   INTEGER DEFAULT 0,
    token_hash       TEXT,
    estado_token     TEXT DEFAULT 'sin',
    token_creado     TEXT
);

CREATE TABLE IF NOT EXISTS historial (
    id          BIGSERIAL PRIMARY KEY,
    equipo_id   BIGINT NOT NULL REFERENCES equipos(id) ON DELETE CASCADE,
    latitud     DOUBLE PRECISION NOT NULL,
    longitud    DOUBLE PRECISION NOT NULL,
    ciudad      TEXT DEFAULT '',
    pais        TEXT DEFAULT '',
    precision_m INTEGER,
    fuente      TEXT DEFAULT 'ip',
    fecha       TEXT NOT NULL COLLATE "C"
);

CREATE TABLE IF NOT EXISTS usuarios (
    id           BIGSERIAL PRIMARY KEY,
    usuario      TEXT NOT NULL UNIQUE,
    clave_hash   TEXT NOT NULL,
    creado       TEXT,
    debe_cambiar INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS eventos (
    id      BIGSERIAL PRIMARY KEY,
    tipo    TEXT NOT NULL,
    detalle TEXT DEFAULT '',
    ip      TEXT DEFAULT '',
    fecha   TEXT NOT NULL COLLATE "C"
);

CREATE TABLE IF NOT EXISTS configuracion (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE TABLE IF NOT EXISTS paquetes (
    nombre    TEXT PRIMARY KEY,
    contenido BYTEA NOT NULL,
    tamano    BIGINT,
    fecha     TEXT
);

INSERT INTO configuracion (clave, valor) VALUES ('google_api_key', '') ON CONFLICT DO NOTHING;

CREATE INDEX IF NOT EXISTS idx_historial_equipo ON historial(equipo_id, fecha DESC);
CREATE INDEX IF NOT EXISTS idx_historial_fecha  ON historial(fecha);
CREATE INDEX IF NOT EXISTS idx_equipos_ultima   ON equipos(ultima_conexion);
CREATE INDEX IF NOT EXISTS idx_equipos_token    ON equipos(token_hash);
"""


class Fila(tuple):
    """Fila de Postgres con el mismo uso que ``sqlite3.Row``: por posición,
    por nombre, ``keys()`` y ``dict(fila)``."""

    def __new__(cls, valores, nombres):
        objeto = super().__new__(cls, valores)
        objeto._nombres = list(nombres)
        return objeto

    def __getitem__(self, clave):
        if isinstance(clave, str):
            try:
                return tuple.__getitem__(self, self._nombres.index(clave))
            except ValueError:
                raise KeyError(clave) from None
        return tuple.__getitem__(self, clave)

    def keys(self):
        return list(self._nombres)


def _fabrica_filas(cursor):
    nombres = [columna.name for columna in (cursor.description or [])]
    return lambda valores: Fila(valores, nombres)


def _traducir(sql: str) -> str:
    """Pasa una consulta escrita con ``?`` al formato de psycopg (``%s``)."""
    return sql.replace("%", "%%").replace("?", "%s")


class _ConexionPG:
    """Envoltorio mínimo con la parte de la API de sqlite3 que usa este módulo."""

    def __init__(self, conexion):
        self._con = conexion

    def execute(self, sql: str, params=()):
        return self._con.execute(_traducir(sql), tuple(params))

    def executescript(self, script: str) -> None:
        for sentencia in script.split(";"):
            if sentencia.strip():
                self._con.execute(sentencia)

    def commit(self) -> None:
        self._con.commit()

    def rollback(self) -> None:
        self._con.rollback()

    def close(self) -> None:
        self._con.close()


_ESTADO = {"listo": False, "en_curso": False}


def _abrir_pg(crear_esquema: bool = False) -> _ConexionPG:
    import psycopg  # solo se necesita en modo Postgres

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,40}", PG_ESQUEMA):
        raise RuntimeError("UNIDAD17_PG_SCHEMA solo admite letras, números y guion bajo.")
    con = psycopg.connect(
        DATABASE_URL,
        row_factory=_fabrica_filas,
        connect_timeout=10,
        sslmode=os.environ.get("UNIDAD17_PG_SSLMODE", "require"),
        prepare_threshold=None,  # el pooler de Supabase no admite sentencias preparadas
    )
    if crear_esquema:
        con.execute('CREATE SCHEMA IF NOT EXISTS "%s"' % PG_ESQUEMA)
    con.execute('SET search_path TO "%s"' % PG_ESQUEMA)
    con.commit()
    return _ConexionPG(con)


CAMPOS_REPORTE = (
    "ip_local", "ip_publica", "mac", "so", "procesador", "arquitectura",
    "ram_gb", "disco_libre_gb", "latitud", "longitud", "ciudad", "pais",
    "precision_m", "fuente", "version_agente",
)


# --------------------------------------------------------------------------
# Utilidades de fecha
# --------------------------------------------------------------------------
def ahora() -> datetime:
    return datetime.now(timezone.utc)


def iso(momento: datetime | None = None) -> str:
    return (momento or ahora()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def desde_iso(texto: str | None) -> datetime | None:
    if not texto:
        return None
    try:
        return datetime.strptime(texto, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def segundos_desde(texto: str | None) -> float:
    momento = desde_iso(texto)
    if momento is None:
        return float("inf")
    return (ahora() - momento).total_seconds()


# --------------------------------------------------------------------------
# Conexión e instalación
# --------------------------------------------------------------------------
def conectar():
    if ES_POSTGRES:
        # Si la base no estaba disponible al arrancar (p. ej. proyecto pausado),
        # el esquema se crea en la primera conexión que funcione.
        if not _ESTADO["listo"] and not _ESTADO["en_curso"]:
            inicializar()
        return _abrir_pg()
    carpeta = os.path.dirname(RUTA_DB)
    if carpeta:
        os.makedirs(carpeta, exist_ok=True)
    con = sqlite3.connect(RUTA_DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def inicializar() -> None:
    _ESTADO["en_curso"] = True
    try:
        if ES_POSTGRES:
            con = _abrir_pg(crear_esquema=True)
            try:
                con.executescript(ESQUEMA_PG)
                _asegurar_admin(con)
                _asegurar_modo_clave_global(con)
                con.commit()
            finally:
                con.close()
        else:
            con = conectar()
            try:
                con.executescript(ESQUEMA)
                _asegurar_columnas(con)
                _asegurar_admin(con)
                _asegurar_modo_clave_global(con)
                con.commit()
            finally:
                con.close()
        _ESTADO["listo"] = True
    finally:
        _ESTADO["en_curso"] = False


def _asegurar_columnas(con: sqlite3.Connection) -> None:
    existentes = {fila["name"] for fila in con.execute("PRAGMA table_info(equipos)")}
    columnas = {
        "arquitectura": "TEXT DEFAULT ''",
        "ram_gb": "REAL",
        "disco_libre_gb": "REAL",
        "version_agente": "TEXT DEFAULT ''",
        "pais": "TEXT DEFAULT ''",
        "token_hash": "TEXT",
        "estado_token": "TEXT DEFAULT 'sin'",
        "token_creado": "TEXT",
    }
    for nombre, tipo in columnas.items():
        if nombre not in existentes:
            con.execute(f"ALTER TABLE equipos ADD COLUMN {nombre} {tipo}")
    con.execute("UPDATE equipos SET estado_token = 'sin' WHERE estado_token IS NULL")
    con.execute("CREATE INDEX IF NOT EXISTS idx_equipos_token ON equipos(token_hash)")

    # Usuarios: columna para obligar a cambiar la contraseña.
    usuarios = {fila["name"] for fila in con.execute("PRAGMA table_info(usuarios)")}
    if "debe_cambiar" not in usuarios:
        con.execute("ALTER TABLE usuarios ADD COLUMN debe_cambiar INTEGER DEFAULT 0")
        # Instalaciones anteriores: quien siga con la contraseña de fábrica
        # (o la de config.json) deberá cambiarla en su próximo acceso.
        conocidas = {"unidad17", str(CFG.get("clave_admin", ""))}
        for fila in con.execute("SELECT id, clave_hash FROM usuarios").fetchall():
            if any(c and check_password_hash(fila["clave_hash"], c) for c in conocidas):
                con.execute("UPDATE usuarios SET debe_cambiar = 1 WHERE id = ?", (fila["id"],))
    con.commit()


def _asegurar_admin(con: sqlite3.Connection) -> None:
    if con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        con.execute(
            "INSERT INTO usuarios (usuario, clave_hash, creado, debe_cambiar) VALUES (?, ?, ?, 1)",
            (CFG["usuario_admin"], generate_password_hash(CFG["clave_admin"]), iso()),
        )
        con.commit()


def _asegurar_modo_clave_global(con: sqlite3.Connection) -> None:
    """Decide si los agentes pueden seguir usando la clave global para reportar.

    Instalación nueva (sin equipos): desactivado. Instalación con equipos que
    ya reportan con la clave global: activado hasta que el administrador lo
    desactive, para no dejar a los agentes antiguos sin servicio.
    """
    existe = con.execute(
        "SELECT 1 FROM configuracion WHERE clave = 'permitir_clave_global'"
    ).fetchone()
    if existe is None:
        hay_equipos = con.execute("SELECT COUNT(*) FROM equipos").fetchone()[0] > 0
        con.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('permitir_clave_global', ?)",
            ("1" if hay_equipos else "0",),
        )


# --------------------------------------------------------------------------
# Reportes del agente
# --------------------------------------------------------------------------
def guardar_reporte(datos: dict) -> tuple[int, bool]:
    """Crea o actualiza un equipo y devuelve ``(id, es_nuevo)``."""
    momento = iso()
    valores = [datos.get(campo) for campo in CAMPOS_REPORTE]

    con = conectar()
    try:
        fila = con.execute(
            "SELECT id FROM equipos WHERE hostname = ?", (datos["hostname"],)
        ).fetchone()

        if fila is None:
            columnas = ", ".join(("hostname",) + CAMPOS_REPORTE + ("primera_conexion", "ultima_conexion"))
            marcas = ", ".join("?" for _ in range(len(CAMPOS_REPORTE) + 3))
            cur = con.execute(
                f"INSERT INTO equipos ({columnas}, total_reportes) VALUES ({marcas}, 1) RETURNING id",
                [datos["hostname"]] + valores + [momento, momento],
            )
            equipo_id = int(cur.fetchone()["id"])
            es_nuevo = True
        else:
            equipo_id = int(fila["id"])
            asignaciones = ", ".join(f"{campo} = ?" for campo in CAMPOS_REPORTE)
            con.execute(
                f"""UPDATE equipos SET {asignaciones},
                        ultima_conexion = ?, total_reportes = total_reportes + 1
                    WHERE id = ?""",
                valores + [momento, equipo_id],
            )
            es_nuevo = False

        latitud, longitud = datos.get("latitud"), datos.get("longitud")
        if latitud is not None and longitud is not None:
            _registrar_punto(con, equipo_id, datos, momento)

        con.commit()
    finally:
        con.close()
    _depuracion_diaria()
    return equipo_id, es_nuevo


def _registrar_punto(con: sqlite3.Connection, equipo_id: int, datos: dict, momento: str) -> None:
    ultimo = con.execute(
        "SELECT latitud, longitud, fecha FROM historial WHERE equipo_id = ? ORDER BY fecha DESC LIMIT 1",
        (equipo_id,),
    ).fetchone()

    registrar = ultimo is None
    if ultimo is not None:
        metros = _distancia_metros(ultimo["latitud"], ultimo["longitud"],
                                   datos["latitud"], datos["longitud"])
        registrar = metros >= 30 or segundos_desde(ultimo["fecha"]) >= 600

    if registrar:
        con.execute(
            """INSERT INTO historial
                   (equipo_id, latitud, longitud, ciudad, pais, precision_m, fuente, fecha)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (equipo_id, datos["latitud"], datos["longitud"], datos.get("ciudad", ""),
             datos.get("pais", ""), datos.get("precision_m"), datos.get("fuente", "ip"), momento),
        )


def _distancia_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia aproximada entre dos coordenadas (haversine)."""
    radio = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radio * math.asin(math.sqrt(a))


# --------------------------------------------------------------------------
# Consultas del panel
# --------------------------------------------------------------------------
def listar_equipos() -> list[sqlite3.Row]:
    con = conectar()
    try:
        return con.execute(
            "SELECT * FROM equipos ORDER BY (ultima_conexion IS NULL), ultima_conexion DESC"
        ).fetchall()
    finally:
        con.close()


def obtener_equipo(equipo_id: int) -> sqlite3.Row | None:
    con = conectar()
    try:
        return con.execute("SELECT * FROM equipos WHERE id = ?", (equipo_id,)).fetchone()
    finally:
        con.close()


def historial_equipo(equipo_id: int, limite: int = 100) -> list[sqlite3.Row]:
    con = conectar()
    try:
        return con.execute(
            "SELECT * FROM historial WHERE equipo_id = ? ORDER BY fecha DESC LIMIT ?",
            (equipo_id, limite),
        ).fetchall()
    finally:
        con.close()


def resumen() -> dict:
    limite_linea = iso(ahora() - timedelta(minutes=int(CFG["minutos_offline"])))
    limite_24h = iso(ahora() - timedelta(hours=24))
    limite_7d = iso(ahora() - timedelta(days=7))

    con = conectar()
    try:
        fila = con.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(CASE WHEN ultima_conexion >= ? THEN 1 ELSE 0 END), 0) AS en_linea,
                      COALESCE(SUM(CASE WHEN ultima_conexion >= ? AND fuente = 'gps' THEN 1 ELSE 0 END), 0) AS con_gps,
                      COALESCE(SUM(CASE WHEN ultima_conexion < ? THEN 1 ELSE 0 END), 0) AS sin_conexion
                 FROM equipos""",
            (limite_linea, limite_linea, limite_24h),
        ).fetchone()
        reportes = con.execute(
            "SELECT COUNT(*) FROM historial WHERE fecha >= ?", (limite_7d,)
        ).fetchone()[0]
    finally:
        con.close()

    return {
        "total": fila["total"],
        "en_linea": fila["en_linea"],
        "con_gps": fila["con_gps"],
        "sin_conexion": fila["sin_conexion"],
        "reportes_7d": reportes,
    }


def actividad_7_dias() -> list[dict]:
    hoy = ahora().date()
    con = conectar()
    try:
        datos = []
        for i in range(6, -1, -1):
            dia = hoy - timedelta(days=i)
            total = con.execute(
                "SELECT COUNT(*) FROM historial WHERE substr(fecha, 1, 10) = ?",
                (dia.isoformat(),),
            ).fetchone()[0]
            datos.append({"etiqueta": dia.strftime("%d/%m"), "total": total})
    finally:
        con.close()
    return datos


def distribucion_fuente() -> dict:
    con = conectar()
    try:
        filas = con.execute("SELECT fuente, COUNT(*) AS total FROM equipos GROUP BY fuente").fetchall()
    finally:
        con.close()

    datos = {"gps": 0, "wifi": 0, "ip": 0, "sin": 0}
    for fila in filas:
        clave = fila["fuente"] if fila["fuente"] in ("gps", "wifi", "ip") else "sin"
        datos[clave] += fila["total"]
    return datos


# --------------------------------------------------------------------------
# Configuración editable desde el panel (clave de Google, etc.)
# --------------------------------------------------------------------------
def obtener_config(clave: str, defecto: str = "") -> str:
    con = conectar()
    try:
        fila = con.execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (clave,)
        ).fetchone()
    finally:
        con.close()
    return (fila["valor"] or "") if fila else defecto


def guardar_config(clave: str, valor: str) -> None:
    con = conectar()
    try:
        con.execute(
            "INSERT INTO configuracion (clave, valor) VALUES (?, ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave, valor),
        )
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------
# Usuarios y auditoría
# --------------------------------------------------------------------------
def verificar_usuario(usuario: str, clave: str) -> bool:
    con = conectar()
    try:
        fila = con.execute(
            "SELECT clave_hash FROM usuarios WHERE usuario = ?", (usuario,)
        ).fetchone()
    finally:
        con.close()
    return bool(fila) and check_password_hash(fila["clave_hash"], clave)


def cambiar_clave(usuario: str, nueva: str) -> None:
    con = conectar()
    try:
        con.execute(
            "UPDATE usuarios SET clave_hash = ?, debe_cambiar = 0 WHERE usuario = ?",
            (generate_password_hash(nueva), usuario),
        )
        con.commit()
    finally:
        con.close()


def debe_cambiar_clave(usuario: str) -> bool:
    con = conectar()
    try:
        fila = con.execute(
            "SELECT debe_cambiar FROM usuarios WHERE usuario = ?", (usuario,)
        ).fetchone()
    finally:
        con.close()
    return bool(fila and fila["debe_cambiar"])


# --------------------------------------------------------------------------
# Tokens por equipo
# --------------------------------------------------------------------------
# estado_token: 'sin'       el equipo aún no tiene token (usa la clave global)
#               'activo'    tiene un token válido
#               'revocado'  el administrador lo bloqueó; no puede volver a
#                           enrolarse hasta que se lo permitan
#               'reenrolar' el administrador permitió que pida un token nuevo
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def enrolar_equipo(hostname: str) -> tuple[str | None, str]:
    """Entrega un token nuevo al equipo si está permitido.

    Devuelve ``(token, motivo)``. Si no se puede, ``token`` es ``None`` y el
    motivo es ``activo`` (ya tiene uno) o ``revocado``.
    """
    momento = iso()
    con = conectar()
    try:
        fila = con.execute(
            "SELECT id, estado_token FROM equipos WHERE hostname = ?", (hostname,)
        ).fetchone()
        token = "T17-" + secrets.token_urlsafe(32)
        if fila is None:
            con.execute(
                """INSERT INTO equipos (hostname, primera_conexion, ultima_conexion,
                                        total_reportes, token_hash, estado_token, token_creado)
                   VALUES (?, ?, ?, 0, ?, 'activo', ?)""",
                (hostname, momento, momento, _hash_token(token), momento),
            )
            con.commit()
            return token, "nuevo"

        estado = fila["estado_token"] or "sin"
        if estado in ("sin", "reenrolar"):
            con.execute(
                """UPDATE equipos SET token_hash = ?, estado_token = 'activo', token_creado = ?
                   WHERE id = ?""",
                (_hash_token(token), momento, fila["id"]),
            )
            con.commit()
            return token, "ok"
        return None, estado
    finally:
        con.close()


def equipo_por_token(token) -> sqlite3.Row | None:
    """Devuelve el equipo dueño del token, solo si el token sigue activo."""
    if not isinstance(token, str) or not token or len(token) > 200:
        return None
    con = conectar()
    try:
        fila = con.execute(
            "SELECT id, hostname, estado_token FROM equipos WHERE token_hash = ?",
            (_hash_token(token),),
        ).fetchone()
    finally:
        con.close()
    if fila is not None and fila["estado_token"] == "activo":
        return fila
    return None


def estado_token_por_hostname(hostname: str) -> str:
    con = conectar()
    try:
        fila = con.execute(
            "SELECT estado_token FROM equipos WHERE hostname = ?", (hostname,)
        ).fetchone()
    finally:
        con.close()
    return (fila["estado_token"] or "sin") if fila else "sin"


def revocar_token(equipo_id: int) -> None:
    con = conectar()
    try:
        con.execute(
            "UPDATE equipos SET token_hash = NULL, estado_token = 'revocado' WHERE id = ?",
            (equipo_id,),
        )
        con.commit()
    finally:
        con.close()


def permitir_reenrolamiento(equipo_id: int) -> None:
    con = conectar()
    try:
        con.execute(
            "UPDATE equipos SET token_hash = NULL, estado_token = 'reenrolar' WHERE id = ?",
            (equipo_id,),
        )
        con.commit()
    finally:
        con.close()


def contar_sin_token() -> int:
    con = conectar()
    try:
        return con.execute(
            "SELECT COUNT(*) FROM equipos WHERE COALESCE(estado_token, 'sin') = 'sin'"
        ).fetchone()[0]
    finally:
        con.close()


def registrar_evento(tipo: str, detalle: str = "", ip: str = "") -> None:
    con = conectar()
    try:
        con.execute(
            "INSERT INTO eventos (tipo, detalle, ip, fecha) VALUES (?, ?, ?, ?)",
            (tipo[:40], detalle[:300], ip[:64], iso()),
        )
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------
# Mantenimiento
# --------------------------------------------------------------------------
def depurar_historial(dias: int) -> int:
    """Borra los puntos de historial anteriores a ``dias`` días (0 = todos)."""
    corte = iso(ahora() - timedelta(days=dias))
    con = conectar()
    try:
        borrados = con.execute("DELETE FROM historial WHERE fecha < ?", (corte,)).rowcount
        con.commit()
    finally:
        con.close()
    return max(0, borrados)


def depurar_eventos(dias: int) -> int:
    corte = iso(ahora() - timedelta(days=dias))
    con = conectar()
    try:
        borrados = con.execute("DELETE FROM eventos WHERE fecha < ?", (corte,)).rowcount
        con.commit()
    finally:
        con.close()
    return max(0, borrados)


_ultima_depuracion = [0.0]


def _depuracion_diaria() -> None:
    """Una vez al día (por proceso) recorta historial y eventos antiguos, para
    no agotar el espacio de un plan gratuito. Nunca interrumpe un reporte."""
    dias = int(CFG.get("historial_dias") or 0)
    if not CFG.get("depuracion_automatica") or dias <= 0:
        return
    if time.monotonic() - _ultima_depuracion[0] < 86400 and _ultima_depuracion[0]:
        return
    _ultima_depuracion[0] = time.monotonic()
    try:
        puntos = depurar_historial(dias)
        eventos = depurar_eventos(max(dias, 180))
        if puntos or eventos:
            log.info("Depuración automática: %d puntos de historial y %d eventos antiguos", puntos, eventos)
    except Exception as exc:  # noqa: BLE001
        log.warning("No se pudo depurar la base de datos: %s", exc)


# --------------------------------------------------------------------------
# Paquetes de actualización en la base (solo Postgres)
# --------------------------------------------------------------------------
def guardar_paquete_blob(nombre: str, ruta: str) -> None:
    with open(ruta, "rb") as archivo:
        contenido = archivo.read()
    con = conectar()
    try:
        con.execute(
            "INSERT INTO paquetes (nombre, contenido, tamano, fecha) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(nombre) DO UPDATE SET contenido = excluded.contenido, "
            "tamano = excluded.tamano, fecha = excluded.fecha",
            (nombre, contenido, len(contenido), iso()),
        )
        con.commit()
    finally:
        con.close()


def leer_paquete_blob(nombre: str):
    con = conectar()
    try:
        fila = con.execute("SELECT contenido FROM paquetes WHERE nombre = ?", (nombre,)).fetchone()
    finally:
        con.close()
    return bytes(fila["contenido"]) if fila else None


def conservar_paquetes(nombres) -> None:
    """Borra de la base los paquetes que ya no están en el manifiesto."""
    nombres = [n for n in nombres if n]
    con = conectar()
    try:
        if nombres:
            marcas = ", ".join("?" for _ in nombres)
            con.execute("DELETE FROM paquetes WHERE nombre NOT IN (%s)" % marcas, nombres)
        else:
            con.execute("DELETE FROM paquetes")
        con.commit()
    finally:
        con.close()


# --------------------------------------------------------------------------
# Exportación
# --------------------------------------------------------------------------
def _celda_csv(valor) -> str:
    """Evita que un valor de texto se interprete como fórmula en Excel."""
    if valor is None:
        return ""
    texto = str(valor)
    if texto[:1] in ("=", "+", "-", "@"):
        texto = "'" + texto
    return texto


def exportar_csv() -> str:
    filas = listar_equipos()
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    escritor.writerow([
        "Hostname", "IP local", "IP publica", "MAC", "Sistema", "Procesador",
        "Arquitectura", "RAM (GB)", "Disco libre (GB)", "Latitud", "Longitud",
        "Ciudad", "Pais", "Precision (m)", "Fuente", "Primera conexion",
        "Ultima conexion", "Reportes",
    ])
    for fila in filas:
        escritor.writerow([_celda_csv(valor) for valor in (
            fila["hostname"], fila["ip_local"], fila["ip_publica"], fila["mac"],
            fila["so"], fila["procesador"], fila["arquitectura"], fila["ram_gb"],
            fila["disco_libre_gb"], fila["latitud"], fila["longitud"], fila["ciudad"],
            fila["pais"], fila["precision_m"], fila["fuente"], fila["primera_conexion"],
            fila["ultima_conexion"], fila["total_reportes"],
        )])
    return "\ufeff" + buffer.getvalue()
