"""Linea de comandos del agente.

Por defecto **no escribe nada**: si no se dice lo contrario, el agente trabaja en
modo simulacion. Para que inserte de verdad en Ninox hay que pedirlo con
``--real``, y esa decision no deberia tomarse por accidente desde una tarea
programada.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from bfi.logging_setup import configurar_logger

from . import NOMBRE, VERSION
from .config import NOMBRE_FICHERO, ConfigAgente, ErrorConfiguracion
from .correo import ErrorFuenteCorreos, FuenteSimulada
from .correo.fuente_outlook_com import FuenteOutlookCom, outlook_disponible
from .pipeline import ejecutar
from .procesador import ProcesadorBfi

SALIDA_OK = 0
SALIDA_INCIDENCIAS = 1
SALIDA_ABORTADO = 2


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bfi_agente",
        description="%s: revisa una carpeta de Outlook y procesa los adjuntos "
                    "de BFI hacia el ERP." % NOMBRE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Ejemplos:\n"
            "  python -m bfi_agente --comprobar\n"
            "  python -m bfi_agente --listar-carpetas\n"
            "  python -m bfi_agente --dry-run\n"
            "  python -m bfi_agente --dry-run --simulado pruebas\\correos\n"
            "  python -m bfi_agente --real\n"
        ),
    )
    parser.add_argument("--config", metavar="RUTA",
                        help="fichero de configuracion (por defecto %s)" % NOMBRE_FICHERO)
    modo = parser.add_mutually_exclusive_group()
    modo.add_argument("--dry-run", action="store_true", default=None,
                      help="no escribe en Ninox ni mueve correos (por defecto)")
    modo.add_argument("--real", action="store_true",
                      help="inserta de verdad en Ninox y marca los correos")
    parser.add_argument("--desde", metavar="AAAA-MM-DD",
                        help="revisar desde esta fecha, en lugar de usar dias_atras")
    parser.add_argument("--simulado", metavar="CARPETA",
                        help="usar correos de ejemplo de una carpeta local en vez "
                             "de Outlook")
    parser.add_argument("--listar-carpetas", action="store_true",
                        help="mostrar las carpetas del buzon y salir")
    parser.add_argument("--comprobar", action="store_true",
                        help="comprobar configuracion, Outlook y Ninox, y salir")
    parser.add_argument("--no-marcar", action="store_true",
                        help="procesar los correos pero no ponerles categoria, ni "
                             "marcarlos como leidos, ni moverlos (util para una "
                             "prueba contra el buzon real)")
    parser.add_argument("--mostrar-resumen", action="store_true",
                        help="en simulacion, abrir el correo de resumen en pantalla")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="mostrar tambien el detalle en la consola")
    parser.add_argument("--version", action="version",
                        version="%s %s" % (NOMBRE, VERSION))
    return parser


def _fecha(texto: Optional[str]) -> Optional[datetime]:
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto.strip(), formato)
        except ValueError:
            continue
    raise SystemExit("Fecha no valida: %s (se espera AAAA-MM-DD)" % texto)


def _cargar_config(ruta: Optional[str], log) -> ConfigAgente:
    cfg = ConfigAgente.cargar(ruta)
    if cfg.ruta_origen is None:
        log("AVISO: no existe el fichero de configuracion; se usan los valores "
            "por defecto. Copia agente_correo.ejemplo.json a %s y ajustalo."
            % NOMBRE_FICHERO)
    else:
        log("Configuracion: %s" % cfg.ruta_origen)
    cfg.validar()
    return cfg


def _abrir_sin_carpeta(cfg: ConfigAgente, log) -> Optional[FuenteOutlookCom]:
    """Abre Outlook **sin** exigir que exista la carpeta configurada.

    Es lo que hace falta para diagnosticar: si la carpeta vigilada no existe (o
    esta mal escrita), lo util es poder listar las que si existen en lugar de
    quedarse con un error.
    """
    fuente = FuenteOutlookCom(carpeta="", log=log)
    try:
        fuente.abrir()
    except ErrorFuenteCorreos as exc:
        log("ERROR: %s" % exc)
        return None
    return fuente


def _comprobar_carpeta(fuente: FuenteOutlookCom, ruta: str, log) -> bool:
    try:
        carpeta = fuente.resolver_carpeta(ruta)
    except ErrorFuenteCorreos as exc:
        log("  ERROR: %s" % exc)
        return False
    try:
        cuantos = int(carpeta.Items.Count)
    except Exception:                                     # noqa: BLE001
        cuantos = -1
    log("  carpeta '%s' localizada: %d elemento(s)" % (ruta, cuantos))
    return True


def _preflight(cfg: ConfigAgente, log) -> int:
    problemas = 0
    log("Comprobando la configuracion...")
    log("  Carpeta vigilada ......... %s" % cfg.carpeta_outlook)
    log("  Carpeta de procesados .... %s" % (cfg.carpeta_procesados or "(no se mueve el correo)"))
    log("  Remitentes permitidos .... %s"
        % (", ".join(cfg.remitentes_permitidos) or "(cualquiera: conviene restringirlo)"))
    log("  Patron de adjunto ........ %s" % cfg.patron_adjunto)
    log("  Dias hacia atras ......... %d" % cfg.dias_atras)

    log("Comprobando Outlook...")
    ok, mensaje = outlook_disponible()
    log("  %s" % mensaje)
    if not ok:
        problemas += 1
    else:
        fuente = _abrir_sin_carpeta(cfg, log)
        if fuente is None:
            problemas += 1
        else:
            try:
                if not _comprobar_carpeta(fuente, cfg.carpeta_outlook, log):
                    problemas += 1
                if cfg.carpeta_procesados:
                    _comprobar_carpeta(fuente, cfg.carpeta_procesados, log)
            finally:
                fuente.cerrar()

    log("Comprobando Ninox...")
    ok_ninox, mensaje_ninox = ProcesadorBfi.credenciales_presentes()
    log("  %s" % mensaje_ninox)
    if not ok_ninox:
        problemas += 1

    log("Comprobando carpetas de trabajo...")
    for ruta in (cfg.carpeta_trabajo_abs, cfg.ruta_estado_abs.parent):
        try:
            ruta.mkdir(parents=True, exist_ok=True)
            log("  escribible: %s" % ruta)
        except OSError as exc:
            problemas += 1
            log("  ERROR: no se puede escribir en %s: %s" % (ruta, exc))

    log("")
    if problemas:
        log("Comprobacion terminada con %d problema(s)." % problemas)
    else:
        log("Comprobacion terminada: todo listo.")
    return SALIDA_OK if problemas == 0 else SALIDA_INCIDENCIAS


def _listar_carpetas(cfg: ConfigAgente, log) -> int:
    fuente = _abrir_sin_carpeta(cfg, log)
    if fuente is None:
        return SALIDA_ABORTADO
    try:
        log("Carpetas disponibles en el buzon (hasta 3 niveles):")
        for linea in fuente.listar_carpetas():
            log("  %s" % linea)
        log("")
        log("La carpeta configurada es: %s" % cfg.carpeta_outlook)
        return SALIDA_OK if _comprobar_carpeta(fuente, cfg.carpeta_outlook, log) \
            else SALIDA_INCIDENCIAS
    finally:
        fuente.cerrar()


def main(argv: Optional[List[str]] = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    logger = configurar_logger("bfi_agente", consola=True,
                               nivel=10 if args.verbose else 20)

    def log(texto: str) -> None:
        logger.info(texto)

    try:
        cfg = _cargar_config(args.config, log)
    except ErrorConfiguracion as exc:
        print("ERROR de configuracion:\n%s" % exc, file=sys.stderr)
        return SALIDA_ABORTADO

    if args.comprobar:
        return _preflight(cfg, log)
    if args.listar_carpetas:
        return _listar_carpetas(cfg, log)

    simular = not args.real
    fuente = None
    if args.simulado:
        try:
            fuente = FuenteSimulada.desde_directorio(args.simulado, log=log)
        except ErrorFuenteCorreos as exc:
            print("ERROR: %s" % exc, file=sys.stderr)
            return SALIDA_ABORTADO
        log("Usando correos de ejemplo de %s (%d mensaje(s))"
            % (args.simulado, len(fuente.mensajes)))

    try:
        informe = ejecutar(cfg, simular=simular, desde=_fecha(args.desde),
                           fuente=fuente, log=log, marcar=not args.no_marcar,
                           mostrar_resumen=args.mostrar_resumen)
    except ErrorConfiguracion as exc:
        print("ERROR de configuracion:\n%s" % exc, file=sys.stderr)
        return SALIDA_ABORTADO

    print("")
    print(informe.texto())
    if informe.abortado:
        return SALIDA_ABORTADO
    return SALIDA_INCIDENCIAS if informe.errores else SALIDA_OK


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(main())
