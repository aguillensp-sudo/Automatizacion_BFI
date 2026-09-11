"""Configuracion central de la aplicacion BFI.

Todo lo que se puede ajustar sin tocar logica vive aqui: endpoints, tiempos de
espera, nombres de variables de entorno y el MAPA DE NEGOCIO cuenta -> tabla
Ninox. Ese mapa es la traduccion literal del apartado 5.1.1 del documento
``AppWindows_BFI.md``.
"""
from __future__ import annotations

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
CUENTA_A_TABLA = {
    "0300000005399610": "OD",
    "0300000006074740": "PD",
    "0300000006102035": "TD",
}

# Nombre legible de cada tabla, solo para los mensajes al usuario final.
TABLA_A_ETIQUETA = {
    "OD": "OD — BFI 05399610",
    "PD": "PD — BFI 06074740",
    "TD": "TD — BFI 61020",
    "DF": "DF — BFI 61021 (TEST)",
}

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
        "saldo": "O",          # Saldo inicial
        "egreso_ingreso": "F",  # Egreso/Ingreso (booleano)
        "oper_transito": "O1",  # Oper. en transito (choice No/Si)
        "factura": "Q1",       # Factura (texto)
        "tipo_cambio": "J",    # Tipo de Cambio
        "tipo_cambio_eur": None,
    },
    "PD": {
        "fecha_valor": "B",    # Fecha Bancaria
        "referencia": "P1",    # Referencia
        "detalle": "G1",       # Detalles
        "importe": "D",        # Importe CUP
        "saldo": "O",          # Saldo inicial
        "egreso_ingreso": "F",
        "oper_transito": "M1",  # Oper. en transito
        "factura": "O1",       # Factura (texto)
        "tipo_cambio": "J",
        "tipo_cambio_eur": None,
    },
    "TD": {
        "fecha_valor": "B",
        "referencia": "S1",    # Referencia
        "detalle": "K1",       # Detalles
        "importe": "D",        # Importe USD
        "saldo": "O",
        "egreso_ingreso": "F",
        "oper_transito": "Q1",  # Oper. en transito
        "factura": "R1",       # Factura (texto)
        "tipo_cambio": "J",    # Tipo de Cambio CUP-USD  -> 24 (fijo)
        "tipo_cambio_eur": "C1",  # Tipo de Cambio USD-EUR -> en blanco
    },
    # DF "BFI 61021 (TEST)" es la unica tabla vacia del ERP con campos
    # escribibles y es ESTRUCTURALMENTE IDENTICA A TD (mismos ids de campo). Se
    # incluye aqui solo para poder ensayar el circuito completo sin tocar datos
    # de negocio (ver tools/ensayo_df.py). La aplicacion nunca enruta una cuenta
    # real a DF: el mapa de cuentas de arriba no la menciona.
    "DF": {
        "fecha_valor": "B",
        "referencia": "S1",
        "detalle": "K1",
        "importe": "D",
        "saldo": "O",
        "egreso_ingreso": "F",
        "oper_transito": "Q1",
        "factura": "R1",
        "tipo_cambio": "J",
        "tipo_cambio_eur": "C1",
    },
}

# Aplica a OD y PD: "Tipo de Cambio = siempre en blanco" (apartado 5.2).
# Se OMITE el campo en lugar de enviarlo vacio: el PUT hace merge y asi no se
# destruye un valor que otro proceso pueda haber calculado.
TIPO_CAMBIO_FIJO_TD = 24

OPER_TRANSITO_NO = "No"

# ---------------------------------------------------------------------------
# Ficheros
# ---------------------------------------------------------------------------
CSV_BASENAME = "movimientos_bfi.csv"
LOG_DIRNAME = "logs"
