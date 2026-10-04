"""Interfaz de una fuente de correo.

Todo el pipeline habla con esta interfaz, nunca con COM directamente. Es lo que
permitira anadir Microsoft Graph el dia que el buzon viva en un inquilino propio
con administrador, sin tocar la logica de negocio.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional

from .modelo import Adjunto, FiltroMensajes, MensajeCorreo


class ErrorFuenteCorreos(Exception):
    """No se pudo leer el buzon (Outlook cerrado, sin perfil, carpeta ausente)."""


class FuenteCorreos(ABC):
    """De donde salen los correos con sus adjuntos."""

    nombre = "abstracta"

    def abrir(self) -> None:
        """Prepara el acceso. Debe poder llamarse dos veces sin efectos."""

    def cerrar(self) -> None:
        """Libera recursos. Debe tolerar que nunca se llamara a ``abrir``."""

    @abstractmethod
    def listar_carpetas(self) -> List[str]:
        """Rutas de las carpetas visibles, para diagnosticos."""

    @abstractmethod
    def listar_pendientes(self, filtro: FiltroMensajes) -> List[MensajeCorreo]:
        """Correos de la carpeta vigilada que pasan el filtro, del mas nuevo al
        mas antiguo."""

    @abstractmethod
    def descargar_adjuntos(self, mensaje: MensajeCorreo, destino: Path,
                           filtro: FiltroMensajes) -> List[Adjunto]:
        """Guarda en ``destino`` los adjuntos que interesan y los devuelve."""

    @abstractmethod
    def marcar_procesado(self, mensaje: MensajeCorreo) -> str:
        """Marca el correo como ya procesado. Devuelve que se hizo, para el log."""

    @abstractmethod
    def responder(self, mensaje: MensajeCorreo, texto: str) -> str:
        """Responde al remitente del correo. Devuelve que se hizo, para el log."""

    # -------------------------------------------------------------- contexto
    def __enter__(self) -> "FuenteCorreos":
        self.abrir()
        return self

    def __exit__(self, *_excepcion: Any) -> None:
        self.cerrar()

    def __repr__(self) -> str:                      # pragma: no cover - cosmetica
        return "<%s %s>" % (type(self).__name__, self.nombre)


def describir_error(exc: BaseException) -> str:
    """Mensaje accionable a partir de un error de COM o de red."""
    texto = str(exc).strip() or type(exc).__name__
    return texto


def buscar_carpeta(fuente: FuenteCorreos, ruta: str) -> Optional[str]:
    """Sugerencia de carpeta mas parecida a ``ruta``, para los mensajes de error."""
    objetivo = (ruta or "").split("/")[-1].strip().lower()
    if not objetivo:
        return None
    for candidata in fuente.listar_carpetas():
        if candidata.split("/")[-1].strip().lower() == objetivo:
            return candidata
    return None
