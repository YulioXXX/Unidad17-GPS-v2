# Render (gratis) + Supabase (gratis)

El panel corre en Render y **todos los datos viven en Supabase** (Postgres):
equipos, usuarios, tokens, historial, la clave de Google, e incluso los `.exe` de
actualización. Render puede reiniciar o suspender el servicio sin que se pierda
nada.

## 1. Supabase

1. Crea un proyecto (región cercana a la de Render). Anota la **contraseña de la
   base de datos** que eliges.
2. En el proyecto, botón **Connect** → cadena de conexión **Session pooler**
   (puerto 5432; es la compatible con IPv4, que es lo que normalmente necesita
   Render). Tiene esta forma:
   `postgresql://postgres.xxxx:[TU-CLAVE]@aws-0-xx.pooler.supabase.com:5432/postgres`
3. Sustituye `[TU-CLAVE]` por tu contraseña. Si tiene símbolos (`@ : / # ? %`)
   escríbelos codificados (`@` → `%40`, `:` → `%3A`, `/` → `%2F`…) o elige una
   contraseña solo con letras y números.

El panel crea sus tablas en un esquema propio llamado `unidad17`, no en `public`.
Si ya usas ese proyecto de Supabase para otra cosa, no se mezclan ni se pisan.

## 2. Pruébalo desde tu PC (2 minutos, recomendado)

No pude probar el código contra un Postgres real, así que antes de desplegar
comprueba que funciona con tu base:

```bash
pip install flask "psycopg[binary]"
python herramientas/probar_postgres.py "postgresql://postgres.xxxx:CLAVE@aws-0-xx.pooler.supabase.com:5432/postgres"
```

Crea un esquema temporal, recorre las operaciones del panel y lo borra. Debe
terminar con `RESULTADO: TODO OK`. Si algo falla, copia el mensaje (sin la
contraseña) y me lo pasas.

## 3. Render

1. Sube el proyecto a un repositorio privado de GitHub (el `.gitignore` ya excluye
   secretos y datos locales).
2. En Render: **New + → Blueprint** y elige el repositorio (lee `render.yaml`:
   plan gratis, Docker). Te pedirá dos valores:

   | Variable | Valor |
   |---|---|
   | `DATABASE_URL` | la cadena de Supabase del paso 1 |
   | `UNIDAD17_URL_PUBLICA` | `https://TU-SERVICIO.onrender.com` (la URL que te asigne; puedes ponerla después y redesplegar) |

   Render genera solo `UNIDAD17_CLAVE_API`, `UNIDAD17_CLAVE_SECRETA` y
   `UNIDAD17_CLAVE_ADMIN`. Son fijas: no cambian al reiniciar.
3. Cuando termine el despliegue, abre la URL y entra con usuario `admin` y como
   contraseña el valor de `UNIDAD17_CLAVE_ADMIN` (pestaña **Environment** del
   servicio). Te obligará a elegir otra.
4. En cada agente: `"url_servidor": "https://TU-SERVICIO.onrender.com"` y
   `"clave_agente"` = el valor de `UNIDAD17_CLAVE_API`.
5. Sigue `docs/08_SEGURIDAD.md` para las claves de firma de actualizaciones.

## Límites del plan gratis (qué esperar)

| Dónde | Límite | Efecto |
|---|---|---|
| Render | Se suspende tras 15 min sin tráfico y tarda ~1 min en despertar | Con agentes reportando cada 5 min casi nunca ocurre. Los reportes que fallen se guardan en la cola del agente y se reenvían. |
| Render | Puede reiniciar el servicio cuando quiera | No se pierde nada: los datos están en Supabase. |
| Supabase | Pausa el proyecto tras 7 días de inactividad | Con agentes escribiendo a diario no debería pasar. Si pasa, el panel no funciona hasta que pulses **Restore** en Supabase. Entra al menos una vez por semana si hay poca actividad. |
| Supabase | 500 MB de base, sin copias de seguridad automáticas | El panel borra solo el historial de más de 90 días (`historial_dias` en `config.json`; `0` lo desactiva) y los eventos de más de 180. Descarga el CSV de equipos de vez en cuando. |
| Panel | Los `.exe` de actualización se guardan en la base (máx. 80 MB cada uno) | Solo se conserva el último de agente y de panel. |

## Cuando haya ingresos (sin cambiar código)

* Render → plan **Starter**: no se suspende.
* Supabase → plan **Pro**: no se pausa y hace copias diarias.

## Si algo no arranca

Mira **Logs** en Render. Errores típicos: `DATABASE_URL` mal copiada o con la
clave sin codificar; usar la conexión directa (IPv6) en lugar de la del
**Session pooler**; proyecto de Supabase pausado. Con la base caída el panel
arranca igual y crea las tablas en la primera conexión que funcione.
