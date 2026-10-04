"""Comprueba que las tablas destino (OD, PD y TD) existen y mapean bien.

Se usa antes de apuntar el agente a una base distinta de la habitual: una base
de pruebas puede no tener las mismas tablas, y es mejor saberlo antes de dejar
corriendo una tarea desatendida.

Uso:
    python tools/comprobar_tablas_ninox.py                 # base configurada
    python tools/comprobar_tablas_ninox.py jd1m8n8l4j7i    # otra base
    python tools/comprobar_tablas_ninox.py jd1m8n8l4j7i "JI-PRUEBAS-CLAUDE"
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bfi import config                                    # noqa: E402
from bfi.ninox_writer import EscritorNinox                # noqa: E402


def main() -> int:
    db_id = (sys.argv[1] if len(sys.argv) > 1 else "").strip()
    etiqueta = (sys.argv[2] if len(sys.argv) > 2 else db_id)

    # El cliente lee las credenciales del entorno primero, asi que basta con
    # definirla aqui para apuntar a otra base sin tocar la configuracion del
    # usuario.
    if db_id:
        os.environ[config.ENV_DB_ID] = db_id
        print("Base de datos: %s (%s)" % (etiqueta or db_id, db_id))
    else:
        from bfi.credentials import get_credential
        print("Base de datos configurada: %s"
              % get_credential(config.ENV_DB_ID))

    print("Tablas esperadas: %s"
          % ", ".join("%s -> %s" % (t, config.TABLA_A_ETIQUETA.get(t, t))
                      for t in sorted(set(config.CUENTA_A_TABLA.values()))))
    escritor = EscritorNinox(aviso=lambda texto: print("  %s" % texto))
    try:
        ok, mensaje = escritor.comprobar_conexion()
    except Exception as exc:                              # noqa: BLE001
        print("ERROR: %s" % exc)
        return 2
    print(mensaje)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
