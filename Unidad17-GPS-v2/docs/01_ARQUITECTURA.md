# Arquitectura

## Visión general

```
┌────────────────────────────┐        HTTPS/HTTP (LAN)        ┌──────────────────────────┐
│  Equipo con agente         │  POST /api/report              │  Servidor del panel      │
│  cliente.py                │  X-Clave-Agente: U17-...       │  Flask + SQLite          │
│                            │ ─────────────────────────────► │                          │
│  1. hardware.info_equipo() │                                │  validar_reporte()       │
│  2. geolocalizacion        │ ◄───────────────────────────── │  guardar_reporte()       │
│     · GPS Windows (winsdk) │        {"ok": true, id}        │  historial + eventos     │
│     · GPS .NET (PowerShell)│                                │                          │
│     · Wi-Fi + Google       │  GET /api/config  (clave)      │  ┌────────────────────┐  │
│     · ubicación por IP     │  GET /api/version (updates)    │  │ SQLite datos/      │  │
└────────────────────────────┘                                │  │ unidad17.db        │  │
                                                              │  └────────────────────┘  │
┌────────────────────────────┐        Navegador               │                          │
│  Administrador             │ ◄────────────────────────────► │  actualizaciones/        │
└────────────────────────────┘  login, panel, mapa, ajustes,   │  versiones.json + .exe   │
                                 actualizaciones              └──────────────────────────┘
```

## Componentes

### Servidor (`servidor/`)

| Archivo | Responsabilidad |
|---|---|
| `app.py` | Rutas Flask, login, CSRF, límite de intentos, API, exportación, actualizaciones, arranque |
| `actualizaciones.py` | Manifiesto `versiones.json`, SHA-256, paquetes y publicación |
| `base_datos.py` | Esquema SQLite, upsert de equipos, historial, métricas, configuración y auditoría |
| `configuracion.py` | `config.json`, claves generadas, rutas compatibles con PyInstaller |
| `wsgi.py` | Entrada para Gunicorn/Waitress en producción |
| `mantenimiento.py` | Purga de historial por antigüedad y `VACUUM` |
| `deploy/` | Unidad systemd, Caddyfile y script de actualización en Linux |
| `templates/` | Jinja2: `login`, `panel`, `equipo`, `mapa`, `ajustes`, `actualizaciones`, `error` |
| `static/` | CSS propio, JS, logo y Leaflet 1.9.4 servido en local |

### Cliente (`cliente/`)

| Archivo | Responsabilidad |
|---|---|
| `cliente.py` | Configuración, ciclo de reportes, cola, clave de Google, aviso inicial y registro |
| `geolocalizacion.py` | Cascada GPS Windows → GPS .NET → Wi-Fi + Google → IP; dirección inversa con Nominatim |
| `actualizador.py` | Consulta `/api/version`, descarga, verifica SHA-256 y programa el reemplazo silencioso |
| `cola.py` | Reportes pendientes en disco cuando el servidor no responde |
| `hardware.py` | Hostname, IP local, MAC, SO, CPU, RAM y disco libre |

## Flujo de un reporte

1. El agente lee `config.json` (URL, clave, intervalo).
2. Recopila hardware y ubicación. La ubicación se intenta en este orden:
   1. `winsdk.windows.devices.geolocation` (si está instalado y hay permiso).
   2. `System.Device.Location` mediante Windows PowerShell (sin instalar nada).
   3. Wi-Fi con `netsh wlan` + Geolocation API de Google (si el panel tiene clave).
   4. Servicios de IP: `ipapi.co`, `ipwho.is`, `ip-api.com`.
   5. Si hay coordenadas (GPS o Wi-Fi), se completa ciudad/país con Nominatim.
3. Envía `POST /api/report` con la cabecera `X-Clave-Agente`. Si el servidor no
   responde, el reporte se guarda en `datos_agente/cola.jsonl` y se reintenta en
   el siguiente ciclo.
4. El servidor valida tipos y rangos, hace *upsert* por `hostname` y guarda un
   punto de historial si el equipo se movió ≥ 30 m o pasaron ≥ 10 minutos.
5. El panel lee la base y muestra estado, posición e historial.

## Modelo de datos

```sql
equipos(id, hostname UNIQUE, ip_local, ip_publica, mac, so, procesador,
        arquitectura, ram_gb, disco_libre_gb, latitud, longitud, ciudad, pais,
        precision_m, fuente, version_agente, primera_conexion, ultima_conexion,
        total_reportes)

historial(id, equipo_id → equipos.id, latitud, longitud, ciudad, pais,
          precision_m, fuente, fecha)

usuarios(id, usuario UNIQUE, clave_hash, creado)

eventos(id, tipo, detalle, ip, fecha)

configuracion(clave TEXT PRIMARY KEY, valor TEXT)   -- google_api_key
```

* Fechas en UTC con formato `YYYY-MM-DDTHH:MM:SSZ`; la interfaz las muestra en
  hora local.
* `fuente` ∈ `gps`, `wifi`, `ip`, `manual`.
* `equipos.hostname` es la clave natural: un equipo que se renombra aparece
  como uno nuevo.

## Decisiones de diseño

* **Sin dependencias en el cliente**: solo biblioteca estándar; el GPS nativo es
  opcional (`winsdk`). Así el `.exe` es pequeño y no requiere instalar nada.
* **Mapa local**: Leaflet se sirve desde `static/vendor/leaflet`; solo las
  teselas vienen de Esri. Sin CDN ni claves de API.
* **Clave de agente obligatoria**: evita que cualquier equipo de la red inyecte
  posiciones falsas.
* **Historial acotado**: se guardan puntos relevantes, no cada reporte, para que
  la base no crezca sin control.
* **Agente visible**: la consola muestra cada envío. Es una decisión de
  transparencia, no una limitación técnica.

## Despliegue

* **LAN**: el servidor escucha en `0.0.0.0:5000`; hay que permitir el puerto en
  el firewall de Windows.
* **Varias redes**: publica el panel detrás de un proxy inverso con HTTPS
  (Caddy, Nginx, IIS) y usa esa URL en `config.json`.
* **Copias de seguridad**: detén el panel y copia la carpeta `datos/` (o usa
  `sqlite3 datos/unidad17.db ".backup copia.db"` con el servidor en marcha).
