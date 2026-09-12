"""Crea los dos ingresos de prueba en DF con el campo Concepto = 11.

Peticion del usuario: regenerar los mismos dos ingresos inventados, esta vez con
el campo Concepto puesto a "Ingresos recibidos" (id 11), porque ese campo
interviene en el calculo del saldo inicial.

    python tools/prueba_ingresos_df.py             # simulacion
    python tools/prueba_ingresos_df.py --execute
    python tools/prueba_ingresos_df.py --execute --borrar   # borra y sale
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                     # noqa: E402
from bfi.ninox_client import NinoxClient                    # noqa: E402

# Mismos datos que la vez anterior, MAS el Concepto = 11 (Ingresos recibidos).
INGRESOS = [
    {"B": "2026-09-01", "S1": "PRUEBA-ING-001",
     "K1": "INGRESO DE PRUEBA 1 (inventado)", "C": "11", "D": 1350.75,
     "F": True, "Q1": "No", "J": 24, "O": 10000.00},
    {"B": "2026-09-02", "S1": "PRUEBA-ING-002",
     "K1": "INGRESO DE PRUEBA 2 (inventado)", "C": "11", "D": 1149.75,
     "F": True, "Q1": "No", "J": 24, "O": 11350.75},
]
SALDO_ENVIADO = [10000.00, 11350.75]
SALDO_ESPERADO = [11350.75, 12500.50]   # saldo tras aplicar el importe


def mostrar(cli, rid, etiqueta=""):
    f = (cli.get_record(config.TABLA_TEST, rid) or {}).get("fields", {})
    print("   %-8s id %s" % (etiqueta, rid))
    print("      Referencia     : %s" % f.get("Referencia"))
    print("      Concepto       : %r" % f.get("Concepto"))
    print("      Importe USD    : %s" % f.get("Importe USD"))
    print("      Egreso/Ingreso : %r  (toggle azul = ingreso)" % f.get("Egreso/Ingreso"))
    print("      Saldo inicial  : %r" % f.get("Saldo inicial"))
    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--borrar", action="store_true", help="borra los de prueba y sale")
    args = ap.parse_args()

    cli = NinoxClient()
    existentes = [r for r in cli.fetch_all_records(config.TABLA_TEST, use_cache=False)
                  if (r["fields"].get("Referencia") or "").startswith("PRUEBA-ING")]

    if args.borrar:
        for r in existentes:
            print("   borrado", r["id"], "->",
                  cli.delete_record(config.TABLA_TEST, r["id"])[0])
        return 0

    print("=== Registros de prueba que ya hay: %d ===" % len(existentes))
    for r in existentes:
        print("   id %s | %s | Concepto=%r | Saldo=%r"
              % (r["id"], r["fields"].get("Referencia"),
                 r["fields"].get("Concepto"), r["fields"].get("Saldo inicial")))

    if not args.execute:
        print("\n(simulacion: no se crea nada)")
        return 0

    print("\n=== Creando los 2 INGRESOS con Concepto = 11 ===")
    ids = []
    for i, campos in enumerate(INGRESOS, 1):
        st, cuerpo = cli.create_record(config.TABLA_TEST, {"fields": campos})
        rid = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        ids.append(rid)
        print("\n--- Linea %d (envio saldo %s) ---" % (i, SALDO_ENVIADO[i - 1]))
        mostrar(cli, rid, "creado")

    print("\n=== Esperando 5 s por si Ninox recalcula el saldo solo ===")
    time.sleep(5)
    for i, rid in enumerate(ids, 1):
        f = mostrar(cli, rid, "5s despues")
        print("      lo que deberia valer: %s" % SALDO_ESPERADO[i - 1])

    print("\nids para abrir en Ninox:", ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
