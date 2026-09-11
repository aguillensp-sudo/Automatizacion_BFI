"""Registro de la actividad de la aplicacion.

Escribe a fichero **y** a la interfaz. El fichero es lo unico que permite
averiguar que paso cuando el usuario dice "me dio un error": sin consola, un
``.exe --windowed`` no deja rastro en ningun sitio.

La carpeta de registros se crea junto al ejecutable (o junto al codigo en
desarrollo). Si no se puede escribir ahi (por ejemplo en ``C:\\Program Files``),
se cae a ``%LOCALAPPDATA%`` para no perder el registro.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional


def carpeta_base() -> Path:
    """Carpeta donde vive la aplicacion (soporta el empaquetado con PyInstaller)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def carpeta_logs() -> Path:
    """Primera carpeta escribible de una lista de candidatas.

    No se comprueba la escritura creando un fichero de prueba: eso dejaba un
    residuo en la carpeta de distribucion. Si al final ninguna fuera
    escribible, el ``FileHandler`` falla y el registro sigue funcionando en la
    ventana, que es lo importante.
    """
    candidatos = [
        carpeta_base() / "logs",
        Path.home() / "AppData" / "Local" / "BFI-Extractor" / "logs",
    ]
    for carpeta in candidatos:
        try:
            carpeta.mkdir(parents=True, exist_ok=True)
            return carpeta
        except OSError:
            continue
    return Path.cwd()


def configurar_logger(nombre: str = "bfi", nivel: int = logging.INFO,
                      consola: bool = False) -> logging.Logger:
    """Configura el registro a fichero (y a consola) del logger de la aplicacion.

    Es **idempotente por tipo de manejador**, y eso importa: antes esta funcion
    devolvia el logger en cuanto tuviera *cualquier* manejador, asi que si algo
    ya habia configurado el registro (la linea de comandos, o una prueba
    anterior), el manejador que envia las lineas a la ventana no se llegaba a
    conectar y **la caja de registro de la interfaz se quedaba vacia**.
    """
    logger = logging.getLogger(nombre)
    logger.setLevel(nivel)
    logger.propagate = False
    marcas = {getattr(h, "_bfi_tipo", None) for h in logger.handlers}
    formato = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")

    if "fichero" not in marcas:
        ruta = carpeta_logs() / ("bfi_%s.log" % datetime.now().strftime("%Y%m%d"))
        try:
            fh = logging.FileHandler(ruta, encoding="utf-8")
            fh.setFormatter(formato)
            fh._bfi_tipo = "fichero"
            logger.addHandler(fh)
        except OSError:
            pass

    if consola and "consola" not in marcas and getattr(sys, "stderr", None) is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formato)
        sh._bfi_tipo = "consola"
        logger.addHandler(sh)

    return logger


def conectar_a_ventana(destino, nombre: str = "bfi") -> logging.Logger:
    """Conecta la caja de registro de la ventana al logger de la aplicacion.

    Se puede llamar aunque el registro ya este configurado: retira el manejador
    de interfaz anterior, si lo hubiera, para que nunca queden dos ventanas
    recibiendo las mismas lineas.
    """
    logger = logging.getLogger(nombre)
    for handler in list(logger.handlers):
        if getattr(handler, "_bfi_tipo", None) == "ventana":
            logger.removeHandler(handler)
    ui = ManejadorInterfaz(destino)
    ui._bfi_tipo = "ventana"
    logger.addHandler(ui)
    return logger


class ManejadorInterfaz(logging.Handler):
    """Handler que reenvia cada linea a la caja de registro de la ventana."""

    def __init__(self, destino) -> None:
        super().__init__()
        self.destino = destino
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s",
                                            datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.destino(self.format(record))
        except Exception:           # noqa: BLE001 - la GUI nunca debe romper el log
            pass


def marca_de_tiempo() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")
