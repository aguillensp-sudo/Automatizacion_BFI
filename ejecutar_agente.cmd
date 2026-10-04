@echo off
REM ---------------------------------------------------------------------------
REM  Ejecuta el agente de correo una vez.
REM
REM  Se puede llamar a mano o desde el Programador de tareas (lo hace
REM  programar_agente.bat).
REM
REM  MODO:
REM    --real     procesa los correos, inserta en Ninox (base de PRODUCCION,
REM               la que indique NINOX_DB_ID) y responde al remitente.
REM    --dry-run  ensayo: no escribe en Ninox, no responde y no marca nada.
REM
REM  Se puede forzar otro modo pasandolo como primer argumento:
REM    ejecutar_agente.cmd --dry-run
REM ---------------------------------------------------------------------------
setlocal

set MODO=--real
if not "%~1"=="" set MODO=%~1

set RAIZ=%~dp0
cd /d "%RAIZ%"

REM  Interprete de Python. No se usa "python" a secas porque en este equipo
REM  resuelve al alias de la Microsoft Store (WindowsApps\python.exe, 0 bytes),
REM  que depende de una opcion de Windows y puede no estar disponible en la
REM  sesion de la tarea programada. Se busca el interprete real y, si no
REM  aparece, se cae al PATH como ultimo recurso.
set PYTHON=python
for /d %%D in ("%LOCALAPPDATA%\Python\pythoncore-*") do if exist "%%~fD\python.exe" set PYTHON=%%~fD\python.exe

if not exist "logs" mkdir "logs"

echo.>> "logs\agente_tarea.log"
echo ===== %DATE% %TIME%  %MODO% =====>> "logs\agente_tarea.log"
echo Interprete: %PYTHON%>> "logs\agente_tarea.log"

"%PYTHON%" -m bfi_agente %MODO% >> "logs\agente_tarea.log" 2>&1
set CODIGO=%ERRORLEVEL%

echo Codigo de salida: %CODIGO%>> "logs\agente_tarea.log"
exit /b %CODIGO%
