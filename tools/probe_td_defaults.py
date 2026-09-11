"""Sonda 2: que campos se auto-rellenan y que forma debe tener el payload.

La sonda anterior demostro dos cosas:

1. La API **acepta el id de campo** ("R1", "D", "O"...) y lo traduce al nombre.
2. **No todo lo que envias se guarda**: "Saldo inicial" recibio 222.22 y quedo
   en 23226.13 (valor por defecto/formula de la tabla).

Por defecto esta sonda trabaja sobre **DF**, la unica tabla del ERP vacia y con
campos escribibles. DF es *identica* a TD (mismos ids de campo: B, D, F, J, C1,
K1, R1, S1, O, Q1, G1), asi que sirve para validar el payload de TD sin tocar
una tabla de negocio. En OD y PD los campos con formula ("Saldo inicial",
"Tipo de Cambio") se comportaran igual, porque son las mismas formulas.

`--tablas` permite apuntar a tablas reales, pero hacerlo implica crear Y BORRAR
en tablas de negocio con referencias entrantes (TC Saldos, QC Facturas Cuba).
El documento del ERP lo prohibe. No lo hagas sin una razon muy justificada.

Uso:
    python tools/probe_td_defaults.py                 # simulacion sobre DF
    python tools/probe_td_defaults.py --execute       # ejecucion real sobre DF
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi.ninox_client import NinoxClient  # noqa: E402

MARCADOR = "BFI-PROBE-DEFAULTS"

# Campos que la aplicacion va a escribir, en ids, mas un valor de prueba.
# DF replica TD, asi que este es literalmente el payload de la tabla TD.
POR_TABLA = {
    "DF": {"B": "2026-07-01", "S1": MARCADOR, "K1": "detalle de prueba",
           "D": 12.34, "O": 999.99, "F": True, "Q1": "No", "J": 24, "C1": ""},
    "TD": {"B": "2026-07-01", "S1": MARCADOR, "K1": "detalle de prueba",
           "D": 12.34, "O": 999.99, "F": True, "Q1": "No", "J": 24, "C1": ""},
    "PD": {"B": "2026-07-01", "P1": MARCADOR, "G1": "detalle de prueba",
           "D": 12.34, "O": 999.99, "F": True, "M1": "No"},
    "OD": {"B": "2026-07-01", "R1": MARCADOR, "G1": "detalle de prueba",
           "D": 12.34, "O": 999.99, "F": True, "O1": "No"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--tablas", nargs="*", default=["DF"])
    args = ap.parse_args()

    cli = NinoxClient()
    resumen = {}

    for tabla in args.tablas:
        envio = POR_TABLA[tabla]
        print("=" * 72)
        print("TABLA %s — envio:" % tabla, json.dumps(envio, ensure_ascii=False))

        if not args.execute:
            print("   (simulacion)")
            resumen[tabla] = "simulado"
            continue

        nuevo_id = None
        try:
            status, body = cli.create_record(tabla, {"fields": envio})
            print("   POST ->", status)
            if status != 200:
                print("   !! respuesta:", json.dumps(body, ensure_ascii=False)[:400])
                resumen[tabla] = "POST %s" % status
                continue
            nuevo_id = body.get("id") if isinstance(body, dict) else None
            if nuevo_id is None:
                resumen[tabla] = "sin id en la respuesta"
                continue

            guardado = cli.get_record(tabla, nuevo_id) or {}
            campos = guardado.get("fields", {})
            print("   id", nuevo_id, "-> guardado:")
            for k, v in campos.items():
                print("      %-26s = %r" % (k, v))

            # Comparativa: que se pidio y que quedo
            nombres = cli.field_names(tabla)
            print("   COMPARATIVA:")
            for fid, valor in envio.items():
                nombre = nombres.get(fid, "??")
                real = campos.get(nombre, "<ausente>")
                ok = (str(real) == str(valor)) or (real == valor)
                print("      %-4s %-26s enviado=%-14r guardado=%r   %s"
                      % (fid, nombre, valor, real, "OK" if ok else "DIFIERE"))
            auto = sorted(set(campos) - {nombres.get(f, f) for f in envio})
            print("   CAMPOS AUTO-RELLENADOS (no enviados):", auto or "ninguno")
            resumen[tabla] = "id %s | auto=%s" % (nuevo_id, auto)
        finally:
            if nuevo_id is not None:
                st, _ = cli.delete_record(tabla, nuevo_id)
                print("   borrado de %s -> %s" % (nuevo_id, st))

    print("\n" + "=" * 72)
    print("RESUMEN")
    for t, r in resumen.items():
        print("   %-3s %s" % (t, r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
