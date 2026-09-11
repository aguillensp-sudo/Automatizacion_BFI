"""Sonda 3: ?el valor por defecto de "Saldo inicial" solo actua en el alta?

Hipotesis, despues de ver que en las tablas reales "Saldo inicial" tiene un
valor distinto por registro (1457 valores distintos en 1458 filas de OD), es
que NO es un campo con formula, sino un campo almacenado con **valor por
defecto que se impone al crear** y que admite correccion despues con un PUT.

Si eso es cierto hay una via de rescate para el unico campo que el POST
descarta, y conviene saberlo antes de dar por bueno el volcado.

Protocolo: UN registro en DF -> POST con 111 -> PUT con 222 -> borrar.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi.ninox_client import NinoxClient  # noqa: E402


def main() -> int:
    cli = NinoxClient()
    campo = "Saldo inicial"
    nuevo = None
    try:
        st, cuerpo = cli.create_record("DF", {"fields": {"S1": "BFI-PROBE-PUT",
                                                          campo: 111.11}})
        print("POST ->", st)
        nuevo = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        print("id", nuevo)
        tras_post = (cli.get_record("DF", nuevo) or {}).get("fields", {}).get(campo)
        print("  tras POST, %s = %r  (se envio 111.11)" % (campo, tras_post))

        st, _ = cli.update_record("DF", nuevo, {"fields": {campo: 222.22}})
        tras_put = (cli.get_record("DF", nuevo) or {}).get("fields", {}).get(campo)
        print("PUT  ->", st)
        print("  tras PUT,  %s = %r  (se envio 222.22)" % (campo, tras_put))

        print("\nVEREDICTO:")
        if tras_put == 222.22:
            print("   El campo SI es escribible: el valor por defecto solo gana en")
            print("   el alta. Un PUT posterior guarda lo que se envie -> hay via")
            print("   de rescate para el campo que el POST descarta.")
        elif tras_put == tras_post:
            print("   El campo NO acepta escritura ni en el alta ni en el PUT:")
            print("   se comporta como calculado. No se puede forzar por API.")
        else:
            print("   Comportamiento inesperado: tras POST %r, tras PUT %r"
                  % (tras_post, tras_put))
    finally:
        if nuevo is not None:
            print("borrado ->", cli.delete_record("DF", nuevo)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
