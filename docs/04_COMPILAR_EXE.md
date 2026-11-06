# Compilar a .exe

## Requisitos

```bat
pip install pyinstaller
```

La primera vez descarga unos 10 MB. Comprueba con `pyinstaller --version`.

## Servidor (panel)

```bat
cd servidor
pyinstaller --noconfirm --clean --onefile --name Unidad17-Panel ^
  --add-data "templates;templates" ^
  --add-data "static;static" ^
  app.py
```

Resultado: `servidor\dist\Unidad17-Panel.exe` (unos 12–18 MB).

Puedes usar el script `scripts\compilar_servidor.bat`, que hace lo mismo y deja
el resultado en la misma carpeta.

### Dónde guarda los datos el .exe

Junto al ejecutable:

```
Unidad17-Panel.exe
config.json          (se crea solo)
datos\unidad17.db
servidor.log
```

Por eso conviene colocar el `.exe` en una carpeta escribible, por ejemplo
`C:\Unidad17\`, y no en `Archivos de programa` (requiere permisos de
administrador para escribir al lado del ejecutable).

### Ejecutarlo

Doble clic. Se abre la consola con la URL, la clave de agentes y el navegador.

Opciones:

```bat
Unidad17-Panel.exe --puerto 8080 --sin-navegador
```

## Agente (cliente)

```bat
cd cliente
pyinstaller --noconfirm --clean --onefile --name Unidad17-Agente ^
  --exclude-module winsdk --exclude-module tkinter ^
  cliente.py
```

Resultado: `cliente\dist\Unidad17-Agente.exe` (unos 7–12 MB).

> **Importante:** el agente se compila **con consola**. Es una decisión de
> transparencia: la persona que usa el equipo debe poder ver que el agente está
> activo. No añadas `--noconsole`.

### Incluir el GPS de Windows (opcional)

```bat
pip install winsdk
pyinstaller --noconfirm --clean --onefile --name Unidad17-Agente ^
  --collect-all winsdk --exclude-module tkinter ^
  cliente.py
```

El `.exe` crece bastante (winsdk incluye proyecciones de WinRT). Sin winsdk el
agente sigue funcionando con el GPS vía .NET y la ubicación por IP.

### Distribuir el agente

Copia junto al `.exe`:

```
Unidad17-Agente.exe
config.json
```

`config.json` debe tener la URL del servidor y la clave de agente. La primera vez
se crea uno vacío; edítalo o distribúyelo ya configurado.

## Falsos positivos del antivirus

Los ejecutables generados con PyInstaller a veces se marcan como sospechosos.
Es un comportamiento conocido del empaquetado, no un virus. Opciones:

* Firmar el ejecutable con un certificado de código.
* Añadir una exclusión en Windows Defender para la carpeta del agente.
* Distribuir desde una ruta de red de confianza.
* Compilar en la misma organización que lo va a usar.

No intentes evitar el antivirus: si el agente es legítimo, debe poder
inspeccionarse.

## Si aparece "Could not create temporary directory"

El modo `--onefile` se descomprime en `%TEMP%` al arrancar. Algunas políticas de
seguridad (antivirus, AppLocker, cuentas restringidas) bloquean esa extracción y
el programa no llega a iniciar.

Soluciones, en orden de preferencia:

1. Copiar el `.exe` a una carpeta local escribible (`C:\Unidad17\`) en lugar de
   una carpeta de red o de descargas.
2. Compilar en modo carpeta:

```bat
pyinstaller --noconfirm --clean --onedir --name Unidad17-Panel ^
  --add-data "templates;templates" --add-data "static;static" app.py
```

Se genera `dist\Unidad17-Panel\` con el `.exe` y una carpeta `_internal`.
Distribuye la carpeta completa; arranca más rápido y no usa `%TEMP%`.

## Probar el .exe

1. Ejecuta `Unidad17-Panel.exe`, entra al panel y copia la clave.
2. En otro equipo (o en otra carpeta), ejecuta `Unidad17-Agente.exe --diagnostico`.
3. Ajusta `config.json` y ejecuta el agente.
4. Comprueba que el equipo aparece en el panel.

## Notas técnicas

* `--onefile` descomprime en `%TEMP%` al arrancar: el primer inicio tarda 1–3 s.
  Si necesitas arranque inmediato, usa `--onedir` y distribuye la carpeta.
* El servidor usa el servidor de desarrollo de Flask. Para producción, usa
  `waitress` detrás de un proxy:

```bat
pip install waitress
waitress-serve --port=5000 app:app
```

* Las plantillas y los estáticos se resuelven con `sys._MEIPASS` cuando el
  programa está congelado; no muevas los archivos internos del `.exe`.
