# Seguridad (v1.0.11)

Esta versión cambia tres cosas: **token propio por equipo**, **cambio obligatorio
de la contraseña inicial** y **actualizaciones firmadas**.

## 1. Token por equipo

Antes todos los agentes compartían una sola clave. Si se filtraba en un equipo,
servía para falsificar reportes de cualquiera y para leer la clave de Google.

Ahora:

1. El agente presenta la **clave de enrolamiento** (la de Ajustes) **una sola vez**
   a `POST /api/registrar` y recibe un **token único**.
2. El token se guarda en `.token_equipo`, junto al agente. A partir de ahí el
   agente envía solo `X-Token-Equipo`; la clave compartida deja de viajar.
3. El panel guarda únicamente el SHA-256 del token. Un token solo vale para el
   `hostname` al que se entregó.
4. Desde la ficha del equipo puedes **Revocar acceso** (deja de reportar y no puede
   volver a enrolarse) o **Permitir re-enrolamiento** (por ejemplo, si se
   reinstaló el agente y perdió su token: lo pedirá solo en el siguiente ciclo).

Estados de un equipo: `sin token` → `activo` → `revocado` / `reenrolar`.

Si un token falla, el agente reintenta enrolarse como máximo cada 15 minutos.

### Clave global (compatibilidad)

Los agentes 1.0.10 no conocen los tokens y siguen reportando con la clave
compartida. Por eso:

* **Instalación nueva** (sin equipos): la clave global NO sirve para reportar.
* **Instalación existente**: queda activa hasta que la desactives en
  **Ajustes → Autenticación de agentes**. Ese panel te dice cuántos equipos
  siguen sin token.
* Aunque esté activa, un equipo que ya tiene token (o está revocado) **no puede**
  reportar con la clave global: nadie puede suplantarlo ni saltarse una revocación.

Los intentos con credenciales inválidas se limitan por IP (6 en 5 minutos; luego
`429`). Los agentes válidos no se ven afectados.

### Endpoints nuevos o cambiados

| Ruta | Credencial | Notas |
|---|---|---|
| `POST /api/registrar` | `X-Clave-Agente` | Body `{"hostname": "..."}` → `{"token": "..."}`. `409` si ya tiene token, `403` si está revocado. |
| `POST /api/report` | `X-Token-Equipo` (o clave global si está permitida) | `403` si el hostname no coincide con el token. |
| `GET /api/config` | `X-Token-Equipo` (o clave global si está permitida) | |
| `POST /equipo/<id>/token` | sesión + CSRF | `accion=revocar` o `accion=reenrolar`. |

## 2. Contraseña inicial

* La cuenta creada automáticamente (`admin` / `unidad17`) obliga a definir una
  contraseña nueva en el primer acceso; hasta entonces solo se puede cambiarla o
  cerrar sesión.
* En instalaciones existentes, quien siga con la contraseña de fábrica (o la de
  `config.json`) la tendrá que cambiar en su próximo acceso.
* Mínimo 8 caracteres; se rechazan `unidad17`, `admin` y similares.
* Si publicas el panel por HTTPS, pon `"cookie_segura": true` en el `config.json`
  del servidor para que la cookie de sesión solo viaje cifrada.

## 3. Actualizaciones firmadas (Ed25519)

El SHA-256 del manifiesto lo publica el propio servidor, así que no protege si el
servidor se compromete. La firma sí: se hace **fuera** del servidor con una clave
privada que solo tú tienes, y los agentes la verifican con la clave pública.

La firma cubre **componente + versión + SHA-256 + tamaño**, así que no sirve para
otro archivo, otra versión ni el otro componente.

### Puesta en marcha (una sola vez)

```bat
cd herramientas
python firmar_paquete.py claves
```

Crea `firma_privada.key` (**secreta**: guárdala fuera del servidor y haz copia de
seguridad) y `firma_publica.txt`.

1. Pega la clave pública en `cliente/firma_publica.py` (`CLAVE_PUBLICA_HEX`).
   Alternativa sin recompilar: ponla en `config.json` del agente como
   `clave_publica_firma`.
2. Pégala también en el panel: **Ajustes → Firma de actualizaciones**. Desde ese
   momento el panel rechaza cualquier paquete sin firma válida.

### Publicar cada versión

```bat
scripts\compilar_agente.bat
cd herramientas
python firmar_paquete.py firmar --tipo agente --version 1.0.12 ..\cliente\dist\Unidad17-Agente.exe
```

Genera `Unidad17-Agente.exe.firma`. En **Actualizaciones → Publicar una versión**
sube el `.exe` y su `.firma`. (Para el panel usa `--tipo panel`.)

Comprobar una firma: `python firmar_paquete.py verificar --tipo agente --version 1.0.12 Unidad17-Agente.exe`

### Qué hace el agente

Comprueba la firma **antes de descargar**; si no es válida, no instala nada y lo
deja en `agente.log`. Sin clave pública en ningún sitio, **no se actualiza solo**
(salvo `"permitir_sin_firma": true`, no recomendado).

## Cómo pasar de la 1.0.10 a la 1.0.11

1. Copia los archivos de este parche sobre tu proyecto.
2. Genera las claves de firma y pega la pública en `cliente/firma_publica.py`.
3. Recompila **servidor** y **agente** (la versión ya es 1.0.11).
4. Arranca el panel nuevo. Entra con tu usuario: te pedirá cambiar la contraseña.
5. Ajustes → Firma de actualizaciones → pega la clave pública.
6. Firma el agente 1.0.11 y publícalo (`.exe` + `.firma`).
7. Los agentes 1.0.10 se actualizarán solos. **Esta primera actualización se
   acepta solo por SHA-256**, porque la 1.0.10 todavía no verifica firmas; a partir
   de la 1.0.11 todo se verifica.
8. Los agentes 1.0.11 se enrolan solos. Cuando Ajustes indique que ningún equipo
   queda sin token, pulsa **Desactivar la clave global para reportar**.

## Lo que esto NO resuelve

* **HTTP en texto plano.** Si el panel va por HTTP, el token (y la clave de Google)
  pueden verse en la red. Usa HTTPS (`docs/06_DESPLIEGUE.md`, Caddy).
* **El token vive en un archivo** (`.token_equipo`) sin cifrar, como la clave anterior
  vivía en `config.json`. Quien tenga acceso de administrador al equipo puede leerlo.
* **Firma de código de Windows**: los `.exe` siguen sin firmar para SmartScreen y
  pueden dar falsos positivos en antivirus. La firma de este documento es otra cosa.
* **Perder la clave privada**: tendrías que recompilar y reinstalar a mano los
  agentes con una clave nueva.
