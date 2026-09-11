"""Carga de credenciales de Ninox sin intervencion del usuario.

Orden de resolucion:

1. ``os.environ`` (desarrollo, o cuando el lanzador las inyecta).
2. Registro de Windows, ambito de USUARIO, que es donde las deja ``setx`` y el
   panel de Sistema. Se consulta via PowerShell **y** via ``reg query`` porque
   un ``.exe`` empaquetado con PyInstaller arranca sin shell.

Si falta alguna variable se lanza ``EnvironmentError`` con un mensaje que un
usuario de ofimatica pueda entender.
"""
from __future__ import annotations

import os
import subprocess
from typing import Optional

from .config import ENV_VARS


def _from_powershell(name: str) -> Optional[str]:
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "[Environment]::GetEnvironmentVariable('%s','User')" % name],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    value = (out.stdout or "").strip()
    return value or None


def _from_reg_query(name: str) -> Optional[str]:
    """Alternativa sin PowerShell: HKCU\\Environment."""
    try:
        out = subprocess.run(
            ["reg", "query", r"HKCU\Environment", "/v", name],
            capture_output=True, text=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError):
        return None
    if out.returncode != 0:
        return None
    for line in (out.stdout or "").splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].upper() == name.upper():
            return parts[2].strip() or None
    return None


def get_credential(name: str) -> Optional[str]:
    """Devuelve el valor de una variable: proceso -> PowerShell -> registro."""
    value = os.environ.get(name)
    if value:
        return value
    return _from_powershell(name) or _from_reg_query(name)


def load_credentials() -> dict:
    """Carga las tres credenciales o falla con un mensaje accionable."""
    creds = {}
    missing = []
    for name in ENV_VARS:
        value = get_credential(name)
        if value:
            creds[name] = value
        else:
            missing.append(name)
    if missing:
        raise EnvironmentError(
            "Faltan las credenciales de Ninox: " + ", ".join(missing) +
            ".\n\nDefinelas como variables de entorno del usuario y vuelve a "
            "abrir la aplicacion:\n"
            '   setx NINOX_API_KEY "tu_clave"\n'
            '   setx NINOX_TEAM_ID "tu_equipo"\n'
            '   setx NINOX_DB_ID   "tu_base_de_datos"\n'
        )
    return creds
