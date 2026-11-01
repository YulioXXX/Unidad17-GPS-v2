# Despliegue en Render (sin servidor propio)

> **Sin presupuesto por ahora:** usa Render gratis con la base de datos en Supabase,
> en `docs/11_RENDER_SUPABASE.md`. Esta guía es la variante con plan Starter + disco.

Render ejecuta el `Dockerfile` del proyecto y ya da HTTPS y un dominio
`https://algo.onrender.com`. No necesitas Caddy ni `docker-compose.yml`.

## Importante: el plan gratis NO sirve para usarlo de verdad

Según la documentación de Render, un servicio gratuito:

* tiene el **sistema de archivos efímero**: se pierde todo lo que escribe (incluida
  una base SQLite) en cada reinicio, despliegue o suspensión; los **discos
  persistentes solo existen en servicios de pago**;
* se **suspende tras 15 minutos sin tráfico** y tarda cerca de un minuto en volver;
* Render puede reiniciarlo cuando quiera.

Este panel guarda en disco la base de datos, la clave de enrolamiento y los
paquetes de actualización, así que en el plan gratis perderías equipos, usuarios y
tokens en cualquier reinicio. Úsalo, como mucho, para ver cómo se ve.

Para uso real: **plan Starter (desde unos 7 USD/mes) + un disco persistente
de 1 GB** (se cobra aparte; mira el precio en la página de Render).

## Pasos

1. Sube el proyecto a un repositorio de GitHub (privado). El archivo
   `.gitignore` de `herramientas/` ya evita subir la clave privada de firma; **no
   subas nunca `firma_privada.key`** ni `servidor/config.json`.
2. En Render: **New + → Blueprint**, elige el repositorio. Lee `render.yaml`
   (servicio Docker, plan Starter, disco de 1 GB en `/data`).
   Sin Blueprint: **New + → Web Service**, runtime *Docker*, plan Starter, añade un
   *Disk* con *Mount Path* `/data`, y las variables de abajo.
3. Variables de entorno:

   | Variable | Valor |
   |---|---|
   | `UNIDAD17_PROXY` | `1` |
   | `UNIDAD17_COOKIE_SEGURA` | `1` |
   | `UNIDAD17_URL_PUBLICA` | la URL que te asigne Render, con `https://` |

   (La URL la conoces tras el primer despliegue: añádela y vuelve a desplegar.)
4. Abre la URL: entra con `admin` / `unidad17` y cambia la contraseña.
5. La clave de enrolamiento está en Ajustes. En cada agente:
   `"url_servidor": "https://TU-SERVICIO.onrender.com"`.
6. Sigue `docs/08_SEGURIDAD.md` para las claves de firma.

## Copias de seguridad

Render no hace copia automática de tu base. Descarga de vez en cuando la base y
`config.json` (Shell del servicio → `cat /data/config.json`, o *Disk snapshots*
si tu plan los incluye). Sin `config.json` se genera otra clave de enrolamiento y
los agentes tendrían que volver a enrolarse.

## Alternativas

Si prefieres un servidor tradicional, un VPS pequeño de pocos dólares al mes con
`docs/09_DESPLIEGUE_DOCKER.md` te da lo mismo con más control. Cualquier opción
funciona mientras tenga **disco que persista** y no se suspenda.
