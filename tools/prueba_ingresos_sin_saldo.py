"""Crea dos ingresos en DF SIN escribir jamas el campo Saldo inicial.

Peticion explicita del usuario. El objetivo es ver que calcula la formula de
Ninox por si sola, sin que la aplicacion le escriba nada:

  * No se envia 'O' (Saldo inicial) en el alta.
  * No se hace ningun PUT de correccion.
  * Se lee lo que Ninox haya puesto, y se repite la lectura mas tarde por si
    recalcula con retardo.

Los datos son los mismos que los de la prueba anterior (ingresos inventados),
para poder comparar.

    python tools/prueba_ingresos_sin_saldo.py --execute
    python tools/prueba_ingresos_sin_saldo.py --borrar
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                      # noqa: E402
from bfi.ninox_client import NinoxClient                    # noqa: E402

# SIN la clave "O": el saldo no se envia nunca.
#
# El primer registro es un "ancla": la formula del saldo mira la fila ANTERIOR,
# y la primera fila no tiene ninguna. Sin ancla, el primer registro siempre
# saldra a 0 y no se podria distinguir "la formula no funciona" de "no habia
# nada de donde encadenar". El ancla representa un saldo ya existente en la
# cuenta antes de los movimientos que estamos probando.
ANCLA = {
    "B": "2026-08-31", "S1": "ANCLA-2026-08-31",
    "K1": "SALDO PREVIO DE LA CUENTA (ancla de la prueba)", "C": "11",
    "D": 0.0, "F": True, "Q1": "No", "J": 24,
}

INGRESOS = [
    {"B": "2026-09-01", "S1": "PRUEBA-ING-001",
     "K1": "INGRESO DE PRUEBA 1 (inventado)", "C": "11", "D": 1350.75,
     "F": True, "Q1": "No", "J": 24},
    {"B": "2026-09-02", "S1": "PRUEBA-ING-002",
     "K1": "INGRESO DE PRUEBA 2 (inventado)", "C": "11", "D": 1149.75,
     "F": True, "Q1": "No", "J": 24},
]

CAMPOS_QUE_IMPORTAN = ("Referencia", "Importe USD",
                       "Egreso/Ingreso", "Saldo inicial")


def leer(cli, rid):
    f = (cli.get_record(config.TABLA_TEST, rid) or {}).get("fields", {})
    return {k: f.get(k) for k in CAMPOS_QUE_IMPORTAN}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--borrar", action="store_true")
    args = ap.parse_args()

    cli = NinoxClient()
    todos = cli.fetch_all_records(config.TABLA_TEST, use_cache=False)

    if args.borrar:
        print("=== Borrando TODOS los registros de %s (%d) ==="
              % (config.TABLA_TEST, len(todos)))
        for r in sorted(todos, key=lambda x: x["id"]):
            print("   borrado", r["id"], "->",
                  cli.delete_record(config.TABLA_TEST, r["id"])[0])
        print("   quedan:", len(cli.fetch_all_records(config.TABLA_TEST, use_cache=False)))
        return 0

    print("=== Estado inicial de %s: %d registros ===" % (config.TABLA_TEST, len(todos)))
    for r in sorted(todos, key=lambda x: x["id"]):
        print("   id %s | %s | Saldo=%r" % (r["id"], r["fields"].get("Referencia"),
                                            r["fields"].get("Saldo inicial")))

    if not args.execute:
        print("\n(simulacion)")
        return 0

    print("\n=== Creando el ANCLA y los 2 INGRESOS, sin enviar NUNCA el saldo ===")
    print("   campos que se envian:", sorted(INGRESOS[0]))
    print("   (no aparece 'O' / 'Saldo inicial' a proposito)")
    ids = []
    for etiqueta, campos in ([("ANCLA", ANCLA)]
                             + [("INGRESO %d" % i, c)
                                for i, c in enumerate(INGRESOS, 1)]):
        st, cuerpo = cli.create_record(config.TABLA_TEST, {"fields": campos})
        rid = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        ids.append(rid)
        print("\n--- %s (id %s, HTTP %s) ---" % (etiqueta, rid, st))
        for k, v in leer(cli, rid).items():
            print("      %-16s : %r" % (k, v))

    for espera in (5, 20):
        print("\n=== Relectura tras %d segundos ===" % espera)
        time.sleep(espera)
        for etiqueta, rid in zip(["ANCLA"] + ["INGRESO %d" % i
                                              for i in range(1, len(INGRESOS) + 1)],
                                 ids):
            print("   %-9s (id %s): %s" % (etiqueta, rid, leer(cli, rid)))

    print("\nids para abrir en Ninox:", ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
