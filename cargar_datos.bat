@echo off
rem ================================================================
rem  DatosActivos - carga o amplia la base de datos (doble clic)
rem  Admite los mismos parametros que cargar_datos.py, por ejemplo:
rem     cargar_datos.bat --simbolo ETHUSDT
rem ================================================================
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (set "PY=py -3") else (set "PY=python")

%PY% --version >nul 2>nul
if errorlevel 1 (
    echo No se ha encontrado Python.
    echo Instalalo desde https://www.python.org/downloads/ marcando "Add python.exe to PATH"
    echo y vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

echo Comprobando que pandas esta instalado...
%PY% -m pip install --quiet --disable-pip-version-check pandas
if errorlevel 1 (
    echo No se pudo instalar pandas. Revisa tu conexion a internet.
    pause
    exit /b 1
)

%PY% codigo\cargar_datos.py %*
echo.
pause
