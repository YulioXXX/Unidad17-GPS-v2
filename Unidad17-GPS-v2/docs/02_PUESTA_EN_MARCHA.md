# Puesta en marcha

## 0. Antes de empezar

* Windows 10/11 en el servidor y en los equipos a ubicar.
* Python 3.9+ en el servidor si vas a ejecutar desde código (no hace falta si
  usas el `.exe`).
* Todos los equipos deben verse entre sí en la red (misma LAN o VPN).
* Decide qué equipos vas a registrar y con qué autorización (ver
  `03_LEGAL_Y_PRIVACIDAD.md`).

## 1. Servidor

```bat
cd servidor
pip install -r requirements.txt
python app.py
```

Salida esperada:

```
====================================================================
  PANEL UNIDAD 17
  URL local     : http://127.0.0.1:5000
  Red local     : http://192.168.1.50:5000
  Usuario       : admin
  Clave agentes : U17-xxxxxxxxxxxxxxxxxxxxxxxx
  Base de datos : ...\servidor\datos\unidad17.db
====================================================================
```

En el primer arranque se crea `servidor\config.json`. Contiene la clave de
agente, la clave secreta de sesiones y el usuario inicial:

```json
{
  "host": "0.0.0.0",
  "puerto": 5000,
  "abrir_navegador": true,
  "usuario_admin": "admin",
  "clave_admin": "unidad17",
  "clave_api": "U17-...",
  "clave_secreta": "...",
  "minutos_offline": 15
}
```

> `clave_admin` solo se usa para crear el usuario la primera vez. Después manda
> la contraseña guardada en la base de datos (cámbiala desde **Ajustes**).

### Abrir el puerto en el firewall

PowerShell **como administrador**:

```powershell
New-NetFirewallRule -DisplayName "Unidad17 Panel" -Direction Inbound `
  -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

Si el servidor está en una red pública, limita el alcance a `-Profile Private` y
considera usar una VPN.

### Acceso desde otro equipo

Abre `http://IP_DEL_SERVIDOR:5000` en el navegador. Si no carga:

1. `ping IP_DEL_SERVIDOR`.
2. Comprueba que el firewall permite el puerto.
3. Verifica que el panel sigue abierto (la consola debe seguir en ejecución).

## 2. Agente en el equipo

1. Copia la carpeta `cliente/` al equipo (o el `.exe` compilado).
2. Copia `config.ejemplo.json` como `config.json`.
3. Edita:

```json
{
  "url_servidor": "http://192.168.1.50:5000",
  "clave_agente": "U17-...",
  "intervalo_segundos": 300,
  "tiempo_limite": 15,
  "avisar_al_iniciar": true,
  "auto_actualizar": true,
  "horas_actualizacion": 6,
  "max_cola": 5000
}
```

La clave se copia desde **Ajustes → Clave de agente**.

### Wi-Fi con Google (opcional)

Para que el agente pueda triangular por Wi-Fi cuando el GPS de Windows no esté
disponible:

1. Habilita **Geolocation API** en Google Cloud Console y crea una API Key.
2. En el panel: **Ajustes → Google Geolocation (Wi-Fi)** → guarda la clave.
3. El agente la recibe al reportar; no hay que reiniciarlo ni copiarla a cada
   equipo.

Sin clave, la secuencia sigue siendo GPS de Windows → IP.

### Actualizaciones

Cuando publiques una versión en **Actualizaciones**, el agente la descarga y se
reemplaza solo (verifica SHA-256). No hace falta tocar cada equipo.

4. Prueba la configuración:

```bat
python cliente.py --diagnostico
```

El diagnóstico muestra hardware, respuesta de `/salud` y el resultado de cada
método de ubicación.

5. Inicia el agente:

```bat
python cliente.py
```

Verás un banner y una línea por cada reporte:

```
2026-10-25 18:14:02  OK   reporte aceptado (equipo #3)  ->  GPS 10.06780, -69.34740 | Barquisimeto | Venezuela
```

Deja la ventana abierta: el agente es visible a propósito.

## 3. Comprobar que funciona

* En el panel, el equipo debe aparecer con estado **En línea**.
* `Última conexión` debe decir *ahora* (se actualiza solo cada 45 s).
* Abre la ficha del equipo: verás hardware, mapa e historial.
* Si no hay coordenadas, revisa la sección de problemas.

## 4. GPS de Windows

Windows no entrega ubicación a aplicaciones de escritorio sin permiso:

1. **Configuración → Privacidad y seguridad → Ubicación** → activar.
2. Permitir que las aplicaciones de escritorio accedan a la ubicación.
3. Instalar el paquete opcional en el equipo:

```bat
pip install winsdk
```

Si no se instala, el agente intenta el GPS vía .NET y, si falla, usa la IP. Para
equipos de escritorio sin Wi-Fi ni GPS, la ubicación por IP será la habitual.

## 5. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `No se pudo conectar con ...` | URL incorrecta, firewall o panel apagado | Revisa IP/puerto con `--diagnostico` |
| `HTTP 401` | Clave de agente distinta | Copia de nuevo la clave desde Ajustes |
| Sin coordenadas | Ubicación de Windows desactivada y sin salida a Internet | Activa la ubicación o conecta el equipo a Internet |
| Ciudad vacía pero hay coordenadas | Nominatim no respondió | Es cosmético; las coordenadas sí se guardan |
| El mapa aparece vacío | Sin Internet en el equipo que abre el panel | Usa el enlace a OpenStreetMap de la ficha |
| `No se pudo abrir el puerto 5000` | Otra copia del panel en ejecución | Cierra la anterior o usa `--puerto 5001` |
| El equipo aparece dos veces | Se cambió el hostname | Es el comportamiento esperado (clave natural) |

## 6. Varios equipos

* No hay límite práctico: SQLite y el servidor de desarrollo de Flask aguantan
  decenas de equipos reportando cada 5 minutos.
* Para más carga, ejecuta el panel con un servidor WSGI de producción
  (`waitress-serve --port=5000 app:app`) detrás de un proxy.
* Programa el agente con el **Programador de tareas** si quieres que arranque
  solo. La tarea es visible en el sistema y el agente sigue mostrando su ventana.

## 7. Cambiar la contraseña

**Ajustes → Seguridad** → contraseña actual, nueva y repetición. La sesión dura
8 horas; los demás accesos caducan solos.
