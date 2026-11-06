@echo off
setlocal
cd /d "%~dp0.."

echo ============================================
echo  Dependencias del panel Unidad 17
echo ============================================
python -m pip install --upgrade pip
python -m pip install -r "servidor\requirements.txt"
if errorlevel 1 goto :error

echo.
echo Dependencias instaladas.
echo.
echo Opcional: GPS nativo de Windows para el agente
echo    python -m pip install winsdk
echo.
pause
exit /b 0

:error
echo.
echo [ERROR] No se pudieron instalar las dependencias.
echo Comprueba que Python esta en el PATH y que hay conexion a Internet.
pause
exit /b 1
