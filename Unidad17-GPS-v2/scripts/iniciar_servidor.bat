@echo off
setlocal
cd /d "%~dp0..\servidor"
if errorlevel 1 goto :error

echo Iniciando panel Unidad 17...
echo.
python app.py
echo.
echo El panel se detuvo.
pause
exit /b 0

:error
echo No se encontro la carpeta servidor.
pause
exit /b 1
