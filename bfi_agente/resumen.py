"""Informe de la ejecucion y correo de resumen.

El resumen no es un adorno: es la unica forma de que alguien se entere de que el
lunes a las 7:00 algo fallo. Por eso se escribe **siempre** en un fichero,
aunque el envio de correo este desactivado o falle.
"""
from __future__ import annotations

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, List, Optional

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")

ESTADO_OK = "ok"
ESTADO_SIN_DATOS = "sin datos"
ESTADO_OMITIDO = "omitido"
ESTADO_ERROR = "error"


def fecha_larga(momento: Optional[datetime] = None) -> str:
    momento = momento or datetime.now()
    return "%d de %s de %d, %s" % (momento.day, MESES[momento.month - 1],
                                   momento.year, momento.strftime("%H:%M"))


@dataclass
class ResultadoCorreo:
    """Lo que ocurrio con un correo concreto."""

    etiqueta: str
    clave: str = ""
    estado: str = ESTADO_OK
    adjuntos: int = 0
    adjuntos_repetidos: int = 0
    filas: int = 0
    insertados: int = 0
    omitidos: int = 0
    # Lineas que Ninox rechazo. Un fallo del correo entero (no se pudo leer, no
    # se pudo extraer) se refleja en ``estado``, no aqui: asi los totales no
    # cuentan dos veces el mismo problema.
    errores: int = 0
    marcado: str = ""
    respuesta: str = ""
    notas: List[str] = field(default_factory=list)
    carpeta: str = ""

    def linea(self) -> str:
        if self.estado == ESTADO_OK:
            detalle = ("%d adjunto(s), %d movimiento(s), %d insertado(s), "
                       "%d omitido(s) por duplicado"
                       % (self.adjuntos, self.filas, self.insertados, self.omitidos))
            if self.errores:
                detalle += ", %d con error" % self.errores
            if self.respuesta:
                detalle += "; %s" % self.respuesta
        elif self.estado == ESTADO_SIN_DATOS:
            detalle = "sin adjuntos que interesen"
        elif self.estado == ESTADO_OMITIDO:
            detalle = self.notas[0] if self.notas else "ya estaba procesado"
        else:
            detalle = self.notas[0] if self.notas else "error"
        return "  - %s: %s" % (self.etiqueta, detalle)


