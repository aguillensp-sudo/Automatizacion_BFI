# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para BFI Extractor.

Se genera de forma automatica con `build_exe.bat`, que ademas crea el icono.
Este fichero se conserva en el repositorio para poder reproducir la compilacion
con `pyinstaller BFIExtractor.spec`.

Decisiones:
  * CARPETA y no un unico fichero: el .exe de un solo fichero se descomprime en
    %TEMP% en cada arranque, tarda varios segundos y dispara mas falsos positivos
    del antivirus. En una carpeta, el doble clic es instantaneo.
  * --windowed: sin ventana de consola negra detras de la aplicacion.
  * Se excluyen los paquetes de analisis de datos que pdfplumber no necesita,
    para reducir el tamano.
"""
import os

bloqueados = []
for modulo in ("pandas", "numpy", "matplotlib", "scipy", "PIL", "pytest",
               "IPython", "notebook", "tkinter.test"):
    bloqueados.append((modulo, None))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=["pdfplumber", "tkinter", "tkinter.ttk", "tkinter.filedialog",
                   "tkinter.messagebox"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[m for m, _ in bloqueados],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BFI Extractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join("recursos", "bfi.ico") if os.path.exists(
        os.path.join("recursos", "bfi.ico")) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="BFI Extractor",
)
