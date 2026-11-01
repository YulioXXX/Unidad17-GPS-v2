# Despliegue con Docker (cualquier servidor Linux)

Sirve en cualquier VPS (Ubuntu/Debian) con Docker. Incluye HTTPS automático con
Caddy. Necesitas: un servidor con IP pública, un **dominio** apuntando a esa IP
(registro A) y los puertos **80 y 443** abiertos.

## 1. Instalar Docker (una vez)

```bash
curl -fsSL https://get.docker.com | sudo sh
```

## 2. Subir el proyecto

Desde tu PC (solo hace falta la carpeta del proyecto con el parche aplicado;
`cliente/` y `scripts/` no se usan en el servidor):

```bash
scp -r Unidad17-GPS-v2 usuario@IP_DEL_SERVIDOR:~/
```

## 3. Configurar y arrancar

```bash
cd ~/Unidad17-GPS-v2
cp .env.ejemplo .env && nano .env       # DOMINIO, URL_PUBLICA
sudo docker compose up -d --build
sudo docker compose logs -f app         # Ctrl+C para salir
```

Abre `https://tu-dominio`. Entra con `admin` / `unidad17`: te obligará a cambiar
la contraseña.

> **Probar sin dominio** (solo para una prueba): pon `DOMINIO=:80`,
> `URL_PUBLICA=http://IP_DEL_SERVIDOR` y `COOKIE_SEGURA=0`. Funciona por HTTP, sin
> cifrar: no lo dejes así en producción.

## 4. Configurar los agentes

La clave de enrolamiento está en Ajustes del panel (o con
`sudo docker compose exec app cat /data/config.json`). En el `config.json` de
cada agente:

```json
{ "url_servidor": "https://tu-dominio", "clave_agente": "U17-..." }
```

Después sigue `docs/08_SEGURIDAD.md` (claves de firma, publicar el agente).

## Operación

| Tarea | Comando |
|---|---|
| Ver estado | `sudo docker compose ps` |
| Actualizar el panel | sube los archivos nuevos y `sudo docker compose up -d --build` |
| Reiniciar | `sudo docker compose restart app` |
| Copia de seguridad | `sudo docker compose exec app python -c "import sqlite3;sqlite3.connect('/data/datos/unidad17.db').execute(\"VACUUM INTO '/data/copia.db'\")"` y luego `sudo docker compose cp app:/data/copia.db .` |
| Limpieza del historial | `sudo docker compose exec app python mantenimiento.py --dias 90` |

Los datos (base, `config.json`, paquetes de actualización) viven en el volumen
`unidad17_data` y sobreviven a reconstruir la imagen. Haz copias periódicas de
`config.json` y la base: si pierdes `config.json` se genera otra clave de
enrolamiento.

## Notas

* El panel corre con **un solo proceso** (8 hilos) a propósito: el límite de
  intentos fallidos vive en memoria. Sobra para cientos de equipos.
* El puerto 5000 del contenedor no se publica; solo Caddy llega a él.
* `UNIDAD17_PROXY=1` hace que el panel confíe en la IP que informa Caddy. No lo
  actives si expones el puerto del panel directamente a Internet.
* Los paquetes `.exe` se suben desde el panel (Actualizaciones), no se incluyen
  en la imagen.
