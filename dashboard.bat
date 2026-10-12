@echo off
rem ================================================================
rem  DatosActivos - abre el dashboard para comparar estrategias
rem  en el navegador (doble clic). Solo lee las bases de datos.
rem  Para cerrarlo, cierra esta ventana.
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

echo Comprobando que pandas, streamlit y plotly estan instalados...
%PY% -m pip install --quiet --disable-pip-version-check pandas streamlit plotly
if errorlevel 1 (
    echo No se pudieron instalar. Revisa tu conexion a internet.
    pause
    exit /b 1
)

echo Abriendo el dashboard en el navegador. Para cerrarlo, cierra esta ventana.
%PY% -m streamlit run codigo\dashboard.py --server.address localhost --server.showEmailPrompt false --browser.gatherUsageStats false %*
echo.
pause
