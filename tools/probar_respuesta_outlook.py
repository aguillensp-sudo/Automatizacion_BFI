"""Comprueba que Outlook puede preparar una respuesta, SIN enviarla.

Es la parte del agente que mas depende del entorno: crear una respuesta usa el
modelo de objetos de Outlook y, segun la configuracion de seguridad del equipo,
Outlook puede pedir confirmacion (o bloquear el envio). Mejor saberlo un martes
por la tarde que un lunes a las 11:00.

Lo que hace, exactamente:

1. Abre la carpeta configurada y coge el correo mas reciente que cumpla el filtro.
2. Prepara la respuesta (``Reply``) y muestra a quien iria dirigida.
3. **La descarta sin enviarla.** Este programa no envia correo nunca.

Uso:
    python tools/probar_respuesta_outlook.py
    python tools/probar_respuesta_outlook.py --config agente_correo.json
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bfi_agente.config import ConfigAgente                     # noqa: E402
from bfi_agente.correo import (ErrorFuenteCorreos,              # noqa: E402
                               FiltroMensajes, FuenteOutlookCom)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", metavar="RUTA",
                        help="fichero de configuracion del agente")
    args = parser.parse_args()

    cfg = ConfigAgente.cargar(args.config)
    patron_adjunto, patron_asunto = cfg.compilar_patrones()
    filtro = FiltroMensajes(remitentes=list(cfg.remitentes_permitidos),
                            patron_adjunto=patron_adjunto,
                            patron_asunto=patron_asunto)

    fuente = FuenteOutlookCom(carpeta=cfg.carpeta_outlook, log=print)
    try:
        fuente.abrir()
        pendientes = fuente.listar_pendientes(filtro)
        if not pendientes:
            print("No hay ningun correo que cumpla el filtro en '%s'."
                  % cfg.carpeta_outlook)
            return 1
        mensaje = pendientes[0]
        print("Correo de prueba: %s" % mensaje.etiqueta())

        item = fuente._item(mensaje)                              # noqa: SLF001
        respuesta = item.Reply()
        try:
            print("  Destinatario de la respuesta: %s" % str(respuesta.To or "(vacio)"))
            print("  Asunto ...................... %s" % str(respuesta.Subject or "(vacio)"))
            print("  Cuerpo preparado por Outlook . %d caracteres"
                  % len(str(respuesta.Body or "")))
            print("")
            print("La respuesta se ha creado correctamente.")
            print("Se descarta ahora mismo: NO se ha enviado nada.")
        finally:
            try:
                respuesta.Close(1)          # 1 = olDiscard
            except Exception:               # noqa: BLE001
                respuesta.Delete()
        return 0
    except ErrorFuenteCorreos as exc:
        print("ERROR: %s" % exc)
        return 2
    except Exception as exc:                                      # noqa: BLE001
        print("ERROR inesperado al preparar la respuesta: %s" % exc)
        print("Si Outlook ha mostrado un aviso pidiendo permiso, ese es el "
              "problema: la ejecucion desatendida se quedaria esperando.")
        return 2
    finally:
        fuente.cerrar()


if __name__ == "__main__":
    raise SystemExit(main())
