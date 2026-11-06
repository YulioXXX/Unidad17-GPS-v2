# Despliegue en un servidor

El panel puede funcionar de dos formas:

* **Windows**: `Unidad17-Panel.exe` (incluido en `servidor/dist/`).
* **Linux**: el código con Gunicorn detrás de Caddy/Nginx (HTTPS).

En ambos casos la base de datos y `config.json` viven junto al programa; haz
copias periódicas.

---

## Opción A · Windows (recomendada si ya usas el .exe)

1. Crea una carpeta escribible, por ejemplo `C:\Unidad17\`, y copia allí
   `Unidad17-Panel.exe`.
2. Ejecútalo. Se crea `config.json`, `datos\unidad17.db` y `servidor.log`.
3. Abre el panel, cambia la contraseña y configura la clave de Google en
   **Ajustes → Google Geolocation**.
4. Permite el puerto en el firewall:

```powershell
New-NetFirewallRule -DisplayName "Unidad17 Panel" -Direction Inbound `
  -Protocol TCP -LocalPort 5000 -Action Allow -Profile Private
```

5. Arranque automático: crea una tarea en el **Programador de tareas** al inicio
   del sistema, o usa [NSSM](https://nssm.cc/) como servicio.

### HTTPS en Windows

Lo más simple es poner **Caddy** delante del panel:

```caddyfile
panel.tudominio.com {
    reverse_proxy 127.0.0.1:5000
}
```

Caddy obtiene y renueva el certificado solo. El panel debe escuchar en
`127.0.0.1` (en `config.json`, `"host": "127.0.0.1"`) y el firewall solo debe
exponer 80/443. Si no tienes dominio, puedes usar la IP y HTTP dentro de la LAN.

> Con HTTPS, edita `config.json` y pon `"url_publica": "https://panel.tudominio.com"`
> para que el manifiesto de actualizaciones entregue URLs correctas a los agentes.

---

## Opción B · Linux (Ubuntu/Debian)

### 1. Usuario y carpetas

```bash
sudo useradd --system --home /opt/unidad17 --shell /usr/sbin/nologin unidad17
sudo mkdir -p /opt/unidad17
sudo chown -R unidad17: /opt/unidad17
```

Copia el proyecto (carpeta `servidor/`, `cliente/` no hace falta en el servidor)
a `/opt/unidad17/`.

### 2. Entorno y dependencias

```bash
sudo apt update && sudo apt install -y python3-venv unzip caddy
sudo -u unidad17 python3 -m venv /opt/unidad17/venv
sudo -u unidad17 /opt/unidad17/venv/bin/pip install -r /opt/unidad17/servidor/requirements-produccion.txt
```

### 3. Servicio systemd

```bash
sudo cp /opt/unidad17/servidor/deploy/unidad17.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now unidad17
sudo systemctl status unidad17
```

El servicio escucha en `127.0.0.1:5000`. Ajusta `User`, `WorkingDirectory` y el
puerto si tu instalación es distinta.

### 4. HTTPS con Caddy

```bash
sudo cp /opt/unidad17/servidor/deploy/Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile      # pon tu dominio
sudo systemctl reload caddy
```

Caddy gestiona el certificado con Let's Encrypt. El firewall solo necesita
80/443:

```bash
sudo ufw allow 80,443/tcp
```

### 5. Configuración

`/opt/unidad17/servidor/config.json`:

```json
{
  "host": "127.0.0.1",
  "puerto": 5000,
  "abrir_navegador": false,
  "url_publica": "https://panel.tudominio.com"
}
```

Reinicia: `sudo systemctl restart unidad17`.

---

## Agentes

En cada equipo, `config.json` debe apuntar a la URL pública (o a la IP de la LAN):

```json
{
  "url_servidor": "https://panel.tudominio.com",
  "clave_agente": "U17-...",
  "auto_actualizar": true
}
```

Si usas HTTPS, el certificado debe ser válido: el agente usa la librería TLS de
Python y rechaza certificados no confiables.

---

## Copias de seguridad

```bash
# Linux (con el servicio detenido o en caliente con sqlite3)
sqlite3 /opt/unidad17/servidor/datos/unidad17.db ".backup '/backup/unidad17-$(date +%F).db'"
sudo tar czf /backup/unidad17-$(date +%F).tar.gz -C /opt/unidad17 servidor/config.json servidor/datos
```

En Windows, copia la carpeta `datos` y `config.json` cuando el panel esté
detenido, o usa la copia en caliente de SQLite.

---

## Lista de verificación

- [ ] El panel responde en la URL pública con HTTPS válido.
- [ ] `config.json` tiene `url_publica` correcta.
- [ ] Firewall: solo 80/443 expuestos; 5000 cerrado al exterior.
- [ ] Contraseña del panel cambiada.
- [ ] Clave de Google configurada en Ajustes.
- [ ] Copia de seguridad programada.
- [ ] Un equipo de prueba reporta y aparece en el panel.
- [ ] El manifiesto `/api/version` devuelve URLs con el dominio correcto.
