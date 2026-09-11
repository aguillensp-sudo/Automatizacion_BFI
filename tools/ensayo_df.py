"""Ensayo de punta a punta: volcado completo en la tabla de test DF.

Ejecuta el circuito real (leer CSV -> validar mapeo -> construir payload ->
POST -> releer -> borrar) pero **con todas las lineas redirigidas a DF**, la
unica tabla vacia del ERP. Sirve para medir dos cosas antes de tocar datos
reales:

* que porcentaje de lineas se inserta sin error, y
* que campos se auto-rellenan o descartan lo enviado (``Saldo inicial``,
  ``Secuencial``, ``Conciliado``).

Al terminar borra TODO lo que creo, asi que DF vuelve a quedar como estaba.

    python tools/ensayo_df.py <ruta_csv>              # simulacion
    python tools/ensayo_df.py <ruta_csv> --execute
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                          # noqa: E402
from bfi.logging_setup import configurar_logger                 # noqa: E402
from bfi.mapping import agrupar_por_tabla, leer_csv             # noqa: E402
from bfi.ninox_writer import EscritorNinox                      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--tabla", default=config.TABLA_TEST)
    ap.add_argument("--sin-corregir", action="store_true")
    args = ap.parse_args()

    log = configurar_logger(consola=True)
    if args.tabla != config.TABLA_TEST:
        raise SystemExit("Este ensayo solo escribe en %s." % config.TABLA_TEST)

    filas = leer_csv(args.csv)
    grupos = agrupar_por_tabla(filas)
    print("Lineas por tabla segun cuenta_no:",
          {t: len(v) for t, v in sorted(grupos.items())})
    todas = [f for t in sorted(grupos) for f in grupos[t]]
    print("Total de lineas del CSV:", len(todas))

    escritor = EscritorNinox(aviso=lambda m: None)
    ok, mensaje = escritor.comprobar_conexion()
    print(mensaje)
    if not ok:
        return 2

    # Se usan las DOS tablas de prueba posibles: DF replica TD. Si hiciera falta
    # validar el mapeo de OD/PD se haria aqui, sin escribir en datos reales.
    destino = {args.tabla: todas}

    if not args.execute:
        resultado = escritor.insertar(destino, simular=True, omitir_duplicados=False)
        print("\nSIMULACION:", resultado.resumen_texto())
        return 0

    resultado = escritor.insertar(destino, simular=False, omitir_duplicados=False,
                                  verificar=True, corregir=not args.sin_corregir)
    print("\n" + resultado.resumen_texto())
    for t in resultado.tablas:
        print("\nErrores (%d):" % len(t.errores))
        for e in t.errores[:20]:
            print("   ", e)
        print("\nCorregidos con un segundo envio (%d):" % len(t.corregidos))
        for c in t.corregidos[:5]:
            print("   ", c)
        print("\nCampos que Ninox no dejo escribir (%d):" % len(t.discrepancias))
        for d in t.discrepancias[:8]:
            print("   ", d)

    # --- Limpieza: DF debe quedar exactamente como estaba ---
    print("\nBorrando los %d registros creados..." % len(resultado.tablas[0].ids_creados))
    fallos = 0
    for rid in resultado.tablas[0].ids_creados:
        st, _ = escritor.cli.delete_record(args.tabla, rid)
        if st != 200:
            fallos += 1
            print("   !! no se pudo borrar el id %s (HTTP %s)" % (rid, st))
    print("Limpieza terminada. Fallos:", fallos)
    return 0 if fallos == 0 and not resultado.erroneos else 1


if __name__ == "__main__":
    raise SystemExit(main())
