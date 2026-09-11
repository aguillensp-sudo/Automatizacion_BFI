@echo off
REM ===========================================================================
REM  Crea "Instalar BFI Extractor.exe": TODO el programa en un unico fichero.
REM
REM  Lo ejecuta el DESARROLLADOR, despues de "build_exe.bat". El resultado se
REM  copia a un pendrive o se envia por correo; el usuario final solo tiene que
REM  hacer doble clic.
REM
REM  Tecnica: un .exe autoextraible SFX de 7-Zip con un config.txt que indica
REM  que hay que lanzar "instalar.bat". Es la forma estandar de empaquetar una
REM  aplicacion de Windows sin depender de Inno Setup ni de WiX.
REM
REM  NOTA IMPORTANTE: este fichero es ASCII puro y con finales de linea CRLF a
REM  proposito. Con finales LF, cmd.exe se comporta de forma impredecible: se
REM  comio la primera letra de cada linea y el script dejo de funcionar. Hay un
REM  .gitattributes que fuerza CRLF en git; si lo editas a mano, mantenlo.
REM ===========================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "APP=dist\BFI Extractor"
set "PAQUETE=dist\BFI-Extractor-payload.7z"
set "SALIDA=Instalar BFI Extractor.exe"

echo.
echo === Comprobaciones previas =============================================
if not exist "%APP%\BFI Extractor.exe" (
    echo ERROR: no existe "%APP%\BFI Extractor.exe".
    echo Ejecuta antes "build_exe.bat".
    pause
    exit /b 1
)

set "SFX="
if exist "%ProgramFiles%\7-Zip\7z.sfx" set "SFX=%ProgramFiles%\7-Zip\7z.sfx"
if not defined SFX if exist "%ProgramFiles(x86)%\7-Zip\7z.sfx" set "SFX=%ProgramFiles(x86)%\7-Zip\7z.sfx"
if not defined SFX (
    echo ERROR: no se encuentra 7z.sfx. Instala 7-Zip desde 7-zip.org.
    pause
    exit /b 1
)
echo   SFX de 7-Zip : !SFX!

set "SZ="
if exist "%ProgramFiles%\7-Zip\7z.exe" set "SZ=%ProgramFiles%\7-Zip\7z.exe"
if not defined SZ if exist "%ProgramFiles(x86)%\7-Zip\7z.exe" set "SZ=%ProgramFiles(x86)%\7-Zip\7z.exe"
if not defined SZ for /f "delims=" %%i in ('where 7z 2^>nul') do if not defined SZ set "SZ=%%i"
if not defined SZ (
    echo ERROR: no se encuentra 7z.exe. Instala 7-Zip desde 7-zip.org.
    pause
    exit /b 1
)
echo   7z.exe       : !SZ!

echo.
echo === Empaquetando la aplicacion =========================================
if exist "%PAQUETE%" del /q "%PAQUETE%"
REM Se comprime DESDE DENTRO de la carpeta de la aplicacion y con el comodin
REM "*": asi la ruta relativa "..\..." es siempre de un solo nivel. Con una ruta
REM larga (".dist\BFI Extractor\*") 7-Zip confundia el prefijo con un modificador
REM y abortaba con "El sistema no puede encontrar el archivo especificado".
pushd "%APP%"
"!SZ!" a -t7z -mx=9 "..\BFI-Extractor-payload.7z" "*"
set "ERR7Z=!errorlevel!"
popd
if not "!ERR7Z!"=="0" (
    echo ERROR: fallo al comprimir la aplicacion ^(codigo !ERR7Z!^).
    pause
    exit /b 1
)

echo.
echo === Montando el instalador =============================================
REM config.txt: es lo primero que ejecuta el SFX al descomprimirse.
> "dist\config.txt" echo ;!@Install@!UTF-8!
>>"dist\config.txt" echo Title="BFI Extractor"
>>"dist\config.txt" echo BeginPrompt="Instalar BFI Extractor en este equipo?"
>>"dist\config.txt" echo RunProgram="instalar.bat"
>>"dist\config.txt" echo ;!@InstallEnd@!

copy /b "!SFX!" + "dist\config.txt" + "%PAQUETE%" "%SALIDA%" >nul
if errorlevel 1 (
    echo ERROR: no se pudo montar el instalador.
    pause
    exit /b 1
)

del /q "%PAQUETE%" "dist\config.txt"

echo.
echo ===========================================================================
echo  Listo: "%SALIDA%"
echo.
echo  Copialo al equipo destino y haz doble clic. El instalador:
echo    - comprueba si la aplicacion esta abierta,
echo    - la instala en %%LOCALAPPDATA%%\Programs,
echo    - crea el acceso directo del escritorio y del menu Inicio,
echo    - y avisa si faltan las credenciales de Ninox.
echo ===========================================================================
pause