@dataclass
class InformeEjecucion:
    """Resultado completo de una pasada del agente."""

    modo: str = "simulacion"
    fuente: str = ""
    carpeta: str = ""
    inicio: datetime = field(default_factory=datetime.now)
    fin: Optional[datetime] = None
    resultados: List[ResultadoCorreo] = field(default_factory=list)
    # Resumen por tabla destino ("OD: 3 insertada(s)..."). El envio es un unico
    # lote para todos los correos, asi que el detalle fiable es por tabla.
    tablas: List[str] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)
    abortado: str = ""
    ninox_omitido: str = ""
    ruta_resumen: str = ""
    enviado_a: str = ""
    # Errores de Ninox que no se han podido asignar a un correo concreto: se
    # cuentan aqui para que los totales del informe sigan cuadrando.
    errores_sin_atribuir: int = 0

    # ------------------------------------------------------------- totales
    @property
    def correos(self) -> int:
        return len(self.resultados)

    @property
    def procesados(self) -> int:
        return sum(1 for r in self.resultados if r.estado == ESTADO_OK)

    @property
    def adjuntos(self) -> int:
        return sum(r.adjuntos for r in self.resultados)

    @property
    def filas(self) -> int:
        return sum(r.filas for r in self.resultados)

    @property
    def insertados(self) -> int:
        return sum(r.insertados for r in self.resultados)

    @property
    def omitidos(self) -> int:
        return sum(r.omitidos for r in self.resultados)

    @property
    def errores(self) -> int:
        return (self.errores_sin_atribuir + sum(r.errores for r in self.resultados)
                + sum(1 for r in self.resultados if r.estado == ESTADO_ERROR))

    @property
    def duracion(self) -> str:
        if not self.fin:
            return ""
        segundos = max(0, int((self.fin - self.inicio).total_seconds()))
        return "%dm %02ds" % (segundos // 60, segundos % 60)

    def todo_bien(self) -> bool:
        return not self.abortado and self.errores == 0

    # --------------------------------------------------------------- asunto
    def asunto(self) -> str:
        if self.abortado:
            return "[BFI] ERROR: no se pudo revisar el buzon"
        if not self.todo_bien():
            return "[BFI] Revision con incidencias (%d)" % self.errores
        if self.procesados == 0:
            return "[BFI] Revision sin movimientos nuevos"
        return "[BFI] %d movimiento(s) insertado(s) en el ERP" % self.insertados

    # ----------------------------------------------------------------- texto
    def texto(self) -> str:
        lineas: List[str] = []
        lineas.append("Agente de correo BFI - %s" % self.modo.upper())
        lineas.append("Fecha: %s" % fecha_larga(self.inicio))
        if self.duracion:
            lineas.append("Duracion: %s" % self.duracion)
        if self.fuente:
            lineas.append("Fuente: %s" % self.fuente)
        if self.carpeta:
            lineas.append("Carpeta vigilada: %s" % self.carpeta)
        lineas.append("")
        if self.abortado:
            lineas.append("NO SE PUDO COMPLETAR LA REVISION")
            lineas.append("  " + self.abortado)
            lineas.append("")
        lineas.append("Resumen: %d correo(s) revisado(s), %d procesado(s), "
                      "%d adjunto(s), %d linea(s) leida(s)."
                      % (self.correos, self.procesados, self.adjuntos, self.filas))
        if self.modo == "simulacion":
            lineas.append("SIMULACION: no se ha escrito nada en Ninox y los correos "
                          "no se han movido ni marcado.")
        else:
            lineas.append("Insertadas: %d. Omitidas por duplicado: %d. Errores: %d."
                          % (self.insertados, self.omitidos, self.errores))
        if self.ninox_omitido:
            lineas.append("Ninox: OMITIDO (%s). Los CSVs quedan en la carpeta de trabajo."
                          % self.ninox_omitido)
        if self.tablas:
            lineas.append("")
            lineas.append("Por tabla destino:")
            for linea in self.tablas:
                lineas.append("  - %s" % linea)
        lineas.append("")
        if self.resultados:
            lineas.append("Detalle por correo:")
            for resultado in self.resultados:
                lineas.append(resultado.linea())
                for nota in resultado.notas[1:]:
                    lineas.append("      - %s" % nota)
        else:
            lineas.append("No habia correos que cumpliesen el filtro.")
        if self.avisos:
            lineas.append("")
            lineas.append("Avisos:")
            for aviso in self.avisos:
                lineas.append("  ! %s" % aviso)
        if self.ruta_resumen:
            lineas.append("")
            lineas.append("Informe completo: %s" % self.ruta_resumen)
        return "\n".join(lineas)

    def html(self) -> str:
        filas = []
        for resultado in self.resultados:
            filas.append(
                "<tr><td>%s</td><td>%s</td><td style='text-align:right'>%d</td>"
                "<td style='text-align:right'>%d</td><td style='text-align:right'>%d</td>"
                "<td>%s</td></tr>"
                % (html.escape(resultado.etiqueta), html.escape(resultado.estado),
                   resultado.filas, resultado.insertados, resultado.errores,
                   html.escape("; ".join(resultado.notas))))
        avisos = ""
        if self.avisos:
            avisos = "<p><b>Avisos</b></p><ul>" + "".join(
                "<li>%s</li>" % html.escape(a) for a in self.avisos) + "</ul>"
        if self.ninox_omitido:
            avisos += ("<p><b>Ninox omitido:</b> %s</p>" % html.escape(self.ninox_omitido))
        cabecera = ("<p><b>%s</b><br>%s</p>"
                    % (html.escape(self.modo.upper()), html.escape(fecha_larga(self.inicio))))
        if self.abortado:
            cabecera += "<p style='color:#b00'><b>No se pudo completar:</b> %s</p>" % html.escape(
                self.abortado)
        cuerpo = (
            "%s<p>%d correo(s) revisado(s) - %d procesado(s) - %d adjunto(s) - "
            "%d linea(s)</p>"
            % (cabecera, self.correos, self.procesados, self.adjuntos, self.filas)
        )
        if self.modo != "simulacion":
            cuerpo += ("<p>Insertadas: <b>%d</b> - Omitidas por duplicado: %d - "
                       "Errores: %d</p>" % (self.insertados, self.omitidos, self.errores))
        if filas:
            cuerpo += ("<table border='1' cellspacing='0' cellpadding='4'>"
                       "<tr><th>Correo</th><th>Estado</th><th>Lineas</th>"
                       "<th>Insertadas</th><th>Errores</th><th>Notas</th></tr>"
                       + "".join(filas) + "</table>")
        cuerpo += avisos
        if self.ruta_resumen:
            cuerpo += "<p style='color:#666;font-size:12px'>Informe completo: %s</p>" % html.escape(
                self.ruta_resumen)
        return "<html><body style='font-family:Segoe UI,Arial,sans-serif'>%s</body></html>" % cuerpo


class EnviadorResumen:
    """Escribe el resumen en un fichero. Es el modo seguro y el de simulacion."""

    def __init__(self, carpeta: Path, log: Optional[Callable[[str], None]] = None) -> None:
        self.carpeta = Path(carpeta)
        self.log = log or (lambda texto: None)

    def enviar(self, informe: InformeEjecucion, para: List[str]) -> str:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        nombre = "resumen_%s.txt" % informe.inicio.strftime("%Y%m%d_%H%M")
        ruta = self.carpeta / nombre
        ruta.write_text(informe.texto(), encoding="utf-8")
        self.log("Resumen escrito en %s" % ruta)
        return str(ruta)


class EnviadorResumenOutlook:
    """Envia el resumen con el Outlook del equipo (COM).

    Si ``simular`` esta activo se usa ``Display`` en lugar de ``Send``: el correo
    se abre en pantalla y **no se envia**.
    """

    def __init__(self, simular: bool = True,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.simular = simular
        self.log = log or (lambda texto: None)

    def enviar(self, informe: InformeEjecucion, para: List[str]) -> str:
        if not para:
            return "sin destinatarios configurados"
        try:
            import pythoncom                                      # noqa: PLC0415
            import win32com.client                                # noqa: PLC0415
        except ImportError:
            return "no se pudo enviar: falta pywin32"
        pythoncom.CoInitialize()
        try:
            app = win32com.client.Dispatch("Outlook.Application")
            correo = app.CreateItem(0)                            # 0 = olMailItem
            correo.To = "; ".join(para)
            correo.Subject = informe.asunto()
            correo.Body = informe.texto()
            try:
                correo.HTMLBody = informe.html()
            except Exception:                                     # noqa: BLE001
                pass
            if self.simular:
                correo.Display()
                return "mostrado en pantalla (simulacion), no enviado"
            correo.Send()
            return "enviado a " + ", ".join(para)
        except Exception as exc:                                  # noqa: BLE001
            return "no se pudo enviar el resumen: %s" % exc
        finally:
            try:
                pythoncom.CoUninitialize()
            except Exception:                                     # noqa: BLE001
                pass


__all__ = [
    "ESTADO_ERROR", "ESTADO_OK", "ESTADO_OMITIDO", "ESTADO_SIN_DATOS",
    "EnviadorResumen", "EnviadorResumenOutlook", "InformeEjecucion",
    "ResultadoCorreo", "fecha_larga",
]
