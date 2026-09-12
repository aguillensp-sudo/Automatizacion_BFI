"""Sonda: ?lo calcula Ninox solo el "Saldo inicial"?

El usuario ha visto el trigger de creacion de la tabla:

    'Saldo inicial' := number((select 'BFI 61020' where Secuencial = p).'Saldo final')

Eso significa que al CREAR un registro, Ninox lo rellena solo. La consecuencia
practica es que la aplicacion no debe enviar ese campo.

Esta sonda mide tres cosas sobre la tabla de prueba DF:

  1. Si "Saldo final" existe como campo (lo usa el trigger).
  2. Que valor pone Ninox en "Saldo inicial" al crear, sin enviarlo.
  3. Si enviamos un valor distinto, ?lo respeta? (solo si lo respeta tendria
     sentido enviarlo; si lo pisa, enviarlo es inutil).

Escribe en DF y borra lo que crea.

    python tools/probe_saldo_trigger.py            # simulacion
    python tools/probe_saldo_trigger.py --execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                     # noqa: E402
from bfi.ninox_client import NinoxClient                    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    cli = NinoxClient()
    tabla = config.TABLA_TEST

    campos = cli.field_names(tabla)
    print("=== 1. Campos con 'Saldo' o 'Secuencial' en %s ===" % tabla)
    for fid, nombre in campos.items():
        if "aldo" in nombre or "ecuencial" in nombre:
            print("   %-4s %s" % (fid, nombre))

    usados = set()
    try:
        # --- A) Crear SIN enviar Saldo inicial ---
        base = {"B": "2026-01-01", "S1": "BFI-SONDA-TRIGGER-A", "K1": "sonda A",
                "D": 1.0, "F": True, "Q1": "No", "J": 24}
        print("\n=== 2. POST sin enviar 'Saldo inicial' ===")
        print("   envio:", {k: v for k, v in base.items()})
        if not args.execute:
            print("   (simulacion)")
            return 0

        st, cuerpo = cli.create_record(tabla, {"fields": base})
        id_a = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        usados.add(id_a)
        guardado_a = (cli.get_record(tabla, id_a) or {}).get("fields", {})
        print("   POST ->", st, "| id", id_a)
        print("   guardado:", {k: v for k, v in guardado_a.items()
                               if "aldo" in k or "ecuencial" in k})
        saldo_a = guardado_a.get("Saldo inicial")

        # --- B) Crear ENVIANDO un Saldo inicial distinto ---
        print("\n=== 3. POST enviando 'Saldo inicial' = 98765.43 ===")
        base_b = dict(base)
        base_b["S1"] = "BFI-SONDA-TRIGGER-B"
        base_b["K1"] = "sonda B"
        base_b["O"] = 98765.43
        st, cuerpo = cli.create_record(tabla, {"fields": base_b})
        id_b = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        usados.add(id_b)
        guardado_b = (cli.get_record(tabla, id_b) or {}).get("fields", {})
        print("   POST ->", st, "| id", id_b)
        print("   Saldo inicial guardado:", repr(guardado_b.get("Saldo inicial")))
        print("   ?respeto lo enviado (98765.43)?:",
              "SI" if guardado_b.get("Saldo inicial") == 98765.43 else "NO, lo piso")

        # --- Conclusion ---
        print("\n=== CONCLUSION ===")
        if saldo_a is not None and saldo_a == guardado_b.get("Saldo inicial"):
            print("   Ninox calcula 'Saldo inicial' por su cuenta y DESCARTA lo que")
            print("   se le envie: los dos registros quedaron con el mismo valor")
            print("   (%r) pese a enviar 98765.43 en el segundo." % saldo_a)
            print("   -> La aplicacion NO debe enviar ese campo.")
        elif guardado_b.get("Saldo inicial") == 98765.43:
            print("   El valor enviado SI se guarda. Si el trigger existe, no se")
            print("   esta aplicando a esta tabla (%s)." % tabla)
        else:
            print("   Comportamiento a revisar: A=%r B=%r"
                  % (saldo_a, guardado_b.get("Saldo inicial")))
    finally:
        for rid in usados:
            if rid is not None:
                print("   borrado %s ->" % rid, cli.delete_record(tabla, rid)[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
