@echo off
setlocal
cd /d "%~dp0..\cliente"
if errorlevel 1 goto :error

echo ============================================
echo  Compilando agente (Unidad17-Agente.exe)
echo ============================================
echo  El agente se compila CON consola: debe ser
echo  visible para la persona que usa el equipo.
echo ============================================
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error

python -m PyInstaller --noconfirm --clean --onefile --name Unidad17-Agente --exclude-module winsdk --exclude-module tkinter cliente.py
if errorlevel 1 goto :error

echo.
echo Listo: %CD%\dist\Unidad17-Agente.exe
echo Copia junto al .exe el archivo config.json ya configurado.
pause
exit /b 0

:error
echo.
echo [ERROR] La compilacion fallo. Revisa los mensajes anteriores.
pause
exit /b 1
