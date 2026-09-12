"""Pruebas de la logica de negocio. No necesitan red ni credenciales.

Ejecutar con:
    python -m pytest tests/ -q
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bfi import config                                    # noqa: E402
from bfi.extractor import (FIELDNAMES, fmt_date,          # noqa: E402
                           parse_amount)
from bfi.mapping import (ErrorDeMapeo, agrupar_por_tabla,  # noqa: E402
                         clave_duplicado, construir_payload, importe_de_fila,
                         leer_csv, marcar_duplicados, normalizar_fecha,
                         resolver_mapeo)

# Campos en ids, tal y como los devuelve la API (recorte de los reales).
CAMPOS_OD = {"B": "Fecha Bancaria", "R1": "Referencia", "G1": "Detalles",
             "D": "Importe CUP", "O": "Saldo inicial", "F": "Egreso/Ingreso",
             "O1": "Oper. en tránsito", "Q1": "Factura", "J": "Tipo de Cambio"}
CAMPOS_PD = {"B": "Fecha Bancaria", "P1": "Referencia", "G1": "Detalles",
             "D": "Importe CUP", "O": "Saldo inicial", "F": "Egreso/Ingreso",
             "M1": "Oper. en tránsito", "O1": "Factura", "J": "Tipo de Cambio"}
CAMPOS_TD = {"B": "Fecha Bancaria", "S1": "Referencia", "K1": "Detalles",
             "D": "Importe USD", "O": "Saldo inicial", "F": "Egreso/Ingreso",
             "Q1": "Oper. en tránsito", "R1": "Factura",
             "J": "Tipo de Cambio CUP-USD", "C1": "Tipo de Cambio USD-EUR"}
CAMPOS_DF = dict(CAMPOS_TD)

MAPAS = {"OD": CAMPOS_OD, "PD": CAMPOS_PD, "TD": CAMPOS_TD, "DF": CAMPOS_DF}


def fila(**kwargs):
    base = {
        "cuenta_no": "0300000005399610", "moneda": "CUP", "nombre": "JULSA",
        "estado_no": "522", "periodo_desde": "2026-06-23",
        "periodo_hasta": "2026-07-01", "fecha_emision": "2026-07-02",
        "saldo_anterior": "7762958.6", "fecha": "2026-07-01",
        "fecha_valor": "2026-07-01", "referencia": "FT2618308488",
        "detalle": "TRANSFERENCIA ENVIADA", "debito": "43918.88",
        "credito": "", "saldo": "7718679.72",
    }
    base.update(kwargs)
    return base


# ---------------------------------------------------------------------------
# extractor
# ---------------------------------------------------------------------------

def test_fmt_date_normaliza_el_ano_de_dos_digitos():
    assert fmt_date("1", "7", "26") == "2026-07-01"
    assert fmt_date("17", "12", "2026") == "2026-12-17"


@pytest.mark.parametrize("texto,esperado", [
    ("7,992.00", 7992.0),
    ("1.234,56", 1234.56),
    ("43875.00", 43875.0),
    ("", None),
    ("-", None),
])
def test_parse_amount(texto, esperado):
    assert parse_amount(texto) == esperado


def test_el_csv_de_ejemplo_se_lee_y_se_agrupa():
    """El CSV real que genero el extractor debe mapearse a las tres tablas."""
    ruta = RAIZ / "movimientos_bfi.csv"
    if not ruta.exists():
        pytest.skip("movimientos_bfi.csv no esta en el repositorio")
    filas = leer_csv(str(ruta))
    assert filas, "el CSV no deberia estar vacio"
    assert set(FIELDNAMES).issubset(filas[0].keys())
    grupos = agrupar_por_tabla(filas)
    assert set(grupos) <= {"OD", "PD", "TD"}
    assert sum(len(v) for v in grupos.values()) == len(filas)


# ---------------------------------------------------------------------------
# mapeo
# ---------------------------------------------------------------------------

def test_mapeo_od_usa_los_ids_del_documento():
    m = resolver_mapeo("OD", CAMPOS_OD)
    assert m.nombre("fecha_valor") == "Fecha Bancaria"
    assert m.nombre("referencia") == "Referencia"
    assert m.nombre("detalle") == "Detalles"
    assert m.nombre("importe") == "Importe CUP"
    assert m.nombre("saldo") == "Saldo inicial"
    assert m.nombre("oper_transito") == "Oper. en tránsito"


def test_mapeo_pd_y_td_son_los_que_indica_el_documento():
    pd = resolver_mapeo("PD", CAMPOS_PD)
    assert pd.ids["P1"] == "Referencia" and pd.nombre("detalle") == "Detalles"
    td = resolver_mapeo("TD", CAMPOS_TD)
    assert td.ids["S1"] == "Referencia" and td.ids["K1"] == "Detalles"
    assert td.nombre("importe") == "Importe USD"


def test_un_id_inexistente_en_la_tabla_destino_aborta():
    """Si el mapeo apuntara a un id que no existe, no se envia NADA."""
    incompleto = {k: v for k, v in CAMPOS_PD.items() if k != "P1"}
    with pytest.raises(ErrorDeMapeo) as info:
        resolver_mapeo("PD", incompleto)
    assert "P1" in str(info.value)


def test_una_cuenta_desconocida_aborta():
    with pytest.raises(ErrorDeMapeo) as info:
        agrupar_por_tabla([fila(cuenta_no="9999999999")])
    assert "9999999999" in str(info.value)


# ---------------------------------------------------------------------------
# importe y egreso/ingreso
# ---------------------------------------------------------------------------

def test_credito_es_ingreso_azul_y_debito_es_egreso_gris():
    """Mapeo del booleano, VERIFICADO EN NINOX el 12/09/2026.

    Se comprobo mirando el toggle del campo junto al valor que la API devuelve:

        credito (entra dinero) -> True  -> toggle AZUL (derecha)  = Ingreso
        debito  (sale dinero)  -> False -> toggle GRIS (izquierda) = Egreso

    El apartado 5.2 del documento funcional decia lo contrario ("debito -> Si /
    credito -> No"): esa transcripcion estaba invertida, y este mapeo la
    sustituye. La prueba fija el mapeo CORRECTO para que nadie lo "arregle" por
    error leyendo el documento viejo.
    """
    m = resolver_mapeo("OD", CAMPOS_OD)

    p = construir_payload(fila(debito="", credito="500.25"), m)
    assert p["fields"]["Importe CUP"] == 500.25
    assert p["fields"]["Egreso/Ingreso"] is True, \
        "un credito es un INGRESO: True -> toggle azul"

    p = construir_payload(fila(debito="43918.88", credito=""), m)
    assert p["fields"]["Importe CUP"] == 43918.88
    assert p["fields"]["Egreso/Ingreso"] is False, \
        "un debito es un EGRESO: False -> toggle gris"


def test_debito_y_credito_a_la_vez_es_un_error():
    with pytest.raises(ErrorDeMapeo):
        importe_de_fila(fila(debito="1", credito="2"))


def test_fila_sin_importe_no_escribe_el_campo():
    m = resolver_mapeo("OD", CAMPOS_OD)
    p = construir_payload(fila(debito="", credito=""), m)
    assert "Importe CUP" not in p["fields"]
    assert "Egreso/Ingreso" not in p["fields"]


# ---------------------------------------------------------------------------
# reglas fijas del apartado 5.2
# ---------------------------------------------------------------------------

def test_oper_en_transito_siempre_no_en_las_tres_tablas():
    for tabla in ("OD", "PD", "TD"):
        m = resolver_mapeo(tabla, MAPAS[tabla])
        p = construir_payload(fila(), m)
        assert p["fields"]["Oper. en tránsito"] == "No"


def test_tipo_de_cambio_en_td_es_24_y_el_eur_va_vacio():
    m = resolver_mapeo("TD", CAMPOS_TD)
    p = construir_payload(fila(), m)
    assert p["fields"]["Tipo de Cambio CUP-USD"] == 24
    assert p["fields"]["Tipo de Cambio USD-EUR"] == ""


def test_tipo_de_cambio_se_omite_en_od_y_pd():
    """Se OMITE en vez de enviarlo vacio: el PUT hace merge y no borra nada."""
    for tabla in ("OD", "PD"):
        m = resolver_mapeo(tabla, MAPAS[tabla])
        p = construir_payload(fila(), m)
        assert "Tipo de Cambio" not in p["fields"]
        assert "Tipo de Cambio" in p["omitidos"]


def test_factura_siempre_vacia_para_no_heredar_datos_ajenos():
    """El CSV no trae factura: si Ninox la rellenara sola, seria enganoso."""
    for tabla in ("OD", "PD", "TD"):
        m = resolver_mapeo(tabla, MAPAS[tabla])
        p = construir_payload(fila(), m)
        assert p["fields"]["Factura"] == ""


def test_una_fila_sin_fecha_aborta():
    m = resolver_mapeo("OD", CAMPOS_OD)
    with pytest.raises(ErrorDeMapeo):
        construir_payload(fila(fecha_valor=""), m)


# ---------------------------------------------------------------------------
# Fechas: el CSV puede haber pasado por Excel
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("entrada,esperado", [
    ("2026-07-08", "2026-07-08"),          # como lo escribe el extractor
    ("2026-7-8", "2026-07-08"),            # ISO sin ceros
    ("08/07/2026", "2026-07-08"),          # como lo deja Excel en espanol
    ("8/7/2026", "2026-07-08"),
    ("08-07-2026", "2026-07-08"),
    ("08/07/26", "2026-07-08"),
])
def test_las_fechas_se_normalizan_a_iso(entrada, esperado):
    assert normalizar_fecha(entrada) == esperado


@pytest.mark.parametrize("entrada", ["", "   ", "no es una fecha", "2026/07/08"])
def test_una_fecha_ilegible_no_inventa_nada(entrada):
    assert normalizar_fecha(entrada) == ""


def test_un_csv_guardado_desde_excel_se_envia_con_fecha_iso():
    """Si el CSV paso por Excel, la fecha debe llegar a Ninox en ISO igualmente.

    Sin esto, Excel convertiria las fechas a 08/07/2026 y Ninox no las
    reconoceria: el volcado fallaria sin que el usuario supiera por que.
    """
    m = resolver_mapeo("TD", CAMPOS_TD)
    p = construir_payload(
        fila(cuenta_no="0300000006102035", fecha_valor="08/07/2026"), m)
    assert p["fields"]["Fecha Bancaria"] == "2026-07-08"


def test_una_fecha_ilegible_aborta_la_fila_con_un_mensaje_util():
    m = resolver_mapeo("TD", CAMPOS_TD)
    with pytest.raises(ErrorDeMapeo) as info:
        construir_payload(fila(fecha_valor="17 de julio"), m)
    assert "Excel" in str(info.value), "el mensaje debe explicar las dos formas validas"


# ---------------------------------------------------------------------------
# duplicados
# ---------------------------------------------------------------------------

def test_deteccion_de_duplicados_por_referencia_fecha_e_importe():
    m = resolver_mapeo("OD", CAMPOS_OD)
    nueva = fila(referencia="NUEVA-1")
    repetida = fila(referencia="EXISTE-1", debito="100.00")
    resultado = marcar_duplicados(
        [nueva, repetida],
        # Un debito es egreso -> False (ver el mapeo verificado mas arriba).
        [{"Referencia": "EXISTE-1", "Fecha Bancaria": "2026-07-01",
          "Importe CUP": 100.0, "Egreso/Ingreso": False}],
        m)
    assert resultado[0]["_duplicado"] is False
    assert resultado[1]["_duplicado"] is True


def test_la_misma_referencia_con_importe_distinto_no_es_duplicado():
    m = resolver_mapeo("OD", CAMPOS_OD)
    resultado = marcar_duplicados(
        [fila(referencia="R", debito="100.00")],
        [{"Referencia": "R", "Fecha Bancaria": "2026-07-01",
          "Importe CUP": 999.0, "Egreso/Ingreso": True}],
        m)
    assert resultado[0]["_duplicado"] is False


def test_clave_duplicado_redondea_a_dos_decimales():
    assert clave_duplicado(fila(debito="100.004"))[2] == 100.0


# ---------------------------------------------------------------------------
# Regresion: los INGRESOS (columna credito)
# ---------------------------------------------------------------------------
# Estas pruebas existen por un error real: en la primera entrega de este
# proyecto se afirmo, sin comprobarlo, que el CSV no tenia ninguna linea con
# credito. Tenia tres. La comprobacion a mano estaba mal; el codigo, bien. Estas
# pruebas fijan el comportamiento para que no dependa de que nadie mire bien.

CUENTA_A_TABLA = {"0300000005399610": ("OD", CAMPOS_OD),
                  "0300000006074740": ("PD", CAMPOS_PD),
                  "0300000006102035": ("TD", CAMPOS_TD)}


def _csv_real():
    ruta = RAIZ / "movimientos_bfi.csv"
    if not ruta.exists():
        pytest.skip("movimientos_bfi.csv no esta en el repositorio")
    return leer_csv(str(ruta))


def test_el_csv_real_tiene_ingresos_y_el_recuento_es_explicito():
    filas = _csv_real()
    ingresos = [f for f in filas if (f.get("credito") or "").strip()]
    debitos = [f for f in filas if (f.get("debito") or "").strip()]
    assert len(filas) == 44, "el CSV de ejemplo deberia tener 44 lineas"
    assert len(ingresos) == 3, "el CSV de ejemplo deberia tener 3 lineas de credito"
    assert len(debitos) == 41
    assert len(ingresos) + len(debitos) == len(filas), \
        "cada linea debe tener exactamente uno de los dos importes"


def test_cada_linea_del_csv_real_escribe_el_signo_correcto():
    """El ingreso va como Egreso/Ingreso = True (toggle azul) y su importe en D."""
    for fila_csv in _csv_real():
        tabla, campos = CUENTA_A_TABLA[fila_csv["cuenta_no"]]
        m = resolver_mapeo(tabla, campos)
        p = construir_payload(fila_csv, m)
        campo_importe = m.nombre("importe")
        es_ingreso = bool((fila_csv.get("credito") or "").strip())
        assert p["fields"]["Egreso/Ingreso"] is es_ingreso, \
            "signo equivocado en la referencia %s" % fila_csv["referencia"]
        valor = p["fields"][campo_importe]
        if es_ingreso:
            assert valor == float(fila_csv["credito"])
        else:
            assert valor == float(fila_csv["debito"])


def test_los_tres_ingresos_del_csv_real_son_los_esperados():
    """Fija los tres ingresos concretos: si el extractor cambia, salta aqui."""
    esperados = {
        ("0300000006074740", "85522010001246", 19102.86),
        ("0300000006102035", "FT2619151273", 7992.0),
        ("0300000006102035", "52542310006746", 8.0),
    }
    obtenidos = set()
    for f in _csv_real():
        if (f.get("credito") or "").strip():
            obtenidos.add((f["cuenta_no"], f["referencia"], float(f["credito"])))
    assert obtenidos == esperados
