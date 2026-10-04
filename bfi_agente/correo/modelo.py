"""Modelo de datos del correo, independiente de como se lea el buzon.

COM (Outlook de escritorio) es la implementacion de hoy, pero la interfaz esta
pensada para que un dia se pueda anadir Microsoft Graph sin tocar el pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Pattern


@dataclass
class Adjunto:
    """Un adjunto de un correo. ``ruta`` solo se rellena al descargarlo."""

    nombre: str
    ruta: str = ""
    bytes_: int = 0
    hash: str = ""

    def descargado(self) -> bool:
        return bool(self.ruta)


@dataclass
class MensajeCorreo:
    """Un correo de la carpeta vigilada."""

    entry_id: str
    asunto: str = ""
    remitente: str = ""
    direccion: str = ""
    recibido: Optional[datetime] = None
    internet_message_id: str = ""
    adjuntos: List[Adjunto] = field(default_factory=list)

    @property
    def clave(self) -> str:
        """Identificador estable del correo para el registro de estado."""
        return self.entry_id or self.internet_message_id

    @property
    def recibido_texto(self) -> str:
        return self.recibido.strftime("%Y-%m-%d %H:%M") if self.recibido else ""

    def etiqueta(self) -> str:
        return "%s | %s | %s" % (self.recibido_texto or "sin fecha",
                                 self.direccion or self.remitente or "sin remitente",
                                 self.asunto or "(sin asunto)")


@dataclass
class FiltroMensajes:
    """Que correos y adjuntos interesan.

    El filtro se aplica **antes** de descargar nada: un buzon con mucho ruido no
    debe llenar la carpeta de trabajo con adjuntos que no son del banco.
    """

    desde: Optional[datetime] = None
    remitentes: List[str] = field(default_factory=list)
    patron_adjunto: Optional[Pattern[str]] = None
    patron_asunto: Optional[Pattern[str]] = None

    def _remitente_autorizado(self, mensaje: MensajeCorreo) -> bool:
        if not self.remitentes:
            return True
        candidatos = {mensaje.direccion.lower(), mensaje.remitente.lower()}
        for permitido in self.remitentes:
            buscado = permitido.lower()
            if buscado in candidatos:
                return True
            # Permitir dominios completos (@banco.com) y comodines simples.
            if buscado.startswith("@") and any(c.endswith(buscado) for c in candidatos):
                return True
        return False

    def adjunto_interesa(self, nombre: str) -> bool:
        if not nombre:
            return False
        return self.patron_adjunto is None or bool(self.patron_adjunto.search(nombre))

    def dentro_de_ventana(self, mensaje: MensajeCorreo) -> bool:
        """Si el correo cae dentro del periodo que se revisa."""
        if self.desde is None or mensaje.recibido is None:
            return True
        return mensaje.recibido >= self.desde

    def adjuntos_validos(self, mensaje: MensajeCorreo) -> List[Adjunto]:
        return [a for a in mensaje.adjuntos if self.adjunto_interesa(a.nombre)]

    def motivo_rechazo(self, mensaje: MensajeCorreo) -> Optional[str]:
        """Devuelve el motivo por el que el correo se ignora, o None si vale."""
        if self.patron_asunto is not None and not self.patron_asunto.search(mensaje.asunto or ""):
            return "el asunto no coincide"
        if not self._remitente_autorizado(mensaje):
            return "remitente no autorizado"
        if not self.adjuntos_validos(mensaje):
            return "sin adjuntos que interesen"
        return None
