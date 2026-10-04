"""Agente de correo del BFI.

Lee una carpeta del Outlook **clasico** de este equipo, descarga los adjuntos
PDF de los estados de cuenta, los procesa con el mismo pipeline que usa la
aplicacion de escritorio (``bfi.extractor`` -> ``bfi.mapping`` ->
``bfi.ninox_writer``) y deja constancia de lo ocurrido en un correo de resumen.

Por que COM y no Microsoft Graph: la suscripcion es **personal**, asi que no
existe un inquilino de Entra ID donde registrar una aplicacion ni un
administrador que conceda permisos. COM sobre el Outlook de escritorio no
necesita nada de eso.
"""
from __future__ import annotations

__all__ = ["NOMBRE", "VERSION"]

NOMBRE = "Agente de correo BFI"
VERSION = "1.0.0"
