"""Fuentes de correo del agente."""
from __future__ import annotations

from .fuente import ErrorFuenteCorreos, FuenteCorreos
from .fuente_outlook_com import FuenteOutlookCom, outlook_disponible
from .fuente_simulada import FuenteSimulada
from .modelo import Adjunto, FiltroMensajes, MensajeCorreo

__all__ = [
    "Adjunto",
    "ErrorFuenteCorreos",
    "FiltroMensajes",
    "FuenteCorreos",
    "FuenteOutlookCom",
    "FuenteSimulada",
    "MensajeCorreo",
    "outlook_disponible",
]
