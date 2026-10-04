@echo off
REM ---------------------------------------------------------------------------
REM  Registra la tarea semanal del agente de correo (lunes a las 11:00).
REM
REM  IMPORTANTE: la tarea se crea con /IT ("ejecutar solo cuando el usuario haya
REM  iniciado sesion"). No es un capricho: Outlook por COM necesita una sesion
REM  interactiva de Windows con el perfil de correo abierto. Si se ejecuta como
REM  SYSTEM, o con "ejecutar tanto si el usuario inicio sesion como si no", el
REM  agente NO puede hablar con Outlook.
REM
REM  El modo de la ejecucion esta en ejecutar_agente.cmd: hoy --real (inserta en
REM  Ninox y responde al remitente). Ponlo en --dry-run para una pasada de
REM  comprobacion.
REM ---------------------------------------------------------------------------
setlocal

set TAREA=BFI Agente de correo
set DIA=MON
set HORA=11:00
set RAIZ=%~dp0

echo.
echo   Tarea ......... %TAREA%
echo   Cuando ........ todos los %DIA% a las %HORA%
echo   Ejecuta ....... %RAIZ%ejecutar_agente.cmd
echo.
echo   El modo (--dry-run o --real) se configura dentro de ejecutar_agente.cmd.
echo.

schtasks /create /tn "%TAREA%" /tr "\"%RAIZ%ejecutar_agente.cmd\"" /sc weekly /d %DIA% /st %HORA% /it /f
if errorlevel 1 (
    echo.
    echo   ERROR: no se pudo crear la tarea.
    echo   Prueba a ejecutar este fichero con el boton derecho, "Ejecutar como administrador".
    echo.
    pause
    exit /b 1
)

echo.
echo   Tarea creada.
echo.
echo   Comprobar:   schtasks /query /tn "%TAREA%" /v /fo LIST
echo   Ejecutar ya: schtasks /run   /tn "%TAREA%"
echo   Quitar:      schtasks /delete /tn "%TAREA%" /f
echo.
echo   Recuerda que el equipo debe tener la sesion iniciada a esa hora.
echo.
pause
