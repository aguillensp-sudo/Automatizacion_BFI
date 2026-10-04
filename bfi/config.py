"""Configuracion central de la aplicacion BFI.

Todo lo que se puede ajustar sin tocar logica vive aqui: endpoints, tiempos de
espera, nombres de variables de entorno y el MAPA DE NEGOCIO cuenta -> tabla
Ninox. Ese mapa es la traduccion literal del apartado 5.1.1 del documento
``AppWindows_BFI.md``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ninox (API REST v1) — endpoints verificados en el proyecto hermano JI
# ---------------------------------------------------------------------------
NINOX_BASE_URL = "https://api.ninox.com/v1"

ENV_API_KEY = "NINOX_API_KEY"
ENV_TEAM_ID = "NINOX_TEAM_ID"
ENV_DB_ID = "NINOX_DB_ID"
ENV_VARS = (ENV_API_KEY, ENV_TEAM_ID, ENV_DB_ID)

PAGE_SIZE = 100          # maximo aceptado por Ninox
REQUEST_TIMEOUT_SEC = 60
MAX_RETRIES = 3
RETRY_BACKOFF_SEC = 1.0


# ---------------------------------------------------------------------------
# Mapa de negocio: numero de cuenta del extracto -> tabla Ninox destino
# ---------------------------------------------------------------------------
# Documento, apartado 5.1.1.
#
# Los numeros de cuenta reales NO se versionan: son datos del cliente. Viven en
# un fichero local ``cuentas.json`` (ver ``cuentas.example.json``) que se busca,
# por este orden, en: la variable de entorno ``BFI_CUENTAS_FILE``;
# ``%APPDATA%\BFI Extractor\cuentas.json``; y junto al ejecutable (o a la raiz
# del proyecto si se ejecuta desde el codigo fuente). Si no existe ninguno, se usan
# las cuentas ficticias de demostracion de abajo: ninguna cuenta real coincide, y
# ``mapping.agrupar_por_tabla`` aborta con un mensaje claro en lugar de escribir.
ENV_CUENTAS_FILE = "BFI_CUENTAS_FILE"

_CUENTAS_DEMO = {
    "0300000000000001": "OD",
    "0300000000000002": "PD",
    "0300000000000003": "TD",
}
_ETIQUETAS_DEMO = {
    "OD": "OD - cuenta 1",
    "PD": "PD - cuenta 2",
    "TD": "TD - cuenta 3",
    "DF": "DF - tabla de pruebas",
}


def _rutas_cuentas():
    rutas = []
    if os.environ.get(ENV_CUENTAS_FILE):
        rutas.append(Path(os.environ[ENV_CUENTAS_FILE]))
    if os.environ.get("APPDATA"):
        rutas.append(Path(os.environ["APPDATA"]) / "BFI Extractor" / "cuentas.json")
    base = Path(sys.executable).parent if getattr(sys, "frozen", False)         else Path(__file__).resolve().parent.parent
    rutas.append(base / "cuentas.json")
    return rutas


def _cargar_cuentas():
    """Devuelve (cuentas, etiquetas, origen). ``origen`` es la ruta usada o ``None``."""
    for ruta in _rutas_cuentas():
        if ruta.is_file():
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            cuentas = dict(datos["cuentas"])
            etiquetas = {**_ETIQUETAS_DEMO, **datos.get("etiquetas", {})}
            return cuentas, etiquetas, str(ruta)
    return dict(_CUENTAS_DEMO), dict(_ETIQUETAS_DEMO), None


CUENTA_A_TABLA, TABLA_A_ETIQUETA, CUENTAS_ORIGEN = _cargar_cuentas()

# Tabla autorizada para pruebas. Nunca se escriben datos reales en ella.
TABLA_TEST = "DF"


# ---------------------------------------------------------------------------
# Mapeo CSV -> Ninox, apartado 5.1.2 del documento
# ---------------------------------------------------------------------------
# Ids de campo, tal y como los transcribio el documento (apartado 5.1.2).
# La API acepta el id de campo y lo traduce al nombre; esta verificado contra la
# base real en tools/probe_df.py. Aun asi, antes de escribir se resuelven a
# NOMBRES contra los metadatos de la tabla destino y se aborta el lote entero si
# algun id no existiera en ella, para no arriesgar un HTTP 500 sin diagnostico.
MAPEO_POR_TABLA = {
    "OD": {
        "fecha_valor": "B",    # Fecha Bancaria
        "referencia": "R1",    # Referencia
        "detalle": "G1",       # Detalles
        "importe": "D",        # Importe CUP
        "egreso_ingreso": "F",  # Egreso/Ingreso (booleano)
        "oper_transito": "O1",  # Oper. en transito (choice No/Si)
        "concepto": "C",      # Concepto (choice)
        "saldo": "O",         # Saldo inicial -> NO se escribe, lo calcula Ninox
        "factura": "Q1",       # Factura (texto)
        "tipo_cambio": "J",    # Tipo de Cambio
        "tipo_cambio_eur": None,
    },
    "PD": {
        "fecha_valor": "B",    # Fecha Bancaria
        "referencia": "P1",    # Referencia
        "detalle": "G1",       # Detalles
        "importe": "D",        # Importe CUP
        "egreso_ingreso": "F",
        "oper_transito": "M1",  # Oper. en transito
        "concepto": "C",
        "saldo": "O",         # Saldo inicial -> NO se escribe, lo calcula Ninox
        "factura": "O1",       # Factura (texto)
        "tipo_cambio": "J",
        "tipo_cambio_eur": None,
    },
    "TD": {
        "fecha_valor": "B",
        "referencia": "S1",    # Referencia
        "detalle": "K1",       # Detalles
        "importe": "D",        # Importe USD
        "egreso_ingreso": "F",
        "oper_transito": "Q1",  # Oper. en transito
        "concepto": "C",
        "saldo": "O",         # Saldo inicial -> NO se escribe, lo calcula Ninox
        "factura": "R1",       # Factura (texto)
        "tipo_cambio": "J",    # Tipo de Cambio CUP-USD  -> 24 (fijo)
        "tipo_cambio_eur": "C1",  # Tipo de Cambio USD-EUR -> en blanco
    },
    # DF "BFI 00000004 (TEST)" es la unica tabla vacia del ERP con campos
    # escribibles y es ESTRUCTURALMENTE IDENTICA A TD (mismos ids de campo). Se
    # incluye aqui solo para poder ensayar el circuito completo sin tocar datos
    # de negocio (ver tools/ensayo_df.py). La aplicacion nunca enruta una cuenta
    # real a DF: el mapa de cuentas de arriba no la menciona.
    "DF": {
        "fecha_valor": "B",
        "referencia": "S1",
        "detalle": "K1",
        "importe": "D",
        "egreso_ingreso": "F",
        "oper_transito": "Q1",
        "concepto": "C",
        "saldo": "O",
        "factura": "R1",
        "tipo_cambio": "J",
        "tipo_cambio_eur": "C1",
    },
}

# Valor de "Concepto" que debe llevar SIEMPRE una linea de ingreso (credito).
# Vale para las tres tablas: en OD, PD y TD el campo Concepto es el id "C" y la
# opcion id 11 es "Ingresos recibidos". Confirmado leyendo los metadatos de las
# tres tablas el 12/09/2026.
#
# Es obligatorio porque la formula de Ninox que calcula "Saldo inicial" depende
# de este campo: sin el, el saldo no se calcula.
CONCEPTO_INGRESO = "11"

# Aplica a OD y PD: "Tipo de Cambio = siempre en blanco" (apartado 5.2).
# Se OMITE el campo en lugar de enviarlo vacio: el PUT hace merge y asi no se
# destruye un valor que otro proceso pueda haber calculado.
TIPO_CAMBIO_FIJO_TD = 24

OPER_TRANSITO_NO = "No"

# "Saldo inicial" (campo O) NO se escribe NUNCA. Lo calcula una formula de Ninox
# al crear el registro, encadenando con la fila anterior. Verificado el
# 12/09/2026 en la tabla TD de produccion: el registro nuevo recibio
# 23230.16 - 4.03 = 23226.13, exactamente el saldo final de la fila anterior.
# Si la aplicacion lo escribiera, taparia ese calculo, y si lo corrigiera con un
# PUT dejaria la fila fuera de la cadena y contaminaria las siguientes.
CAMPOS_QUE_CALCULA_NINOX = ("Saldo inicial",)

# ---------------------------------------------------------------------------
# Ficheros
# ---------------------------------------------------------------------------
CSV_BASENAME = "movimientos_bfi.csv"
LOG_DIRNAME = "logs"
