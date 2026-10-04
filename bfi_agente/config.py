"""Configuracion del agente de correo.

Un unico fichero JSON junto al ejecutable. Se rechazan las claves
desconocidas a proposito: en un proceso desatendido que corre los lunes por la
manana, una errata silenciosa (``remitentes_permitdo``) es peor que un error.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from bfi.logging_setup import carpeta_base

NOMBRE_FICHERO = "agente_correo.json"

# Texto de la respuesta al remitente cuando el correo se ha procesado bien.
TEXTO_RESPUESTA_POR_DEFECTO = "Los registros han sido insertados en Ninox"


class ErrorConfiguracion(Exception):
    """La configuracion impide ejecutar el agente."""


@dataclass
class ConfigAgente:
    """Ajustes del agente. Los valores por defecto son conservadores."""

    # --- Que carpeta se vigila -------------------------------------------------
    carpeta_outlook: str = "Bandeja de entrada/BFI"
    # Vaciar ``carpeta_procesados`` desactiva el archivado: los correos se quedan
    # donde estan y solo se les pone la categoria.
    carpeta_procesados: str = ""
    categoria_procesada: str = "Procesado BFI"

    # --- Que correos cuentan ---------------------------------------------------
    # Lista vacia = cualquier remitente. Se compara sin distinguir mayusculas
    # contra la direccion SMTP y contra el nombre visible.
    remitentes_permitidos: List[str] = field(default_factory=list)
    patron_adjunto: str = r"(?i)\.pdf$"
    patron_asunto: str = ""
    # Margen sobre los 7 dias de la semana, para no perder un correo que llego
    # tarde el lunes anterior.
    dias_atras: int = 8
    # 0 = sin limite.
    max_correos: int = 0

    # --- Como se procesa -------------------------------------------------------
    # Un mismo PDF reenviado dos veces no debe duplicar lineas en el ERP.
    evitar_adjuntos_repetidos: bool = True

    # --- Donde se guarda -------------------------------------------------------
    carpeta_trabajo: str = "logs/trabajo"
    ruta_estado: str = "logs/agente_bfi.sqlite3"

    # --- Aviso al terminar -----------------------------------------------------
    # Por defecto NO se envia correo: hay que decir a quien. El informe siempre
    # se escribe en un fichero dentro de la carpeta de trabajo.
    resumen_activo: bool = False
    resumen_para: List[str] = field(default_factory=list)
    # Con True, el resumen se muestra en pantalla pero no se envia nunca.
    resumen_solo_simular: bool = False

    # --- Respuesta al remitente ------------------------------------------------
    # Se responde al correo original (mismo hilo, "RE:") cuando el correo se ha
    # procesado sin errores. Con esto activo, la ejecucion real SI escribe a
    # terceros: por eso viene desactivado y por eso las pruebas deben dejarlo en
    # false.
    responder_al_remitente: bool = False
    texto_respuesta: str = TEXTO_RESPUESTA_POR_DEFECTO

    # --- Interno ---------------------------------------------------------------
    # No se configura: guarda de que fichero salio la configuracion, para los
    # avisos ("se estan usando los valores por defecto").
    ruta_origen: Optional[str] = None

    # ------------------------------------------------------------------ carga
    @classmethod
    def cargar(cls, ruta: Optional[Any] = None) -> "ConfigAgente":
        """Lee el fichero de configuracion.

        Si no existe se devuelven los valores por defecto en lugar de fallar:
        asi ``--dry-run`` funciona recien clonado el repositorio. Quien llama
        debe avisar de que se estan usando los valores por defecto.
        """
        camino = Path(ruta) if ruta else carpeta_base() / NOMBRE_FICHERO
        if not camino.exists():
            return cls(ruta_origen=None)
        try:
            crudo = json.loads(camino.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ErrorConfiguracion(
                "El fichero %s no es JSON valido: %s" % (camino, exc)) from exc
        if not isinstance(crudo, dict):
            raise ErrorConfiguracion(
                "El fichero %s debe contener un objeto JSON." % camino)
        return cls.desde_diccionario(crudo, origen=str(camino))

    @classmethod
    def desde_diccionario(cls, datos: Dict[str, Any],
                          origen: str = "(memoria)") -> "ConfigAgente":
        campos = {f for f in cls.__dataclass_fields__ if f != "ruta_origen"}
        desconocidos = sorted(set(datos) - campos)
        if desconocidos:
            raise ErrorConfiguracion(
                "Claves no reconocidas en %s: %s.\nClaves validas: %s"
                % (origen, ", ".join(desconocidos), ", ".join(sorted(campos))))
        cfg = cls(ruta_origen=origen)
        for clave, valor in datos.items():
            setattr(cfg, clave, valor)
        cfg.normalizar()
        cfg.validar()
        return cfg

    # ------------------------------------------------------------- validacion
    def normalizar(self) -> None:
        for atributo in ("remitentes_permitidos", "resumen_para"):
            valor = getattr(self, atributo)
            if isinstance(valor, str):
                valor = [valor]
            setattr(self, atributo, [str(v).strip() for v in (valor or []) if str(v).strip()])

    def validar(self) -> None:
        if not str(self.carpeta_outlook or "").strip():
            raise ErrorConfiguracion("carpeta_outlook no puede estar vacia.")
        for nombre, patron in (("patron_adjunto", self.patron_adjunto),
                               ("patron_asunto", self.patron_asunto)):
            if not patron:
                continue
            try:
                re.compile(patron)
            except re.error as exc:
                raise ErrorConfiguracion(
                    "%s no es una expresion regular valida: %s" % (nombre, exc)) from exc
        if int(self.dias_atras) < 0:
            raise ErrorConfiguracion("dias_atras no puede ser negativo.")
        if int(self.max_correos) < 0:
            raise ErrorConfiguracion("max_correos no puede ser negativo.")
        if self.resumen_activo and not self.resumen_para and not self.resumen_solo_simular:
            raise ErrorConfiguracion(
                "resumen_activo esta activo pero resumen_para esta vacio.\n"
                "Indica al menos un destinatario o pon resumen_activo en false.")
        if self.responder_al_remitente and not str(self.texto_respuesta or "").strip():
            raise ErrorConfiguracion(
                "responder_al_remitente esta activo pero texto_respuesta esta vacio:\n"
                "no se enviaria un correo en blanco. Escribe el texto o desactiva "
                "la respuesta.")

    # ---------------------------------------------------------------- rutas
    def ruta(self, valor: str) -> Path:
        """Resuelve una ruta de la configuracion contra la carpeta base."""
        camino = Path(valor)
        return camino if camino.is_absolute() else (carpeta_base() / camino)

    @property
    def carpeta_trabajo_abs(self) -> Path:
        return self.ruta(self.carpeta_trabajo)

    @property
    def ruta_estado_abs(self) -> Path:
        return self.ruta(self.ruta_estado)

    def como_diccionario(self) -> Dict[str, Any]:
        datos = asdict(self)
        datos.pop("ruta_origen", None)
        return datos

    def carpeta_de_ejecucion(self, marca: str) -> Path:
        """Carpeta de trabajo de una ejecucion concreta (``2026-09-28_0730``)."""
        return self.carpeta_trabajo_abs / marca

    def compilar_patrones(self) -> Tuple[Optional[re.Pattern], Optional[re.Pattern]]:
        adjunto = re.compile(self.patron_adjunto) if self.patron_adjunto else None
        asunto = re.compile(self.patron_asunto) if self.patron_asunto else None
        return adjunto, asunto
