"""Fuente simulada: correos de mentira para pruebas y para ``--dry-run``.

Permite ejercitar el pipeline completo (filtros, descarga, extraccion, estado,
resumen) sin Outlook, sin red y sin credenciales de Ninox.
"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

from .fuente import ErrorFuenteCorreos, FuenteCorreos
from .modelo import Adjunto, FiltroMensajes, MensajeCorreo


def _leer_texto(ruta: Path, por_defecto: str = "") -> str:
    try:
        return ruta.read_text(encoding="utf-8").strip()
    except OSError:
        return por_defecto


class FuenteSimulada(FuenteCorreos):
    """Sirve los mensajes que se le pasen, sin tocar ningun buzon real.

    ``desde_directorio`` construye los mensajes a partir de una carpeta de
    ejemplo: cada subcarpeta es un correo y los ficheros que contiene son sus
    adjuntos. Dos ficheros opcionales describen el correo:

    * ``asunto.txt``    -> asunto del mensaje
    * ``remitente.txt`` -> direccion del remitente
    """

    nombre = "simulada"

    def __init__(self, mensajes: Optional[List[MensajeCorreo]] = None,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.mensajes = list(mensajes or [])
        self.log = log or (lambda texto: None)
        self.marcados: List[str] = []
        self.respuestas: List[tuple] = []
        self.abierta = False

    # ------------------------------------------------------------ construccion
    @classmethod
    def desde_directorio(cls, ruta: Any,
                         log: Optional[Callable[[str], None]] = None) -> "FuenteSimulada":
        raiz = Path(ruta)
        if not raiz.is_dir():
            raise ErrorFuenteCorreos(
                "La carpeta de simulacion no existe o no es un directorio: %s" % raiz)
        mensajes: List[MensajeCorreo] = []
        for indice, sub in enumerate(sorted(p for p in raiz.iterdir() if p.is_dir()), start=1):
            if sub.name.startswith("."):
                continue
            adjuntos = [
                Adjunto(nombre=f.name, ruta=str(f), bytes_=f.stat().st_size)
                for f in sorted(sub.iterdir())
                if f.is_file() and f.name.lower() not in ("asunto.txt", "remitente.txt")
            ]
            mensajes.append(MensajeCorreo(
                entry_id="SIM-%03d-%s" % (indice, sub.name),
                asunto=_leer_texto(sub / "asunto.txt", sub.name),
                remitente=_leer_texto(sub / "remitente.txt", "simulado@ejemplo.com"),
                direccion=_leer_texto(sub / "remitente.txt", "simulado@ejemplo.com"),
                recibido=datetime.now(),
                # El identificador de Internet se deriva del nombre de la carpeta:
                # dos correos distintos no pueden compartirlo, igual que en un
                # buzon real (un reenvio es un mensaje nuevo, con otro id).
                internet_message_id="<sim-%s@ejemplo.com>" % sub.name,
                adjuntos=adjuntos,
            ))
        return cls(mensajes, log=log)

    # ---------------------------------------------------------------- interfaz
    def abrir(self) -> None:
        self.abierta = True

    def cerrar(self) -> None:
        self.abierta = False

    def listar_carpetas(self) -> List[str]:
        return ["Bandeja de entrada/BFI (simulada)"]

    def listar_pendientes(self, filtro: FiltroMensajes) -> List[MensajeCorreo]:
        validos = []
        for mensaje in self.mensajes:
            if not filtro.dentro_de_ventana(mensaje):
                self.log("   [simulada] se ignora %s: fuera de la ventana de revision"
                         % mensaje.asunto)
                continue
            motivo = filtro.motivo_rechazo(mensaje)
            if motivo:
                self.log("   [simulada] se ignora %s: %s" % (mensaje.asunto, motivo))
                continue
            validos.append(mensaje)
        return validos

    def descargar_adjuntos(self, mensaje: MensajeCorreo, destino: Path,
                           filtro: FiltroMensajes) -> List[Adjunto]:
        destino.mkdir(parents=True, exist_ok=True)
        salida: List[Adjunto] = []
        for adjunto in filtro.adjuntos_validos(mensaje):
            ruta_destino = destino / adjunto.nombre
            if Path(adjunto.ruta) != ruta_destino:
                shutil.copy2(adjunto.ruta, ruta_destino)
            salida.append(Adjunto(nombre=adjunto.nombre, ruta=str(ruta_destino),
                                  bytes_=ruta_destino.stat().st_size))
        return salida

    def marcar_procesado(self, mensaje: MensajeCorreo) -> str:
        self.marcados.append(mensaje.clave)
        return "marcado como procesado (simulacion)"

    def responder(self, mensaje: MensajeCorreo, texto: str) -> str:
        self.respuestas.append((mensaje.clave, texto))
        return "respuesta simulada a %s" % (mensaje.direccion or mensaje.remitente)
