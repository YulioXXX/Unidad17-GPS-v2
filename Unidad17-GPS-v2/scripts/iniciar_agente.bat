@echo off
setlocal
cd /d "%~dp0..\cliente"
if errorlevel 1 goto :error

echo Agente de ubicacion Unidad 17
echo Deja esta ventana abierta mientras el agente este activo.
echo.
python cliente.py
echo.
pause
exit /b 0

:error
echo No se encontro la carpeta cliente.
pause
exit /b 1
