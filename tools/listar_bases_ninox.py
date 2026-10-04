"""Lista las bases de datos Ninox del equipo configurado.

Sirve para averiguar el identificador de una base concreta (por ejemplo la de
pruebas) sin tener que mirarlo en la web de Ninox.

Uso:
    python tools/listar_bases_ninox.py
    python tools/listar_bases_ninox.py pruebas

Nota: se pide la lista con urllib directamente en lugar de usar NinoxClient,
porque ese cliente construye siempre la URL de UNA base concreta
(``/databases/{db}``) y aqui hace falta el nivel de arriba
(``/databases``).
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bfi.config import NINOX_BASE_URL                     # noqa: E402
from bfi.credentials import load_credentials              # noqa: E402


def main() -> int:
    filtro = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    try:
        credenciales = load_credentials()
    except EnvironmentError as exc:
        print(exc)
        return 2

    url = "%s/teams/%s/databases" % (NINOX_BASE_URL, credenciales["NINOX_TEAM_ID"])
    peticion = urllib.request.Request(
        url,
        headers={"Authorization": "Bearer %s" % credenciales["NINOX_API_KEY"],
                 "Accept": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(peticion, timeout=30) as respuesta:
            estado, cuerpo = respuesta.status, respuesta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        print("ERROR HTTP %s al pedir %s" % (exc.code, url))
        print(exc.read().decode("utf-8", "replace")[:500])
        return 2
    except urllib.error.URLError as exc:
        print("ERROR de red al pedir %s: %s" % (url, exc))
        return 2

    try:
        datos = json.loads(cuerpo)
    except json.JSONDecodeError:
        print("Respuesta no JSON (HTTP %s): %s" % (estado, cuerpo[:500]))
        return 2

    if not isinstance(datos, list):
        print("Respuesta inesperada (HTTP %s): %s" % (estado, cuerpo[:500]))
        return 2

    print("Bases de datos del equipo %s (%d):" % (credenciales["NINOX_TEAM_ID"], len(datos)))
    mostradas = 0
    for base in datos:
        if not isinstance(base, dict):
            continue
        nombre = str(base.get("name", ""))
        if filtro and filtro not in nombre.lower():
            continue
        mostradas += 1
        print("  id=%-16s  %s" % (base.get("id"), nombre))
    if filtro and not mostradas:
        print("  (ninguna coincide con '%s')" % filtro)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
