"""Pipeline del agente: de la carpeta de correo al ERP.

El trabajo se hace en tres fases, y el orden no es un capricho:

1. **Preparacion**, correo a correo: descargar adjuntos, extraer las lineas y
   descartar lo que ya se proceso antes.
2. **Envio, UNA sola vez para todo el lote**: las lineas de todos los correos se
   juntan, se agrupan por tabla y se ordenan por ``fecha_valor`` de la mas antigua
   a la mas reciente **antes** de insertar.
3. **Cierre**, correo a correo: registrar el estado, responder al remitente y
   marcar el correo.

El paso 2 no se puede hacer correo a correo, y este es el motivo: la formula de
Ninox que calcula *Saldo inicial* encadena cada registro con el **anterior por
Secuencial**, o sea, con el ultimo que se inserto. Si un correo trae movimientos
del dia 18 y otro correo trae uno del dia 15, insertar por correos deja el del 15
al final de la cadena y **descuadra todos los saldos siguientes**. Se detecto en
la prueba del 24/09/2026 contra JI-PRUEBAS-CLAUDE: los tres movimientos del dia
18 entraron primero y el del dia 15 despues.

De ahi salen las dos reglas que sostienen todo lo demas:

* **Un correo solo se da por procesado si su envio fue limpio.** Si hubo errores
  no se registra ni se marca: el lunes siguiente se reintenta. Reenviar es barato
  (Ninox descarta duplicados); perder movimientos, no.
* **Nada se da por procesado si no se extrajo ni una linea.** Un PDF que se lee
  pero no produce movimientos se trata como error, no como "sin datos": casi
  siempre significa que el formato del extracto ha cambiado.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from bfi import config as bfi_config

from .config import ConfigAgente
from .correo import (ErrorFuenteCorreos, FiltroMensajes, FuenteCorreos,
                     FuenteOutlookCom, MensajeCorreo)
from .correo.fuente_outlook_com import limpiar_nombre
from .estado import Estado, hash_archivo
from .procesador import ErrorDeMapeo, ErrorProcesamiento, ProcesadorBfi
from .resumen import (ESTADO_ERROR, ESTADO_OK, ESTADO_OMITIDO, ESTADO_SIN_DATOS,
                      EnviadorResumen, EnviadorResumenOutlook, InformeEjecucion,
                      ResultadoCorreo)

NombreLog = Callable[[str], None]

# Los mensajes de error de ``EscritorNinox`` empiezan por "fila N: ...". Ese N es
# la posicion de la fila en la lista que se le entrego, que es la misma lista que
# se le paso a ``enviar``; sirve para saber a que correo pertenece cada error.
PATRON_ERROR_FILA = re.compile(r"^fila (\d+):\s*(.*)$", re.S)


def marca_de_ejecucion(momento: Optional[datetime] = None) -> str:
    """Marca de tiempo para nombrar la carpeta de trabajo de una ejecucion."""
    return (momento or datetime.now()).strftime("%Y-%m-%d_%H%M")


def _sin_acentos(texto: str) -> str:
    """Quita los acentos: el nombre de la carpeta acabara siendo una ruta."""
    origen = "\u00e1\u00e9\u00ed\u00f3\u00fa\u00c1\u00c9\u00cd\u00d3\u00da\u00f1\u00d1\u00fc\u00dc"
    destino = "aeiouAEIOUnNuU"
    return texto.translate(str.maketrans(origen, destino))


def _indices_erroneos(errores: List[str]) -> Dict[int, str]:
    """De ``["fila 3: ..."]`` a ``{3: "..."}``. Lo que no encaje se ignora."""
    salida: Dict[int, str] = {}
    for texto in errores:
        coincidencia = PATRON_ERROR_FILA.match(texto.strip())
        if coincidencia:
            salida[int(coincidencia.group(1))] = coincidencia.group(2).strip()
    return salida


class Agente:
    """Orquesta una pasada completa del agente."""

    def __init__(self, config: ConfigAgente, simular: bool = True,
                 fuente: Optional[FuenteCorreos] = None,
                 procesador: Optional[Any] = None,
                 marcar: bool = True,
                 log: Optional[NombreLog] = None) -> None:
        self.cfg = config
        self.simular = simular
        # Con ``marcar=False`` el agente procesa el correo pero no lo toca: ni
        # categoria, ni leido, ni movimiento de carpeta, ni respuesta. Es lo que
        # se quiere al hacer una prueba contra el buzon real.
        self.marcar = marcar
        self.log: NombreLog = log or (lambda texto: None)
        self.fuente = fuente
        self.fuente_propia = fuente is None
        self.procesador = procesador or ProcesadorBfi(log=self.log)
        self.estado = Estado(config.ruta_estado_abs, persistir=not simular)
        self.patron_adjunto, self.patron_asunto = config.compilar_patrones()

    # ------------------------------------------------------------------ pasada
    def ejecutar(self, desde: Optional[datetime] = None, marca: Optional[str] = None,
                 mostrar_resumen: bool = False,
                 enviador: Optional[Any] = None) -> InformeEjecucion:
        cfg = self.cfg
        inicio = datetime.now()
        marca = marca or marca_de_ejecucion(inicio)
        corte = desde or (inicio - timedelta(days=int(cfg.dias_atras)))
        informe = InformeEjecucion(
            modo="simulacion" if self.simular else "real",
            fuente=getattr(self.fuente, "nombre", "Outlook (COM)"),
            carpeta=cfg.carpeta_outlook,
            inicio=inicio,
        )
        filtro = FiltroMensajes(desde=corte,
                                remitentes=list(cfg.remitentes_permitidos),
                                patron_adjunto=self.patron_adjunto,
                                patron_asunto=self.patron_asunto)
        self.log("Modo: %s" % informe.modo.upper())
        self.log("Correos desde %s (dias_atras=%d)"
                 % (corte.strftime("%Y-%m-%d %H:%M"), cfg.dias_atras))
        if not cfg.remitentes_permitidos:
            self.log("AVISO: no hay remitentes_permitidos; se acepta cualquier remitente.")

        # --- Ninox disponible? Sin credenciales se extrae pero no se envia ---
        ninox_ok, motivo = True, ""
        comprobar = getattr(self.procesador, "credenciales_presentes", None)
        if callable(comprobar):
            ninox_ok, motivo = comprobar()
        if not ninox_ok:
            informe.ninox_omitido = motivo
            self.log("AVISO: %s. Se extraeran los PDFs, pero no se enviara nada "
                     "a Ninox y los correos NO se daran por procesados." % motivo)

        carpeta_ejecucion = cfg.carpeta_de_ejecucion(marca)
        id_ejecucion = self.estado.iniciar_ejecucion(informe.modo)

        if self.fuente is None:
            self.fuente = FuenteOutlookCom(
                carpeta=cfg.carpeta_outlook,
                carpeta_procesados=cfg.carpeta_procesados,
                categoria=cfg.categoria_procesada,
                max_correos=cfg.max_correos,
                log=self.log,
            )

        try:
            self.fuente.abrir()
            pendientes = self.fuente.listar_pendientes(filtro)
            self.log("%d correo(s) pendiente(s) tras aplicar el filtro." % len(pendientes))
            if not pendientes:
                self.log("No hay nada que procesar.")

            # --- Fase 1: preparacion -------------------------------------
            preparados: List[Tuple[MensajeCorreo, ResultadoCorreo, List[Any], List[Dict[str, Any]]]] = []
            for mensaje in pendientes:
                self.log("")
                self.log("- %s" % mensaje.etiqueta())
                resultado, utiles, filas = self._preparar(mensaje, filtro,
                                                          carpeta_ejecucion, ninox_ok)
                informe.resultados.append(resultado)
                if filas:
                    preparados.append((mensaje, resultado, utiles, filas))

            # --- Fase 2: un unico envio, ordenado por fecha ----------------
            if preparados:
                self._enviar_lote(preparados, informe, ninox_ok)

            # --- Fase 3: cierre de cada correo ----------------------------
            for mensaje, resultado, utiles, _filas in preparados:
                self._cerrar(mensaje, resultado, utiles, ninox_ok)
                self.log("   -> %s (%s)" % (resultado.estado,
                                            "; ".join(resultado.notas) or "sin incidencias"))
        except ErrorFuenteCorreos as exc:
            informe.abortado = str(exc)
            self.log("ERROR: %s" % exc)
        except Exception as exc:                          # noqa: BLE001
            informe.abortado = "Fallo inesperado al leer el buzon: %s" % exc
            self.log("ERROR inesperado: %s" % exc)
        finally:
            try:
                self.fuente.cerrar()
            except Exception:                             # noqa: BLE001
                pass

        informe.fin = datetime.now()
        self.estado.cerrar_ejecucion(id_ejecucion, correos=informe.correos,
                                     adjuntos=informe.adjuntos,
                                     insertados=informe.insertados,
                                     errores=informe.errores,
                                     resumen=informe.asunto())
        self.estado.cerrar()
        self._entregar_resumen(informe, mostrar_resumen, enviador)
        return informe

    # ------------------------------------------------------ fase 1: preparar
    def _preparar(self, mensaje: MensajeCorreo, filtro: FiltroMensajes,
                  carpeta_ejecucion: Path, ninox_ok: bool
                  ) -> Tuple[ResultadoCorreo, List[Any], List[Dict[str, Any]]]:
        """Descarga y extrae un correo. Devuelve las filas, sin enviar nada."""
        cfg = self.cfg
        resultado = ResultadoCorreo(etiqueta=mensaje.etiqueta(), clave=mensaje.clave)

        previo = self.estado.correo_procesado(mensaje.clave, mensaje.internet_message_id)
        if previo:
            resultado.estado = ESTADO_OMITIDO
            resultado.notas.append("ya se proceso el %s (%s)"
                                   % (previo.get("procesado_en") or "?", previo.get("resultado") or ""))
            return resultado, [], []

        carpeta = carpeta_ejecucion / limpiar_nombre(_sin_acentos(mensaje.asunto or "correo"), 60)
        resultado.carpeta = str(carpeta)

        # --- 1. Descarga de adjuntos ---------------------------------------
        try:
            descargados = self.fuente.descargar_adjuntos(mensaje, carpeta, filtro)
        except ErrorFuenteCorreos as exc:
            resultado.estado = ESTADO_ERROR
            resultado.notas.append(str(exc))
            return resultado, [], []
        if not descargados:
            resultado.estado = ESTADO_SIN_DATOS
            resultado.notas.append("el correo no traia adjuntos que interesen")
            return resultado, [], []

        # --- 2. Adjuntos ya vistos (el mismo PDF reenviado) -----------------
        utiles = []
        for adjunto in descargados:
            try:
                adjunto.hash = hash_archivo(adjunto.ruta)
            except OSError as exc:
                resultado.notas.append("no se pudo leer %s: %s" % (adjunto.nombre, exc))
                continue
            if cfg.evitar_adjuntos_repetidos:
                visto = self.estado.adjunto_conocido(adjunto.hash)
                if visto:
                    resultado.adjuntos_repetidos += 1
                    resultado.notas.append(
                        "adjunto ya procesado antes: %s (%s)"
                        % (adjunto.nombre, visto.get("procesado_en") or "?"))
                    continue
            utiles.append(adjunto)
        resultado.adjuntos = len(utiles)
        if not utiles:
            resultado.estado = ESTADO_OMITIDO
            resultado.notas.insert(0, "todos los adjuntos de este correo ya se procesaron")
            return resultado, [], []

        # --- 3. Extraccion --------------------------------------------------
        ruta_csv = carpeta / bfi_config.CSV_BASENAME
        try:
            filas = self.procesador.extraer([a.ruta for a in utiles], ruta_csv)
        except Exception as exc:                          # noqa: BLE001
            resultado.estado = ESTADO_ERROR
            resultado.notas.append("fallo al extraer los PDFs: %s" % exc)
            return resultado, utiles, []
        resultado.filas = len(filas)
        if not filas:
            resultado.estado = ESTADO_ERROR
            resultado.notas.append(
                "no se extrajo ninguna linea de %d PDF(s); puede que el formato "
                "del extracto haya cambiado" % len(utiles))
            resultado.notas.append("CSV en %s" % ruta_csv)
            return resultado, utiles, []

        if not ninox_ok:
            resultado.notas.append("Ninox omitido; CSV en %s" % ruta_csv)
        return resultado, utiles, filas

    # --------------------------------------------------------- fase 2: envio
    def _enviar_lote(self,
                     preparados: List[Tuple[MensajeCorreo, ResultadoCorreo,
                                            List[Any], List[Dict[str, Any]]]],
                     informe: InformeEjecucion, ninox_ok: bool) -> None:
        """Inserta **de una vez** las lineas de todos los correos.

        Se marca cada fila con ``_origen`` (la clave del correo) para poder
        repartir despues el resultado de la tabla entre los correos que
        contribuyeron, sin perder de vista que la insercion es unica.
        """
        if not ninox_ok:
            for _mensaje, resultado, _utiles, filas in preparados:
                resultado.notas.append(
                    "%d linea(s) extraida(s) sin enviar: se reintentaran cuando "
                    "haya credenciales de Ninox" % len(filas))
            return

        filas_lote: List[Dict[str, Any]] = []
        por_clave: Dict[str, ResultadoCorreo] = {}
        for _mensaje, resultado, _utiles, filas in preparados:
            por_clave[resultado.clave] = resultado
            for fila in filas:
                copia = dict(fila)
                copia["_origen"] = resultado.clave
                filas_lote.append(copia)

        total = len(filas_lote)
        self.log("")
        self.log("Enviando %d linea(s) de %d correo(s) en un unico lote, "
                 "ordenadas por fecha_valor." % (total, len(preparados)))

        grupos_capturados: Dict[str, List[Dict[str, Any]]] = {}

        def recordar_grupos(grupos: Dict[str, List[Dict[str, Any]]]) -> None:
            grupos_capturados.update(grupos)

        try:
            envio = self.procesador.enviar(filas_lote, simular=self.simular,
                                           al_agrupar=recordar_grupos)
        except ErrorDeMapeo as exc:
            self._marcar_error_de_lote(preparados, str(exc))
            return
        except ErrorProcesamiento as exc:
            self._marcar_error_de_lote(preparados, str(exc))
            return
        except Exception as exc:                          # noqa: BLE001
            self._marcar_error_de_lote(preparados,
                                       "fallo al enviar a Ninox: %s" % exc)
            return

        for tabla in envio.tablas:
            informe.tablas.append(tabla.linea_resumen())
            self.log("   %s" % tabla.linea_resumen())

        self._repartir_resultado(grupos_capturados, envio, por_clave, informe)
        if envio.abortado:
            for resultado in por_clave.values():
                resultado.estado = ESTADO_ERROR
                resultado.notas.append(envio.abortado)

    @staticmethod
    def _marcar_error_de_lote(preparados, motivo: str) -> None:
        for _mensaje, resultado, _utiles, _filas in preparados:
            resultado.estado = ESTADO_ERROR
            resultado.notas.append(motivo)

    def _repartir_resultado(self, grupos: Dict[str, List[Dict[str, Any]]],
                            envio: Any, por_clave: Dict[str, ResultadoCorreo],
                            informe: InformeEjecucion) -> None:
        """Reparte el resultado de cada tabla entre los correos que la alimentaron.

        Los errores se atribuyen por el numero de fila que anota el escritor
        ("fila N: ..."), que es la posicion dentro de la lista que se le paso: esa
        misma lista (ya anotada con ``_origen`` y ``_duplicado``) es la que se
        recorre aqui. Lo que no se pueda atribuir se cuenta aparte, para que los
        totales del informe sigan cuadrando.
        """
        por_tabla = {tabla.tabla: tabla for tabla in envio.tablas}
        for tabla, filas in grupos.items():
            resultado_tabla = por_tabla.get(tabla)
            erroneas = _indices_erroneos(resultado_tabla.errores) if resultado_tabla else {}
            atribuidos = 0
            for numero, fila in enumerate(filas, start=1):
                resultado = por_clave.get(str(fila.get("_origen") or ""))
                if resultado is None:
                    continue
                if fila.get("_duplicado"):
                    resultado.omitidos += 1
                    if fila.get("_motivo"):
                        resultado.notas.append("%s: %s" % (tabla, fila["_motivo"]))
                    continue
                if numero in erroneas:
                    resultado.errores += 1
                    atribuidos += 1
                    resultado.notas.append("%s, fila %d: %s" % (tabla, numero, erroneas[numero]))
                    continue
                resultado.insertados += 1
            if resultado_tabla is not None:
                sin_atribuir = max(0, resultado_tabla.erroneos - atribuidos)
                if sin_atribuir:
                    informe.errores_sin_atribuir += sin_atribuir
                    informe.avisos.append(
                        "%s: %d error(es) que no se pueden asignar a un correo "
                        "concreto (revisa el registro)" % (tabla, sin_atribuir))

    # --------------------------------------------------------- fase 3: cierre
    def _cerrar(self, mensaje: MensajeCorreo, resultado: ResultadoCorreo,
                utiles: List[Any], ninox_ok: bool) -> None:
        """Registra el estado, responde al remitente y marca el correo.

        Solo se llega aqui con correos que trajeron lineas. Se dan por buenos si
        el envio fue limpio; si no, se dejan sin registrar para que el lunes
        siguiente se reintenten.
        """
        if resultado.estado in (ESTADO_ERROR, ESTADO_OMITIDO):
            return
        exito = (ninox_ok and resultado.errores == 0
                 and resultado.estado in (ESTADO_OK, ESTADO_SIN_DATOS))
        if not exito:
            resultado.notas.append(
                "no se registra como procesado: se reintentara en la proxima "
                "ejecucion")
            if self.simular:
                resultado.notas.append("SIMULACION: no se ha escrito nada en Ninox")
            return

        for adjunto in utiles:
            self.estado.registrar_adjunto(adjunto.hash, mensaje.clave,
                                          adjunto.nombre, adjunto.ruta,
                                          adjunto.bytes_)
        self.estado.registrar_correo(mensaje.clave, mensaje.internet_message_id,
                                     mensaje.asunto,
                                     mensaje.direccion or mensaje.remitente,
                                     mensaje.recibido_texto, resultado.estado,
                                     "; ".join(resultado.notas))
        self._responder(mensaje, resultado)
        if self.simular:
            resultado.marcado = "sin marcar (simulacion)"
            resultado.notas.append("en una ejecucion real el correo se marcaria "
                                   "como procesado")
        elif not self.marcar:
            resultado.marcado = "sin marcar (--no-marcar)"
            resultado.notas.append("correo intacto; el estado si queda registrado, "
                                   "asi que no se reprocesara")
        else:
            try:
                resultado.marcado = self.fuente.marcar_procesado(mensaje)
                resultado.notas.append("correo %s" % resultado.marcado)
            except ErrorFuenteCorreos as exc:
                resultado.notas.append("no se pudo marcar el correo: %s" % exc)
        if self.simular:
            resultado.notas.append("SIMULACION: no se ha escrito nada en Ninox")

    # --------------------------------------------------------------- respuesta
    def _responder(self, mensaje: MensajeCorreo, resultado: ResultadoCorreo) -> None:
        """Contesta al remitente si esta configurado.

        Se manda **despues** de registrar el estado: si el envio de la respuesta
        falla, los movimientos ya estan en el ERP y lo unico que queda es la
        anotacion en el informe. Al reves (responder y luego fallar el registro)
        seria peor: el banco tendria un "insertado" que no lo esta.
        """
        cfg = self.cfg
        if not cfg.responder_al_remitente:
            return
        if self.simular:
            resultado.notas.append(
                "respuesta NO enviada (simulacion): \"%s\"" % cfg.texto_respuesta)
            return
        if not self.marcar:
            resultado.notas.append(
                "respuesta NO enviada (--no-marcar): \"%s\"" % cfg.texto_respuesta)
            return
        try:
            resultado.respuesta = self.fuente.responder(mensaje, cfg.texto_respuesta)
        except ErrorFuenteCorreos as exc:
            self.log("   aviso: no se pudo responder al remitente: %s" % exc)
            resultado.notas.append("no se pudo responder al remitente: %s" % exc)
            return
        resultado.notas.append(resultado.respuesta)
        self.log("   %s" % resultado.respuesta)

    # --------------------------------------------------------------- resumen
    def _entregar_resumen(self, informe: InformeEjecucion, mostrar_resumen: bool,
                          enviador: Optional[Any]) -> None:
        cfg = self.cfg
        try:
            escritor = EnviadorResumen(cfg.carpeta_trabajo_abs, log=self.log)
            informe.ruta_resumen = escritor.enviar(informe, [])
        except OSError as exc:
            informe.avisos.append("no se pudo escribir el resumen en disco: %s" % exc)

        if not cfg.resumen_activo:
            informe.enviado_a = "envio desactivado (resumen_activo=false)"
            return
        if self.simular or cfg.resumen_solo_simular:
            if mostrar_resumen and enviador is None:
                enviador = EnviadorResumenOutlook(simular=True, log=self.log)
            if enviador is not None:
                informe.enviado_a = enviador.enviar(informe, cfg.resumen_para)
            else:
                informe.enviado_a = "no enviado (simulacion); queda en %s" % informe.ruta_resumen
            return
        if enviador is None:
            enviador = EnviadorResumenOutlook(simular=False, log=self.log)
        informe.enviado_a = enviador.enviar(informe, cfg.resumen_para)
        self.log("Resumen: %s" % informe.enviado_a)

    # ------------------------------------------------------------------ alias
    def cerrar(self) -> None:
        self.estado.cerrar()


def ejecutar(config: ConfigAgente, simular: bool = True,
             desde: Optional[datetime] = None,
             fuente: Optional[FuenteCorreos] = None,
             procesador: Optional[Any] = None,
             log: Optional[NombreLog] = None,
             marca: Optional[str] = None,
             marcar: bool = True,
             mostrar_resumen: bool = False,
             enviador: Optional[Any] = None) -> InformeEjecucion:
    """Atajo: una pasada completa del agente."""
    agente = Agente(config, simular=simular, fuente=fuente,
                    procesador=procesador, marcar=marcar, log=log)
    try:
        return agente.ejecutar(desde=desde, marca=marca,
                               mostrar_resumen=mostrar_resumen, enviador=enviador)
    finally:
        agente.cerrar()


__all__ = ["Agente", "ejecutar", "marca_de_ejecucion"]
