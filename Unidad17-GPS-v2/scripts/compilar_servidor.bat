@echo off
setlocal
cd /d "%~dp0..\servidor"
if errorlevel 1 goto :error

echo ============================================
echo  Compilando panel (Unidad17-Panel.exe)
echo ============================================
python -m pip install --upgrade pyinstaller
if errorlevel 1 goto :error

python -m PyInstaller --noconfirm --clean --onefile --name Unidad17-Panel --add-data "templates;templates" --add-data "static;static" app.py
if errorlevel 1 goto :error

echo.
echo Listo: %CD%\dist\Unidad17-Panel.exe
echo Copia el .exe a una carpeta escribible (por ejemplo C:\Unidad17\).
pause
exit /b 0

:error
echo.
echo [ERROR] La compilacion fallo. Revisa los mensajes anteriores.
pause
exit /b 1
