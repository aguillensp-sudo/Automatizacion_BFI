"""Linea de comandos de la aplicacion BFI.

La interfaz grafica es el camino normal, pero esto permite ejecutar el mismo
proceso desde una consola (util para depurar o para dejarlo programado):

    python main.py                       # abre la interfaz grafica
    python main.py extraer  <carpeta>    # solo genera el CSV
    python main.py simular  <carpeta>    # genera el CSV y muestra que enviaria
    python main.py insertar <carpeta> --confirmar

``insertar`` exige escribir ``--confirmar``: es una escritura real en el ERP,
sin transacciones y sin deshacer.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bfi import APP_NAME, __version__, config
from bfi.extractor import listar_pdfs, procesar_pdfs
from bfi.logging_setup import configurar_logger
from bfi.mapping import ErrorDeMapeo, agrupar_por_tabla, leer_csv
from bfi.ninox_writer import EscritorNinox


def _preparar(carpeta: str, log) -> tuple:
    """Extrae los PDFs y devuelve (ruta_csv, grupos por tabla)."""
    if not Path(carpeta).is_dir():
        raise SystemExit("La carpeta no existe: %s" % carpeta)
    pdfs = listar_pdfs(carpeta)
    if not pdfs:
        raise SystemExit("No hay ficheros .pdf en %s" % carpeta)
    log.info("%d PDF(s) encontrados.", len(pdfs))

    ruta_csv = str(Path(carpeta) / config.CSV_BASENAME)
    procesar_pdfs(pdfs, ruta_csv, aviso=log.info)
    grupos = agrupar_por_tabla(leer_csv(ruta_csv))
    for tabla in sorted(grupos):
        log.info("%s: %d linea(s)", config.TABLA_A_ETIQUETA.get(tabla, tabla),
                 len(grupos[tabla]))
    return ruta_csv, grupos


def cmd_extraer(args, log) -> int:
    ruta_csv, _ = _preparar(args.carpeta, log)
    print("CSV generado: %s" % ruta_csv)
    return 0


def cmd_simular(args, log) -> int:
    _, grupos = _preparar(args.carpeta, log)
    escritor = EscritorNinox(aviso=log.info)
    ok, mensaje = escritor.comprobar_conexion()
    log.info(mensaje)
    if not ok:
        return 2
    grupos = escritor.detectar_duplicados(grupos)
    resultado = escritor.insertar(grupos, simular=True,
                                  omitir_duplicados=not args.incluir_duplicados)
    print(resultado.resumen_texto())
    return 0


def cmd_insertar(args, log) -> int:
    if not args.confirmar:
        raise SystemExit(
            "Escritura real en el ERP Ninox. Repite el comando con --confirmar.\n"
            "Tablas destino: OD (BFI 05399610), PD (BFI 06074740), TD (BFI 61020).\n"
            "Para ensayar sin tocar datos reales, anade --tabla-test.")
    ruta_csv, grupos = _preparar(args.carpeta, log)
    escritor = EscritorNinox(aviso=log.info)
    ok, mensaje = escritor.comprobar_conexion()
    log.info(mensaje)
    if not ok:
        return 2
    if args.tabla_test:
        log.warning("ENSAYO: se escribe en %s en lugar de en las tablas reales.",
                    config.TABLA_A_ETIQUETA.get(config.TABLA_TEST, config.TABLA_TEST))
        grupos = {config.TABLA_TEST: [f for filas in grupos.values() for f in filas]}
    grupos = escritor.detectar_duplicados(grupos)
    resultado = escritor.insertar(grupos, simular=False,
                                  omitir_duplicados=not args.incluir_duplicados,
                                  verificar=True,
                                  corregir=not args.sin_corregir)
    print(resultado.resumen_texto())
    for tabla in resultado.tablas:
        for err in tabla.errores:
            print("   ERROR %s %s" % (tabla.tabla, err))
        for cor in tabla.corregidos:
            print("   CORREGIDO %s" % cor)
        for disc in tabla.discrepancias:
            print("   AVISO %s" % disc)
    if resultado.insertados and not args.conservar_csv and resultado.erroneos == 0:
        try:
            Path(ruta_csv).unlink()
            print("CSV eliminado: %s" % ruta_csv)
        except OSError as exc:
            print("No se pudo borrar el CSV: %s" % exc)
    elif resultado.erroneos:
        print("El CSV se conserva en %s porque hubo lineas con error." % ruta_csv)
    return 0 if resultado.erroneos == 0 else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="BFI", description="%s v%s — extractos del Banco Financiero" % (APP_NAME, __version__))
    sub = parser.add_subparsers(dest="comando")

    p = sub.add_parser("extraer", help="solo genera el CSV (no usa Ninox)")
    p.add_argument("carpeta")
    p.set_defaults(func=cmd_extraer)

    p = sub.add_parser("simular", help="genera el CSV y muestra que se enviaria")
    p.add_argument("carpeta")
    p.add_argument("--incluir-duplicados", action="store_true")
    p.set_defaults(func=cmd_simular)

    p = sub.add_parser("insertar", help="inserta de verdad en Ninox")
    p.add_argument("carpeta")
    p.add_argument("--confirmar", action="store_true")
    p.add_argument("--incluir-duplicados", action="store_true")
    p.add_argument("--conservar-csv", action="store_true")
    p.add_argument("--sin-corregir", action="store_true",
                   help="no reintentar con un PUT los campos que Ninox descarte "
                        "en el alta")
    p.add_argument("--tabla-test", action="store_true",
                   help="ensayo: escribe todas las lineas en la tabla %s, no en "
                        "las tablas reales" % config.TABLA_TEST)
    p.set_defaults(func=cmd_insertar)

    args = parser.parse_args(argv)
    if not args.comando:
        from bfi.gui import main as gui_main
        return gui_main()

    log = configurar_logger(consola=True)
    try:
        return args.func(args, log)
    except (ErrorDeMapeo, EnvironmentError) as exc:
        log.error("%s", exc)
        print("\n%s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
