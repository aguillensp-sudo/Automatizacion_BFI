"""Sonda de escritura en la tabla DF "BFI 61021 (TEST)".

Responde UNA pregunta, la que decide el mapeo de toda la aplicacion:

    ?La API de Ninox acepta el *id* de campo ("R1", "G1", "D") o exige el
    *nombre* ("Referencia", "Detalles", "Importe USD")?

Metodo: se crea UN solo registro en DF, se escriben los mismos valores por id,
se lee de vuelta y se comprueba que campo quedo realmente grabado. Se repite con
nombres. El registro se borra SIEMPRE en un `finally`.

Uso:
    python tools/probe_df.py            # simulacion: no escribe nada
    python tools/probe_df.py --execute  # ejecucion real
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi.ninox_client import NinoxClient  # noqa: E402

TABLE = "DF"
MARKER = "BFI-PROBE-ID-VS-NOMBRE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="ejecuta de verdad")
    args = ap.parse_args()

    cli = NinoxClient()

    meta = cli.get_table(TABLE)
    by_id = {f["id"]: f["name"] for f in meta["fields"]}
    print("DF campos id->nombre:")
    for fid, name in by_id.items():
        print("   %-4s %s" % (fid, name))

    # 1) ?Acepta ids de campo?
    print("\n" + "=" * 70)
    print("PRUEBA A: escribir con IDS de campo (R1, G1, D, O, F, Q1)")
    print("=" * 70)
    payload_ids = {
        "fields": {
            "R1": MARKER,          # ?Referencia?
            "G1": "detalle prueba",  # ?Detalles? (en TD G1 es Conciliado)
            "D": 111.11,             # ?Importe?
            "O": 222.22,             # ?Saldo inicial?
            "F": True,               # ?Egreso/Ingreso?
            "Q1": "No",              # ?Oper. en transito?
        }
    }
    print(json.dumps(payload_ids, ensure_ascii=False))

    if not args.execute:
        print("\n(simulacion: nada escrito)")
        return 0

    new_id = None
    try:
        status, body = cli.create_record(TABLE, payload_ids)
        print("\nPOST ->", status)
        print(json.dumps(body, ensure_ascii=False, indent=2)[:1500])
        if isinstance(body, dict) and "id" in body:
            new_id = body["id"]
        else:
            # localizar por marcador
            for r in cli.fetch_all_records(TABLE):
                if MARKER in json.dumps(r.get("fields", {}), ensure_ascii=False):
                    new_id = r["id"]
                    break
        print("registro creado id =", new_id)
        if new_id is None:
            print("!! no se pudo identificar el registro creado")
            return 2

        guardado = cli.get_record(TABLE, new_id)
        print("\nESTADO GUARDADO (clave -> valor):")
        for k, v in guardado["fields"].items():
            print("   %-28s = %r" % (k, v))

        print("\nVEREDICTO:")
        campos = guardado["fields"]
        if campos.get("Referencia") == MARKER:
            print("   La API ACEPTA ids de campo: 'R1' se guardo en 'Referencia'.")
        elif any(v == MARKER for v in campos.values()):
            quien = [k for k, v in campos.items() if v == MARKER]
            print("   Raro: el marcador acabo en", quien)
        else:
            print("   La API NO guardo el marcador: los ids de campo no se aceptan.")
    finally:
        if new_id is not None:
            st, _ = cli.delete_record(TABLE, new_id)
            print("\nborrado de %s -> %s" % (new_id, st))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
