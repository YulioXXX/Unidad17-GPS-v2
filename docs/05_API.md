# API

Base: `http://IP_DEL_SERVIDOR:5000`

## Autenticación

Los reportes de los agentes se autentican con la cabecera:

```
X-Clave-Agente: U17-...
```

La clave se genera en el primer arranque y se consulta en **Ajustes**.

Las rutas del panel (`/api/equipos`, `/exportar.csv`) usan la cookie de sesión
del login, no la clave de agente.

## POST /api/report

Registra o actualiza un equipo.

**Cabeceras**

```
Content-Type: application/json
X-Clave-Agente: U17-...
```

**Cuerpo**

| Campo | Tipo | Obligatorio | Notas |
|---|---|---|---|
| `hostname` | string | sí | Máx. 64; identifica el equipo (único) |
| `ip_local` | string | no | IPv4/IPv6 local |
| `ip_publica` | string | no | IP de salida |
| `mac` | string | no | Máx. 32 |
| `so` | string | no | Sistema operativo |
| `procesador` | string | no | CPU |
| `arquitectura` | string | no | `AMD64`, `x86`, `ARM64`… |
| `ram_gb` | número | no | 0–4096 |
| `disco_libre_gb` | número | no | 0–100000 |
| `latitud` | número | no | −90 a 90; debe venir con longitud |
| `longitud` | número | no | −180 a 180 |
| `ciudad` | string | no | Máx. 80 |
| `pais` | string | no | Máx. 80 |
| `precision_m` | número | no | Precisión estimada en metros |
| `fuente` | string | no | `gps`, `ip` o `manual` (por defecto `ip`) |
| `version_agente` | string | no | Versión del cliente |

Los textos se recortan a su longitud máxima y se eliminan caracteres de control.
Los números fuera de rango se guardan como `null`.

**Ejemplo**

```bash
curl -X POST http://192.168.1.50:5000/api/report \
  -H "Content-Type: application/json" \
  -H "X-Clave-Agente: U17-..." \
  -d '{
    "hostname": "PC-RECEPCION",
    "ip_local": "192.168.1.20",
    "ip_publica": "190.1.2.3",
    "mac": "AA:BB:CC:DD:EE:FF",
    "so": "Windows 11 (build 22631)",
    "procesador": "Intel Core i5-10400",
    "arquitectura": "AMD64",
    "ram_gb": 16,
    "disco_libre_gb": 120.5,
    "latitud": 10.0678,
    "longitud": -69.3474,
    "ciudad": "Barquisimeto",
    "pais": "Venezuela",
    "precision_m": 12,
    "fuente": "gps",
    "version_agente": "1.0.0"
  }'
```

**Respuesta correcta**

```json
{"ok": true, "equipo_id": 3, "nuevo": false}
```

**Errores**

| Código | Cuerpo | Causa |
|---|---|---|
| 400 | `{"ok": false, "error": "hostname obligatorio"}` | Falta el hostname |
| 400 | `{"ok": false, "error": "latitud y longitud deben enviarse juntas"}` | Solo una coordenada |
| 401 | `{"ok": false, "error": "clave de agente inválida"}` | Clave ausente o incorrecta |

## GET /salud

Comprobación de disponibilidad, sin autenticación.

```json
{"ok": true, "servicio": "Unidad 17", "version": "1.0.10", "hora": "2026-10-25T22:14:34Z"}
```

## GET /api/config

Devuelve la clave de Google al agente autenticado. Requiere la misma cabecera
que los reportes.

```
X-Clave-Agente: U17-...
```

```json
{"ok": true, "google_api_key": "AIza..."}
```

Si la clave está vacía, el agente omite la triangulación Wi-Fi. La respuesta sin
cabecera válida es `401`.

## GET /api/version

Manifiesto público de versiones.

```json
{
  "ok": true,
  "servidor": {"version": "1.0.10", "hora": "..."},
  "agente": {
    "version": "1.0.11",
    "archivo": "Unidad17-Agente-1.0.11.exe",
    "sha256": "…",
    "tamano": 9602122,
    "fecha": "2026-10-25T23:50:54Z",
    "notas": "…",
    "url": "http://127.0.0.1:5000/actualizaciones/descargar/Unidad17-Agente-1.0.11.exe"
  },
  "panel": {"...": "..."}
}
```

## GET /actualizaciones/descargar/&lt;archivo&gt;

Descarga pública de un paquete publicado. Solo sirve archivos del manifiesto.

## Panel

Las rutas `/actualizaciones`, `/panel`, `/equipo/<id>`, `/mapa`, `/ajustes` y
`/exportar.csv` requieren sesión iniciada.

## GET /api/equipos

Requiere sesión iniciada.

```json
{
  "ok": true,
  "resumen": {"total": 7, "en_linea": 4, "con_gps": 4, "sin_conexion": 2, "reportes_7d": 132},
  "equipos": [
    {
      "id": 1,
      "hostname": "PC-PRUEBA",
      "en_linea": true,
      "ultima_conexion": "2026-10-25T22:16:43Z",
      "ultima_texto": "hace 2 min",
      "fuente": "gps"
    }
  ]
}
```

## GET /exportar.csv

Requiere sesión. Devuelve un CSV con separador `;`, codificación UTF-8 con BOM
(Excel lo abre directamente) y cabecera:

```
Hostname;IP local;IP publica;MAC;Sistema;Procesador;Arquitectura;RAM (GB);
Disco libre (GB);Latitud;Longitud;Ciudad;Pais;Precision (m);Fuente;
Primera conexion;Ultima conexion;Reportes
```

## Notas

* Las fechas son UTC (`YYYY-MM-DDTHH:MM:SSZ`); la interfaz las convierte a hora
  local.
* El servidor guarda un punto de historial cuando el equipo se mueve al menos
  30 m o pasan 10 minutos desde el anterior.
* `hostname` es la clave natural: si cambia, se crea un equipo nuevo.
