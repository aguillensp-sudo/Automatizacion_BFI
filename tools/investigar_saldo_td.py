"""Investiga de donde ha salido el Saldo inicial del registro de prueba en TD."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi.ninox_client import NinoxClient  # noqa: E402

OBJETIVO = 962          # el ingreso de prueba que se acaba de crear
INGRESOS = "Ingresos recibidos"


def main() -> int:
    cli = NinoxClient()
    recs = sorted(cli.fetch_all_records("TD", use_cache=False),
                  key=lambda r: (str(r["fields"].get("Fecha Bancaria") or ""), r["id"]))

    print("=== Registros de TD con Concepto = '%s', por fecha ===" % INGRESOS)
    con_ingreso = [r for r in recs if r["fields"].get("Concepto") == INGRESOS]
    for r in con_ingreso[-15:]:
        f = r["fields"]
        print("   id=%-5s sec=%-5s fecha=%-12s imp=%-11s saldo=%-12s"
              % (r["id"], f.get("Secuencial"), f.get("Fecha Bancaria"),
                 f.get("Importe USD"), f.get("Saldo inicial")))
    print("\n   totales con ese Concepto: %d" % len(con_ingreso))

    print("\n=== El registro nuevo y sus vecinos ===")
    for r in recs:
        if r["id"] in (OBJETIVO - 1, OBJETIVO) or r["id"] in (954, 955, 956):
            f = r["fields"]
            print("   id=%-5s fecha=%-12s imp=%-11s saldo=%-12s Concepto=%r"
                  % (r["id"], f.get("Fecha Bancaria"), f.get("Importe USD"),
                     f.get("Saldo inicial"), f.get("Concepto")))

    print("\n=== Las 5 ultimas filas por Secuencial ===")
    por_sec = sorted(recs, key=lambda r: (r["fields"].get("Secuencial") or 0))
    for r in por_sec[-5:]:
        f = r["fields"]
        print("   sec=%-5s id=%-5s fecha=%-12s imp=%-11s saldo=%-12s Concepto=%r"
              % (f.get("Secuencial"), r["id"], f.get("Fecha Bancaria"),
                 f.get("Importe USD"), f.get("Saldo inicial"), f.get("Concepto")))

    print("\n=== ?De donde puede salir 23226.13? ===")
    iguales = [r for r in recs if r["fields"].get("Saldo inicial") == 23226.13]
    print("   registros de TD con Saldo inicial = 23226.13: %d" % len(iguales))
    for r in iguales[:5]:
        print("      id=%-5s sec=%-5s fecha=%-12s Concepto=%r"
              % (r["id"], r["fields"].get("Secuencial"),
                 r["fields"].get("Fecha Bancaria"), r["fields"].get("Concepto")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
