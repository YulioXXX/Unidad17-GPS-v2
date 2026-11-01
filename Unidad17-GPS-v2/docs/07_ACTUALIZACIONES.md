# Actualizaciones automáticas

El panel publica paquetes y los agentes se actualizan solos, sin avisos al
usuario. Todo se verifica con **SHA-256** antes de tocar el ejecutable.

## Cómo funciona

```
Panel (Ajustes → Actualizaciones)
  └─ sube Unidad17-Agente-1.0.11.exe
       ├─ calcula SHA-256 y tamaño
       ├─ guarda en servidor/actualizaciones/
       └─ publica en actualizaciones/versiones.json

Agente
  ├─ consulta GET /api/version al arrancar y cada 6 h
  ├─ compara versión con la suya
  ├─ descarga el .exe publicado
  ├─ verifica SHA-256 y tamaño
  ├─ escribe _actualizar_agente.bat
  ├─ termina y el .bat reemplaza el .exe (guarda .bak) y lo reinicia
  └─ si algo falla, sigue funcionando con la versión anterior
```

El agente **no** se actualiza si el SHA-256 no coincide, si el archivo está
incompleto o si no puede escribir en su carpeta (por ejemplo, en
`Archivos de programa`). En ese caso lo deja anotado en `agente.log`.

## Manifiesto

`GET /api/version` (público) devuelve:

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
    "url": "https://panel.tudominio.com/actualizaciones/descargar/Unidad17-Agente-1.0.11.exe"
  },
  "panel": { "...": "..." }
}
```

`url_publica` en `config.json` controla el dominio de las URLs. Sin dominio se
usa la URL con la que el agente consultó el manifiesto.

## Publicar una versión

1. Compila el nuevo `.exe` (agente o panel).
2. Entra en **Actualizaciones**.
3. Elige componente, escribe la versión (`1.0.11`), adjunta el archivo y pulsa
   **Publicar versión**.
4. Para el panel, marca *“reiniciarlo al publicar”* y se actualiza solo.

El panel muestra el SHA-256 y el tamaño calculados. No se puede publicar dos
veces el mismo nombre sin subir el archivo de nuevo (se sobrescribe el paquete
de esa versión).

## Panel en Windows (.exe)

El panel no puede sobrescribir su propio ejecutable mientras corre. Al publicar:

1. Se lanza `_actualizar_panel.bat` en segundo plano.
2. El panel actual responde “Actualizando…” y termina.
3. El `.bat` espera a que el proceso muera, guarda `Unidad17-Panel.exe.bak`,
   copia el nuevo y lo arranca con los mismos argumentos.
4. `config.json`, `datos/` y `actualizaciones/` no se tocan.

Si el nuevo ejecutable no arranca, renombra `Unidad17-Panel.exe.bak` a
`Unidad17-Panel.exe` y vuelve a iniciar.

## Panel en Linux

El panel desde código no puede reiniciarse solo sin privilegios. El flujo es:

1. Publica el paquete `.zip` del panel en **Actualizaciones**.
2. Descárgalo y ejecuta en el servidor:

```bash
sudo /opt/unidad17/servidor/deploy/actualizar.sh /tmp/Unidad17-Panel-1.0.11.zip /opt/unidad17/servidor
```

El script conserva `config.json`, `datos/` y `actualizaciones/`, y reinicia el
servicio `unidad17`. Para que sea automático, programa ese comando con un
`systemd.path` o ejecútalo desde tu proceso de despliegue.

## Reversión

* Agente: el `.bat` deja `Unidad17-Agente.exe.bak`. Detén el agente, renombra el
  `.bak` y vuelve a iniciarlo.
* Panel: igual con `Unidad17-Panel.exe.bak`.

## Problemas frecuentes

| Síntoma | Causa | Solución |
|---|---|---|
| El agente no se actualiza | El SHA no coincide o el archivo se cortó | Vuelve a publicar el paquete |
| `El SHA-256 no coincide` | Publicaste otro archivo con la misma versión | Sube el `.exe` correcto |
| No reemplaza el `.exe` | Carpeta sin permisos de escritura | Mueve el agente a una carpeta del usuario |
| El panel no reinicia | No está compilado como `.exe` | Usa el `.exe` o el script de Linux |
| El panel queda en “Actualizando…” | Antivirus bloqueó el `.bat` | Revisa el `.bak` y ejecuta el `.exe` a mano |

## Compatibilidad

* Los agentes 1.0.x siguen reportando contra el panel 1.0.10; el endpoint
  `/api/report` no cambió.
* Los campos nuevos (`fuente: "wifi"`) son ignorados por paneles antiguos.
* Las migraciones de base de datos son aditivas (no borran datos).
