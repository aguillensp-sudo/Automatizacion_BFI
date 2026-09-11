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
    """Configura y devuelve el logger de la aplicacion (idempotente)."""
    logger = logging.getLogger(nombre)
    if logger.handlers:
        return logger
    logger.setLevel(nivel)
    logger.propagate = False

    formato = logging.Formatter("%(asctime)s %(levelname)-8s %(message)s",
                                datefmt="%Y-%m-%d %H:%M:%S")

    ruta = carpeta_logs() / ("bfi_%s.log" % datetime.now().strftime("%Y%m%d"))
    try:
        fh = logging.FileHandler(ruta, encoding="utf-8")
        fh.setFormatter(formato)
        logger.addHandler(fh)
    except OSError:
        pass

    if consola and getattr(sys, "stderr", None) is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(formato)
        logger.addHandler(sh)
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
