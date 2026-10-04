"""Puente con el pipeline de BFI que ya usa la aplicacion de escritorio.

Aqui no se reimplementa nada: se llama a ``bfi.extractor``, ``bfi.mapping`` y
``bfi.ninox_writer``, que son los mismos modulos que usa la ventana. La unica
diferencia es que el agente pasa de la comprobacion de duplicados leyendo el
CSV que acaba de generar en su propia carpeta de trabajo.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from bfi import config as bfi_config
from bfi.credentials import get_credential
from bfi.extractor import procesar_pdfs
from bfi.mapping import ErrorDeMapeo, agrupar_por_tabla, clave_duplicado
from bfi.ninox_writer import EscritorNinox, ResultadoProceso


class ErrorProcesamiento(Exception):
    """Fallo al interpretar los PDFs o al hablar con el ERP."""


def marcar_repetidas_del_lote(grupos: Dict[str, List[Dict[str, Any]]]) -> int:
    """Marca como duplicadas las lineas repetidas **dentro del propio lote**.

    ``marcar_duplicados`` compara cada linea con lo que ya hay en Ninox, no con
    las demas lineas que se estan enviando en esta misma pasada. Al enviar todo
    el lote de una vez eso importa: si dos correos distintos traen el mismo
    movimiento (dos PDFs con contenido distinto pero la misma linea), sin esto
    entraria dos veces.

    Devuelve cuantas lineas se han marcado.
    """
    repetidas = 0
    for filas in grupos.values():
        vistas: set = set()
        for fila in filas:
            if fila.get("_duplicado"):
                continue
            try:
                clave = clave_duplicado(fila)
            except ErrorDeMapeo:
                continue
            if clave in vistas:
                fila["_duplicado"] = True
                fila["_motivo"] = "linea repetida dentro del mismo lote"
                repetidas += 1
            else:
                vistas.add(clave)
    return repetidas


class ProcesadorBfi:
    """Extrae los movimientos de los PDFs y los envia a Ninox."""

    def __init__(self, log: Optional[Callable[[str], None]] = None,
                 verificar: bool = True, pausa: float = 0.0) -> None:
        self.log = log or (lambda texto: None)
        self.verificar = verificar
        self.pausa = pausa

    # --------------------------------------------------------- disponibilidad
    @staticmethod
    def credenciales_presentes() -> Tuple[bool, str]:
        """Comprueba las variables de entorno de Ninox sin llamar a la API."""
        faltan = [nombre for nombre in bfi_config.ENV_VARS if not get_credential(nombre)]
        if faltan:
            return False, "faltan las credenciales: " + ", ".join(faltan)
        return True, "credenciales de Ninox presentes"

    # ------------------------------------------------------------- extraccion
    def extraer(self, rutas_pdf: List[str], ruta_csv: Any) -> List[Dict[str, Any]]:
        """Extrae los movimientos y escribe el CSV. Un PDF ilegible no aborta."""
        return procesar_pdfs(list(rutas_pdf), str(ruta_csv), aviso=self.log)

    # --------------------------------------------------------------- envio
    def enviar(self, filas: List[Dict[str, Any]], simular: bool = True,
               al_agrupar: Optional[Callable[[Dict[str, List[Dict[str, Any]]]], None]] = None
               ) -> ResultadoProceso:
        """Agrupa y envia (o simula el envio) a Ninox, descartando duplicados.

        ``al_agrupar`` recibe los grupos ya ordenados por ``fecha_valor`` y
        anotados con ``_duplicado``. El pipeline lo usa para poder repartir el
        resultado de cada tabla entre los correos que la alimentaron.
        """
        grupos = agrupar_por_tabla(filas)          # lanza ErrorDeMapeo si hay cuentas raras
        if not grupos:
            return ResultadoProceso(simulado=simular,
                                    abortado="No hay filas que enviar a Ninox.")
        escritor = EscritorNinox(aviso=self.log, pausa_entre_envios=self.pausa)
        # detectar_duplicados necesita credenciales y red; el pipeline solo llama
        # aqui cuando ya ha confirmado que las hay.
        grupos = escritor.detectar_duplicados(grupos)
        repetidas = marcar_repetidas_del_lote(grupos)
        if repetidas:
            self.log("   %d linea(s) repetidas dentro del mismo lote: no se envian."
                     % repetidas)
        if al_agrupar is not None:
            al_agrupar(grupos)
        return escritor.insertar(
            grupos,
            simular=simular,
            omitir_duplicados=True,
            verificar=self.verificar and not simular,
        )


__all__ = ["ErrorDeMapeo", "ErrorProcesamiento", "ProcesadorBfi"]
