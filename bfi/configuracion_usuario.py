"""Escritura de las credenciales en el entorno del usuario de Windows.

El documento pide que la aplicacion se instale "sin intervencion del usuario,
dado que se trata de usuarios de ofimatica sin conocimiento de terminales". Un
``setx`` es una terminal; un cuadro de dialogo no. Este modulo es lo que permite
que la propia ventana guarde las credenciales.

Se escriben en ``HKCU\\Environment`` (ambito de USUARIO, nunca del sistema: no
hace falta ser administrador) y ademas en el proceso actual, para que surtan
efecto sin reiniciar la aplicacion. Otros programas reciben el cambio al
reiniciar la sesion, que es el comportamiento normal de las variables de
usuario.
"""
from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from .config import ENV_VARS

# Windows difunde este mensaje para avisar del cambio; con el, los programas ya
# abiertos (Explorer, nuevas consolas) recargan su bloque de entorno.
_HWND_BROADCAST = 0xFFFF
_WM_SETTINGCHANGE = 0x001A
_SMTO_ABORTIFHUNG = 0x0002


def _winreg():
    try:
        import winreg  # noqa: PLC0415 - solo existe en Windows
        return winreg
    except ImportError:
        return None


def guardar_credenciales(valores: Dict[str, str]) -> Tuple[bool, str]:
    """Guarda las credenciales. Devuelve (ok, mensaje).

    En sistemas sin Registro de Windows (macOS/Linux) las deja solo en el
    entorno del proceso y lo dice, en lugar de fallar en silencio.
    """
    limpios = {k: (v or "").strip() for k, v in valores.items() if k in ENV_VARS}
    faltan = [v for v in ENV_VARS if not limpios.get(v)]
    if faltan:
        return False, "Faltan valores: " + ", ".join(faltan)

    # 1) Efecto inmediato dentro de la aplicacion.
    for k, v in limpios.items():
        os.environ[k] = v

    # 2) Persistencia para las proximas ejecuciones.
    winreg = _winreg()
    if winreg is None:
        return True, ("Configuracion aplicada a esta sesion. En este sistema no "
                      "hay Registro de Windows, asi que no se puede guardar de "
                      "forma permanente.")

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as clave:
            for k, v in limpios.items():
                winreg.SetValueEx(clave, k, 0, winreg.REG_SZ, v)
    except OSError as exc:
        return False, ("No se pudieron guardar en el Registro: %s.\n"
                       "Las credenciales valen para esta sesion." % exc)

    _avisar_cambio()
    return True, ("Credenciales guardadas para este usuario. Se aplican desde "
                  "ahora y en los proximos arranques.")


def _avisar_cambio() -> None:
    """Avisa a Windows del cambio de entorno (best effort)."""
    try:
        import ctypes
        ctypes.windll.user32.SendMessageTimeoutW(
            _HWND_BROADCAST, _WM_SETTINGCHANGE, 0, "Environment",
            _SMTO_ABORTIFHUNG, 3000, None)
    except Exception:       # noqa: BLE001 - es solo un aviso, no debe romper nada
        pass


def credenciales_actuales() -> Dict[str, Optional[str]]:
    """Valores actuales, del entorno o del Registro. Solo para rellenar el dialogo."""
    from .credentials import get_credential
    return {nombre: get_credential(nombre) for nombre in ENV_VARS}
