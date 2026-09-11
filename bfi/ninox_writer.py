"""Insercion de las lineas del CSV en el ERP Ninox.

Orquesta el proceso completo y es el unico modulo que **escribe**:

    1. Resuelve el mapeo de cada tabla contra los metadatos reales de Ninox.
    2. Descarga la tabla destino para detectar lineas que ya existen.
    3. Construye el payload de cada fila.
    4. Lo envia (o solo lo muestra, en modo simulacion).
    5. Vuelve a leer cada registro creado y comprueba que se guardo lo enviado.

El punto 5 no es paranoia: esta verificado contra la base real que **hay campos
con formula que descartan lo que envias** (``Saldo inicial``, ``Secuencial``,
``Conciliado``). Sin releer, el informe diria que todo fue bien aunque un campo
no se hubiera grabado.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config
from .mapping import (
    ErrorDeMapeo,
    MapeoResuelto,
    construir_payload,
    marcar_duplicados,
    resolver_mapeo,
)
from .ninox_client import NinoxClient, NinoxError


@dataclass
class ResultadoTabla:
    """Resultado de procesar una tabla."""

    tabla: str
    etiqueta: str
    total: int = 0
    insertados: int = 0
    omitidos: int = 0
    erroneos: int = 0
    duplicados_detectados: int = 0
    errores: List[str] = field(default_factory=list)
    discrepancias: List[str] = field(default_factory=list)
    corregidos: List[str] = field(default_factory=list)
    ids_creados: List[int] = field(default_factory=list)

    def linea_resumen(self) -> str:
        return ("%s: %d insertada(s), %d omitida(s), %d con error"
                % (self.etiqueta, self.insertados, self.omitidos, self.erroneos))


@dataclass
class ResultadoProceso:
    """Resultado global: lo que se le ensena al usuario al terminar."""

    tablas: List[ResultadoTabla] = field(default_factory=list)
    simulado: bool = False
    abortado: str = ""

    @property
    def insertados(self) -> int:
        return sum(t.insertados for t in self.tablas)

    @property
    def erroneos(self) -> int:
        return sum(t.erroneos for t in self.tablas)

    @property
    def omitidos(self) -> int:
        return sum(t.omitidos for t in self.tablas)

    def resumen_texto(self) -> str:
        if self.abortado:
            return self.abortado
        lineas = []
        for t in self.tablas:
            lineas.append("  • " + t.linea_resumen())
        cabecera = ("SIMULACION — no se ha escrito nada en Ninox\n"
                    if self.simulado else
                    "Insercion terminada\n")
        return cabecera + "\n".join(lineas)


class EscritorNinox:
    """Inserta lineas del CSV en las tablas OD, PD y TD."""

    def __init__(self, cliente: Optional[NinoxClient] = None,
                 aviso: Optional[Callable[[str], None]] = None,
                 pausa_entre_envios: float = 0.0) -> None:
        self.cli = cliente or NinoxClient(logger=None)
        self._aviso = aviso or (lambda texto: None)
        self.pausa = pausa_entre_envios
        self._mapeos: Dict[str, MapeoResuelto] = {}

    # ------------------------------------------------------------------ util
    def info(self, texto: str) -> None:
        self._aviso(texto)

    def mapeo(self, tabla: str) -> MapeoResuelto:
        """Mapeo resuelto y cacheado de una tabla, validado contra Ninox."""
        if tabla not in self._mapeos:
            nombres = self.cli.field_names(tabla)
            self._mapeos[tabla] = resolver_mapeo(tabla, nombres)
            self.info("Mapeo validado para %s (%d campos comprobados)."
                      % (tabla, len(self._mapeos[tabla].nombres)))
        return self._mapeos[tabla]

    def comprobar_conexion(self) -> Tuple[bool, str]:
        """Comprueba credenciales y acceso a las tres tablas destino."""
        try:
            self.cli.list_tables()
        except Exception as exc:            # noqa: BLE001
            return False, "No se pudo conectar con Ninox: %s" % exc
        mensajes = []
        for tabla in config.CUENTA_A_TABLA.values():
            try:
                mapeo = self.mapeo(tabla)
                mensajes.append("%s OK" % mapeo.tabla)
            except ErrorDeMapeo as exc:
                return False, str(exc)
            except Exception as exc:        # noqa: BLE001
                return False, "Error al leer la tabla %s: %s" % (tabla, exc)
        return True, "Conexion correcta: " + ", ".join(mensajes)

    # -------------------------------------------------------------- duplicados
    def detectar_duplicados(self, grupos: Dict[str, List[Dict[str, str]]]
                            ) -> Dict[str, List[Dict[str, str]]]:
        """Anota cada fila con ``_duplicado`` comparando con la tabla destino."""
        anotados: Dict[str, List[Dict[str, str]]] = {}
        for tabla, filas in grupos.items():
            mapeo = self.mapeo(tabla)
            self.info("Leyendo %s para buscar lineas ya existentes..." % mapeo.etiqueta)
            try:
                existentes = self.cli.fetch_all_records(tabla, use_cache=False)
            except NinoxError as exc:
                raise ErrorDeMapeo(
                    "No se pudo leer la tabla %s: %s" % (tabla, exc)) from exc
            anotadas = marcar_duplicados(filas, [r.get("fields", {}) for r in existentes],
                                         mapeo)
            n_dup = sum(1 for f in anotadas if f.get("_duplicado"))
            self.info("   %s: %d registros en Ninox, %d linea(s) ya presentes."
                      % (mapeo.etiqueta, len(existentes), n_dup))
            anotados[tabla] = anotadas
        return anotados

    # --------------------------------------------------------------- insercion
    def insertar(self, grupos: Dict[str, List[Dict[str, str]]],
                 simular: bool = True,
                 omitir_duplicados: bool = True,
                 verificar: bool = True,
                 corregir: bool = True) -> ResultadoProceso:
        """Inserta (o simula) todos los grupos.

        ``grupos`` son las filas del CSV, ya anotadas o no con ``_duplicado``.
        En simulacion no se envia nada y se devuelven solo los recuentos.

        ``verificar`` relee cada registro creado. ``corregir`` va un paso mas
        alla: si un campo no se guardo como se envio, lo reintenta con un ``PUT``
        (esta verificado que asi si se guarda; el valor por defecto solo gana en
        el alta). Sin ``corregir`` esos campos se listan como discrepancias.
        """
        resultado = ResultadoProceso(simulado=simular)
        if simular:
            self.info("MODO SIMULACION: se construyen los envios pero no se envia nada.")

        for tabla, filas in grupos.items():
            mapeo = self.mapeo(tabla)
            res = ResultadoTabla(tabla=tabla, etiqueta=mapeo.etiqueta,
                                 total=len(filas))
            self.info("— %s: %d linea(s)" % (mapeo.etiqueta, len(filas)))

            for numero, fila in enumerate(filas, start=1):
                if fila.get("_duplicado") and omitir_duplicados:
                    res.omitidos += 1
                    res.duplicados_detectados += 1
                    continue

                # --- Construccion del payload (puede fallar por datos) ---
                try:
                    envio = construir_payload(fila, mapeo)
                except ErrorDeMapeo as exc:
                    res.erroneos += 1
                    res.errores.append("fila %d: %s" % (numero, exc))
                    continue

                if simular:
                    res.insertados += 1     # "se habrian insertado"
                    if numero <= 3:
                        self.info("   [simulacion] fila %d -> %s"
                                  % (numero, _payload_legible(envio["fields"])))
                    continue

                # --- Envio real ---
                ok, mensaje, nuevo_id = self._enviar(tabla, envio, numero)
                if not ok:
                    res.erroneos += 1
                    res.errores.append("fila %d: %s" % (numero, mensaje))
                    self.info("   fila %d ERROR: %s" % (numero, mensaje))
                    continue

                res.insertados += 1
                if nuevo_id is not None:
                    res.ids_creados.append(nuevo_id)

                # --- Relectura de comprobacion (apartado 7 del doc del ERP) ---
                if verificar and nuevo_id is not None:
                    discrepancias, corregidos = self._verificar(
                        tabla, nuevo_id, envio, corregir)
                    res.discrepancias.extend(discrepancias)
                    res.corregidos.extend(corregidos)
                    for texto in corregidos:
                        self.info("   corregido: %s" % texto)
                    for texto in discrepancias:
                        self.info("   aviso: %s" % texto)

                if self.pausa:
                    time.sleep(self.pausa)

            resultado.tablas.append(res)
            self.info("   -> %s" % res.linea_resumen())
            for err in res.errores[:5]:
                self.info("      · %s" % err)

        return resultado

    # ------------------------------------------------------------------ privado
    def _enviar(self, tabla: str, envio: Dict[str, Any],
                numero: int) -> Tuple[bool, str, Optional[int]]:
        try:
            status, cuerpo = self.cli.create_record(tabla, envio)
        except NinoxError as exc:
            return False, "fallo de red: %s" % exc, None

        if status == 200 and isinstance(cuerpo, dict) and "id" in cuerpo:
            return True, "ok", cuerpo["id"]
        if status == 200:
            return True, "ok (sin id en la respuesta)", None
        # Ninox responde 500 ante un nombre de campo inexistente, no un 400.
        pista = ""
        if status == 500:
            pista = ("  (Ninox devuelve 500 cuando un nombre de campo no existe: "
                     "revisa el mapeo de %s)" % tabla)
        return False, "HTTP %s: %s%s" % (status, _corto(cuerpo), pista), None

    def _verificar(self, tabla: str, record_id: int, envio: Dict[str, Any],
                   corregir: bool) -> Tuple[List[str], List[str]]:
        """Comprueba que los campos se guardaron. Devuelve (discrepancias, corregidos).

        Si un campo no se guardo como se envio y ``corregir`` esta activo, se
        reintenta con un ``PUT``. Esta verificado contra la base real
        (``tools/probe_saldo_put.py``) que asi SI se guarda: el valor por defecto
        de la tabla solo se impone en el alta.
        """
        guardado = self.cli.get_record(tabla, record_id)
        if not guardado:
            return ["no se pudo releer el registro %s de %s" % (record_id, tabla)], []
        campos = guardado.get("fields", {})

        def _igual(nombre: str, valor: Any) -> bool:
            real = campos.get(nombre, None)
            if real is None and valor == "":
                return True
            if isinstance(valor, float) and isinstance(real, (int, float)):
                return abs(float(real) - valor) < 0.005
            return real == valor

        pendientes = {n: v for n, v in envio["fields"].items() if not _igual(n, v)}
        if not pendientes:
            return [], []

        discrepancias: List[str] = []
        corregidos: List[str] = []

        if corregir:
            try:
                status, _ = self.cli.update_record(tabla, record_id,
                                                   {"fields": pendientes})
            except NinoxError as exc:
                status = 0
                discrepancias.append("registro %s de %s: fallo al corregir: %s"
                                     % (record_id, tabla, exc))
            if status == 200:
                releido = (self.cli.get_record(tabla, record_id) or {}).get("fields", {})
                for nombre, valor in pendientes.items():
                    real = releido.get(nombre, None)
                    if real == valor or (isinstance(valor, float)
                                         and isinstance(real, (int, float))
                                         and abs(float(real) - valor) < 0.005):
                        corregidos.append(
                            "registro %s de %s: '%s' se habia quedado en %r y se "
                            "corrigio a %r con un segundo envio"
                            % (record_id, tabla, nombre, campos.get(nombre), valor))
                    else:
                        discrepancias.append(
                            "registro %s de %s: '%s' sigue en %r pese a enviar %r "
                            "(campo calculado por Ninox: no se puede forzar)"
                            % (record_id, tabla, nombre, real, valor))
                return discrepancias, corregidos
            for nombre, valor in pendientes.items():
                discrepancias.append(
                    "registro %s de %s: '%s' se envio %r y quedo %r"
                    % (record_id, tabla, nombre, valor, campos.get(nombre)))
            return discrepancias, corregidos

        for nombre, valor in pendientes.items():
            discrepancias.append(
                "registro %s de %s: '%s' se envio %r y quedo %r "
                "(campo con valor por defecto en el alta)"
                % (record_id, tabla, nombre, valor, campos.get(nombre)))
        return discrepancias, corregidos


def _payload_legible(campos: Dict[str, Any]) -> str:
    partes = []
    for k, v in campos.items():
        if isinstance(v, str) and len(v) > 40:
            v = v[:37] + "..."
        partes.append("%s=%r" % (k, v))
    return "{" + ", ".join(partes) + "}"


def _corto(cuerpo: Any, limite: int = 200) -> str:
    texto = str(cuerpo)
    return texto if len(texto) <= limite else texto[:limite] + "..."
