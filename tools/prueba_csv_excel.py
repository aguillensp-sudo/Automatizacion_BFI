"""Comprueba que un CSV guardado desde Excel se inserta bien.

Escenario real: el usuario abre el CSV en Excel y lo guarda. Excel deja las
fechas como ``08/07/2026`` y quita el decimal de los numeros (``7992`` en vez de
``7992.0``). Antes, la aplicacion enviaba esa fecha tal cual a Ninox, que no la
reconoce.

El ensayo escribe en la tabla de prueba DF y borra lo que crea.

    python tools/prueba_csv_excel.py            # simulacion
    python tools/prueba_csv_excel.py --execute
"""
from __future__ import annotations

import argparse
import csv
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                       # noqa: E402
from bfi.extractor import FIELDNAMES                          # noqa: E402
from bfi.mapping import (agrupar_por_tabla, construir_payload,  # noqa: E402
                         leer_csv, resolver_mapeo)
from bfi.ninox_client import NinoxClient                      # noqa: E402

# Fila tal y como la deja Excel: fechas dd/mm/aaaa y numeros sin decimal.
FILA_EXCEL = {
    "cuenta_no": "0300000006102035", "moneda": "USD",
    "nombre": "JULSA INDUSTRIAL, S.A.", "estado_no": "372",
    "periodo_desde": "30/06/2026", "periodo_hasta": "19/07/2026",
    "fecha_emision": "20/07/2026", "saldo_anterior": "23226.13",
    "fecha": "17/07/2026", "fecha_valor": "08/07/2026",
    "referencia": "FT2619151273", "detalle": "TRANSFERENCIA RECIBIDA: USD",
    "debito": "", "credito": "7992", "saldo": "31218.13",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="bfi_excel_"))
    ruta = tmp / "excel.csv"
    with open(ruta, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerow(FILA_EXCEL)

    filas = leer_csv(str(ruta))
    grupos = agrupar_por_tabla(filas)
    print("CSV de Excel leido ->", {t: len(v) for t, v in grupos.items()})

    cli = NinoxClient()
    # DF es identica a TD: sirve para validar el payload sin tocar negocio.
    mapeo = resolver_mapeo(config.TABLA_TEST, cli.field_names(config.TABLA_TEST))
    df = dict(filas[0])
    df["cuenta_no"] = "0300000006102035"
    envio = construir_payload(df, mapeo)
    print("\nPayload generado:")
    for k, v in envio["fields"].items():
        print("   %-24s = %r" % (k, v))

    esperado = envio["fields"]["Fecha Bancaria"]
    if esperado != "2026-07-08":
        print("\nFALLO: la fecha deberia haberse convertido a 2026-07-08 y es %r" % esperado)
        return 1
    print("\nOK: 08/07/2026 -> %s" % esperado)

    if not args.execute:
        print("(simulacion: nada escrito)")
        return 0

    nuevo = None
    try:
        st, cuerpo = cli.create_record(config.TABLA_TEST, envio)
        print("\nPOST ->", st)
        nuevo = cuerpo.get("id") if isinstance(cuerpo, dict) else None
        guardado = (cli.get_record(config.TABLA_TEST, nuevo) or {}).get("fields", {})
        real = guardado.get("Fecha Bancaria")
        print("Guardado en Ninox: Fecha Bancaria = %r" % real)
        print("Importe USD = %r | Egreso/Ingreso = %r"
              % (guardado.get("Importe USD"), guardado.get("Egreso/Ingreso")))
        if real == "2026-07-08":
            print("\nOK: Ninox acepto la fecha convertida.")
            return 0
        print("\nFALLO: Ninox guardo %r" % real)
        return 1
    finally:
        if nuevo is not None:
            print("borrado ->", cli.delete_record(config.TABLA_TEST, nuevo)[0])


if __name__ == "__main__":
    raise SystemExit(main())
