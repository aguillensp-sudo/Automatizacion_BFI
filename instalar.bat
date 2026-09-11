@echo off
REM ===========================================================================
REM  Instalador de BFI Extractor  -  se ejecuta solo, no pide nada al usuario.
REM
REM  Lo lanza el "Instalar BFI Extractor.exe" (autoextraible). Tambien se puede
REM  ejecutar a mano desde la carpeta descomprimida.
REM
REM  NO necesita permisos de administrador: todo se instala en el perfil del
REM  usuario (%%LOCALAPPDATA%%), igual que Chrome o VS Code. Asi el usuario de
REM  ofimatica no se topa con un aviso de UAC que no sabria interpretar.
REM
REM  NOTA: fichero ASCII puro con finales CRLF a proposito (ver .gitattributes).
REM ===========================================================================
setlocal EnableDelayedExpansion
set "ORIGEN=%~dp0"
set "DESTINO=%LOCALAPPDATA%\Programs\BFI Extractor"
set "NOMBRE=BFI Extractor"
set "EXE=BFI Extractor.exe"

title Instalando %NOMBRE%
echo.
echo ============================================================
echo   Instalando %NOMBRE%
echo ============================================================
echo.

REM --- 1. Cerrar la aplicacion si esta abierta -------------------------------
tasklist /FI "IMAGENAME eq %EXE%" 2>nul | find /I "%EXE%" >nul
if not errorlevel 1 (
    echo   La aplicacion esta abierta. Cerrandola para poder actualizarla...
    taskkill /IM "%EXE%" /F >nul 2>&1
    timeout /t 2 /nobreak >nul
)

REM --- 2. Copiar los ficheros ------------------------------------------------
echo   Copiando ficheros a:
echo     %DESTINO%
if not exist "%DESTINO%" mkdir "%DESTINO%" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   ERROR: no se pudo crear la carpeta de instalacion.
    echo   Comprueba que tienes permiso para escribir en tu propio perfil.
    echo.
    pause
    exit /b 1
)

xcopy "%ORIGEN%*" "%DESTINO%\" /E /I /Y /Q >nul
if errorlevel 1 (
    echo.
    echo   ERROR: fallo la copia de ficheros.
    echo   Si la aplicacion estaba abierta, cierrala y vuelve a intentarlo.
    echo.
    pause
    exit /b 1
)
echo   Ficheros copiados.

REM --- 3. Accesos directos ---------------------------------------------------
echo   Creando accesos directos...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$sh = New-Object -ComObject WScript.Shell; $exe = Join-Path $env:LOCALAPPDATA 'Programs\BFI Extractor\%EXE%'; $dir = Split-Path $exe; foreach ($r in @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'))) { if (Test-Path $r) { $l = $sh.CreateShortcut((Join-Path $r '%NOMBRE%.lnk')); $l.TargetPath = $exe; $l.WorkingDirectory = $dir; $l.IconLocation = $exe; $l.Description = 'Extraccion de extractos del Banco Financiero'; $l.Save() } }" >nul 2>&1
if errorlevel 1 (
    echo   (aviso: no se pudieron crear los accesos directos)
) else (
    echo   Accesos directos creados en el escritorio y en el menu Inicio.
)

REM --- 4. Desinstalador ------------------------------------------------------
> "%DESTINO%\Desinstalar BFI Extractor.bat" echo @echo off
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo echo Eliminando BFI Extractor...
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo del /q "%%USERPROFILE%%\Desktop\BFI Extractor.lnk" 2^>nul
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo del /q "%%APPDATA%%\Microsoft\Windows\Start Menu\Programs\BFI Extractor.lnk" 2^>nul
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo cd /d "%%TEMP%%"
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo rmdir /s /q "%DESTINO%"
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo echo Listo. La aplicacion se ha eliminado.
>>"%DESTINO%\Desinstalar BFI Extractor.bat" echo pause

REM --- 5. Credenciales de Ninox ---------------------------------------------
set "FALTAN="
for %%V in (NINOX_API_KEY NINOX_TEAM_ID NINOX_DB_ID) do (
    reg query "HKCU\Environment" /v %%V >nul 2>&1
    if errorlevel 1 set "FALTAN=!FALTAN! %%V"
)

echo.
echo ============================================================
if defined FALTAN (
    echo   INSTALACION TERMINADA, pero falta un paso:
    echo.
    echo   No hay credenciales de Ninox en este equipo:!FALTAN!
    echo.
    echo   Abre la aplicacion desde el escritorio y pulsa
    echo   "Configurar acceso a Ninox...". Pega ahi los tres datos
    echo   y pulsa Guardar. No hace falta saber nada de informatica.
) else (
    echo   INSTALACION TERMINADA correctamente.
    echo.
    echo   Ya puedes abrir la aplicacion desde el acceso directo
    echo   "BFI Extractor" del escritorio.
)
echo ============================================================
echo.

REM --- 6. Abrir la aplicacion ------------------------------------------------
if not defined FALTAN (
    start "" "%DESTINO%\%EXE%"
) else (
    choice /C SN /M "Abrir la aplicacion ahora para configurar el acceso"
    if errorlevel 2 goto fin
    start "" "%DESTINO%\%EXE%"
)
:fin
exit /b 0