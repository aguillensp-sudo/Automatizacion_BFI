@echo off
REM ===========================================================================
REM  Compila "BFI Extractor.exe" a partir del codigo fuente.
REM
REM  Este script lo ejecuta el DESARROLLADOR. El usuario final no necesita nada
REM  de esto: recibe el instalador ya compilado.
REM
REM  Requisitos en el equipo de compilacion: Python 3.8 o superior con pip.
REM
REM  NOTA: fichero ASCII puro con finales CRLF a proposito (ver .gitattributes).
REM ===========================================================================
setlocal
cd /d "%~dp0"

echo.
echo === 1/4  Comprobando Python ============================================
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: no se encuentra Python en el PATH.
    echo Instalalo desde python.org marcando "Add python.exe to PATH".
    pause
    exit /b 1
)
python --version

echo.
echo === 2/4  Instalando dependencias =======================================
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo ERROR: fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo.
echo === 3/4  Generando el icono ============================================
python tools\crear_icono.py
if errorlevel 1 echo (aviso: se compilara sin icono propio)

echo.
echo === 4/4  Compilando con PyInstaller ====================================
python -m PyInstaller --noconfirm --clean "BFIExtractor.spec"
if errorlevel 1 (
    echo ERROR: fallo la compilacion.
    pause
    exit /b 1
)

echo.
echo ===========================================================================
echo  Listo.
echo.
echo  Aplicacion : dist\BFI Extractor\BFI Extractor.exe
echo  Instalador : ejecuta "crear_instalador.bat" para empaquetar todo en un
echo               unico "Instalar BFI Extractor.exe" para el usuario final.
echo ===========================================================================
pause