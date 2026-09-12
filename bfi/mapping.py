"""Traduccion del CSV a los campos de Ninox.

Este modulo es el corazon de la parte de negocio y es **puro**: no hace red ni
toca la interfaz, asi que se puede probar con ``pytest`` sin credenciales.

Reglas que implementa (documento, apartados 5.1 y 5.2)
------------------------------------------------------

* ``cuenta_no`` decide la tabla destino (``OD``, ``PD`` o ``TD``).
* Columnas que se leen siempre:

      fecha_valor -> "Fecha Bancaria"   (B)
      referencia  -> "Referencia"       (R1 en OD, P1 en PD, S1 en TD)
      detalle     -> "Detalles"         (G1 en OD/PD, K1 en TD)
      debito/credito -> el campo de importe (D, "Importe CUP"/"Importe USD")
      saldo       -> "Saldo inicial"    (O)

* Solo una de las dos columnas de importe viene informada; ambas van al mismo
  campo. El campo que decide el signo es el booleano ``F`` "Egreso/Ingreso",
  y su equivalencia esta **VERIFICADA EN NINOX** el 12/09/2026 mirando el toggle
  del campo junto al valor guardado que devuelve la API:

      credito -> entra dinero -> **True**  -> toggle AZUL (derecha)  = Ingreso
      debito  -> sale dinero  -> **False** -> toggle GRIS (izquierda) = Egreso

  OJO: el apartado 5.2 del documento funcional decia "debito -> Si /
  credito -> No", que es lo contrario. Se comprobo con el registro 768 de la
  tabla DF: guardaba ``False`` y el toggle se veia GRIS (Egreso) siendo la fila
  un ingreso. El usuario confirmo el mapeo de colores.
* "Oper. en transito" se escribe siempre "No".
* "Tipo de Cambio" no se toca en OD ni en PD. En TD se envia ``J`` = 24 y
  ``C1`` en blanco.

Las claves de ``config.MAPEO_POR_TABLA`` son **ids de campo** de Ninox porque
asi los transcribio el documento; la API acepta el id y lo traduce al nombre
(verificado en ``tools/probe_df.py``, 11/09/2026). Aun asi el mapeo se resuelve
a NOMBRES contra los metadatos reales antes de escribir: si un id no existiera
en la tabla destino, se detecta aqui y no se envia nada, en vez de arriesgarse a
un HTTP 500 indistinguible de una caida del servidor.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from . import config


class ErrorDeMapeo(Exception):
    """El CSV o el mapeo no permiten construir un envio valido."""


@dataclass
class MapeoResuelto:
    """Mapeo de una tabla con los NOMBRES de campo ya resueltos."""

    tabla: str
    etiqueta: str
    # clave logica -> nombre real del campo en Ninox
    nombres: Dict[str, str] = field(default_factory=dict)
    # id de campo original del documento -> nombre real (para informes)
    ids: Dict[str, str] = field(default_factory=dict)

    def nombre(self, clave: str) -> Optional[str]:
        return self.nombres.get(clave)


# Orden de los campos en el payload, para que los informes sean legibles.
_CLAVES = ("fecha_valor", "referencia", "detalle", "importe",
           "saldo", "egreso_ingreso", "oper_transito", "factura",
           "tipo_cambio", "tipo_cambio_eur")


def resolver_mapeo(tabla: str, field_names: Dict[str, str]) -> MapeoResuelto:
    """Traduce ``config.MAPEO_POR_TABLA[tabla]`` (ids) a nombres reales.

    ``field_names`` es el diccionario ``{id: nombre}`` que devuelve
    ``NinoxClient.field_names(tabla)``. Lanza ``ErrorDeMapeo`` si la tabla no
    tiene mapeo definido o si algun id del documento no existe en ella.
    """
    if tabla not in config.MAPEO_POR_TABLA:
        raise ErrorDeMapeo("La tabla %r no tiene mapeo definido en config.py" % tabla)

    definicion = config.MAPEO_POR_TABLA[tabla]
    resuelto = MapeoResuelto(
        tabla=tabla,
        etiqueta=config.TABLA_A_ETIQUETA.get(tabla, tabla),
    )
    faltan: List[str] = []
    for clave in _CLAVES:
        fid = definicion.get(clave)
        if not fid:
            continue
        nombre = field_names.get(fid)
        if not nombre:
            faltan.append("%s (%s)" % (fid, clave))
            continue
        resuelto.ids[fid] = nombre
        resuelto.nombres[clave] = nombre

    if faltan:
        raise ErrorDeMapeo(
            "El mapeo de la tabla %s referencia ids de campo que NO existen en "
            "esa tabla: %s.\nCampos disponibles: %s\n"
            "Revisa config.MAPEO_POR_TABLA antes de insertar nada."
            % (tabla, ", ".join(faltan),
               ", ".join(sorted("%s=%s" % (i, n) for i, n in field_names.items())))
        )
    if "importe" not in resuelto.nombres:
        raise ErrorDeMapeo("El mapeo de %s no define el campo de importe." % tabla)
    return resuelto


# ---------------------------------------------------------------------------
# Lectura del CSV
# ---------------------------------------------------------------------------

def leer_csv(ruta: str) -> List[Dict[str, str]]:
    """Lee el CSV del extractor. Acepta BOM (utf-8-sig) y descarta filas vacias."""
    with open(ruta, "r", encoding="utf-8-sig", newline="") as f:
        lector = csv.DictReader(f)
        if not lector.fieldnames:
            raise ErrorDeMapeo("El fichero %s esta vacio o no tiene cabecera." % ruta)
        faltan = [c for c in ("cuenta_no", "fecha_valor", "referencia", "detalle")
                  if c not in lector.fieldnames]
        if faltan:
            raise ErrorDeMapeo(
                "Al CSV le faltan columnas obligatorias: %s. Columnas encontradas: %s"
                % (", ".join(faltan), ", ".join(lector.fieldnames)))
        filas = []
        for fila in lector:
            if not any((v or "").strip() for v in fila.values()):
                continue
            filas.append({k: (v or "").strip() for k, v in fila.items()})
    return filas


def agrupar_por_tabla(filas: Iterable[Dict[str, str]]) -> Dict[str, List[Dict[str, str]]]:
    """Agrupa las filas del CSV por tabla Ninox destino, segun ``cuenta_no``.

    Lanza ``ErrorDeMapeo`` si aparece una cuenta que no esta en el mapa: es
    mejor parar que insertar en la tabla equivocada.
    """
    grupos: Dict[str, List[Dict[str, str]]] = {}
    desconocidas: Dict[str, int] = {}
    for fila in filas:
        cuenta = (fila.get("cuenta_no") or "").strip()
        tabla = config.CUENTA_A_TABLA.get(cuenta)
        if tabla is None:
            desconocidas[cuenta or "(vacia)"] = desconocidas.get(cuenta or "(vacia)", 0) + 1
            continue
        grupos.setdefault(tabla, []).append(fila)
    if desconocidas:
        detalle = ", ".join("%s (%d filas)" % (c, n) for c, n in sorted(desconocidas.items()))
        raise ErrorDeMapeo(
            "Hay cuentas que no corresponden a ninguna tabla conocida: %s.\n"
            "Cuentas configuradas: %s\n"
            "Anade la correspondencia en config.CUENTA_A_TABLA o aparta esos PDFs."
            % (detalle, ", ".join(sorted(config.CUENTA_A_TABLA)))
        )
    return grupos


# ---------------------------------------------------------------------------
# Construccion del payload
# ---------------------------------------------------------------------------

def normalizar_fecha(texto: Any) -> str:
    """Fecha del CSV -> formato ISO ``YYYY-MM-DD``, que es el que guarda Ninox.

    El extractor escribe ISO, pero el CSV es un fichero que puede acabar abierto
    en Excel, y Excel lo guarda con las fechas en formato local (``08/07/2026``)
    y sin el decimal de los numeros. Si eso pasara, la aplicacion enviaria la
    fecha tal cual y Ninox no la reconoceria.

    Por eso se aceptan las dos formas y se convierte. Devuelve cadena vacia si el
    valor no es una fecha reconocible, para que el llamante lo trate como error
    en vez de inventarse un dato.
    """
    t = str(texto or "").strip()
    if not t:
        return ""
    # ISO, tal como lo escribe el extractor.
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t)
    if m:
        anio, mes, dia = m.groups()
        return "%s-%s-%s" % (anio, mes.zfill(2), dia.zfill(2))
    # Formato local espanol, tal como lo deja Excel: dd/mm/aaaa o dd-mm-aaaa.
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", t)
    if m:
        dia, mes, anio = m.groups()
        if len(anio) == 2:
            anio = "20" + anio
        return "%s-%s-%s" % (anio, mes.zfill(2), dia.zfill(2))
    return ""


def _a_float(texto: Any) -> Optional[float]:
    """Convierte a float un valor del CSV. Devuelve None si viene vacio."""
    if texto is None:
        return None
    t = str(texto).strip()
    if t == "":
        return None
    try:
        return float(t)
    except ValueError:
        # El extractor escribe punto decimal; si llegara con coma, se normaliza.
        try:
            return float(t.replace(".", "").replace(",", "."))
        except ValueError:
            return None


def es_ingreso(fila: Dict[str, str]) -> Optional[bool]:
    """?La fila es un ingreso (entra dinero) o un egreso (sale dinero)?

    Mapeo **VERIFICADO EN NINOX** el 12/09/2026, con el usuario delante del
    toggle y la API leyendo el valor guardado:

        credito -> entra dinero -> toggle AZUL (derecha)  -> True
        debito  -> sale dinero  -> toggle GRIS (izquierda) -> False

    OJO: el apartado 5.2 del documento funcional decia lo contrario
    ("debito -> Si / credito -> No"). Se comprobo que esa transcripcion estaba
    invertida respecto a como funciona el campo en Ninox, y el usuario confirmo
    mirando el toggle del registro 768 de DF: el campo guardaba False y el
    toggle aparecia GRIS, es decir Egreso, siendo la fila un ingreso.
    """
    debito = _a_float(fila.get("debito"))
    credito = _a_float(fila.get("credito"))
    if debito is not None and credito is not None:
        raise ErrorDeMapeo(
            "La fila %r trae debito Y credito a la vez; no hay regla definida "
            "para ese caso." % (fila.get("referencia") or fila.get("detalle")))
    if credito is not None:
        return True          # ingreso -> toggle azul
    if debito is not None:
        return False         # egreso  -> toggle gris
    return None


def importe_de_fila(fila: Dict[str, str]):
    """Devuelve ``(importe, es_ingreso)`` a partir de debito/credito.

    El documento garantiza que **al menos una** de las dos viene informada. Si
    las dos vinieran, se avisa al llamante mediante ``ErrorDeMapeo``: no hay
    regla de negocio escrita para ese caso y adivinar seria peor que parar.
    """
    debito = _a_float(fila.get("debito"))
    credito = _a_float(fila.get("credito"))
    if debito is not None and credito is not None:
        raise ErrorDeMapeo(
            "La fila %r trae debito Y credito a la vez; no hay regla definida "
            "para ese caso." % (fila.get("referencia") or fila.get("detalle")))
    if debito is not None:
        return debito, False
    if credito is not None:
        return credito, True
    return None, None


def construir_payload(fila: Dict[str, str], mapeo: MapeoResuelto) -> Dict[str, Any]:
    """Payload de Ninox ``{"fields": {...}}`` para una fila del CSV.

    Devuelve ``{"fields": {...}, "omitidos": {...}}``; lo que no se envia es
    deliberado (ver la cabecera del modulo).
    """
    campos: Dict[str, Any] = {}
    omitidos: Dict[str, str] = {}

    def poner(clave: str, valor: Any) -> None:
        nombre = mapeo.nombre(clave)
        if nombre is None:
            return
        campos[nombre] = valor

    # --- Columnas directas del CSV ---
    fecha = normalizar_fecha(fila.get("fecha_valor"))
    if not fecha:
        raise ErrorDeMapeo(
            "Fila con fecha_valor vacia o no reconocible (%r) en la referencia %r. "
            "Se espera 2026-07-08 (formato del extractor) o 08/07/2026 (si el CSV "
            "se ha guardado desde Excel)."
            % (fila.get("fecha_valor", ""), fila.get("referencia", "?")))
    poner("fecha_valor", fecha)

    poner("referencia", (fila.get("referencia") or "").strip())
    poner("detalle", (fila.get("detalle") or "").strip())

    # "Factura" NO viene en el CSV y no se rellena con nada de el. Se escribe
    # vacia de forma explicita: si la tabla tuviera un valor por defecto para ese
    # campo, un registro con el numero de factura de OTRA operacion seria un dato
    # enganoso. Vacio es la unica respuesta honesta.
    poner("factura", "")

    # --- Importe y signo ---
    importe, ingreso = importe_de_fila(fila)
    if importe is not None:
        poner("importe", importe)
    if ingreso is not None:
        poner("egreso_ingreso", ingreso)

    saldo = _a_float(fila.get("saldo"))
    if saldo is not None:
        poner("saldo", saldo)

    # --- Reglas fijas del apartado 5.2 ---
    poner("oper_transito", config.OPER_TRANSITO_NO)

    # "Tipo de Cambio = siempre en blanco para OD y PD": se OMITE el campo en
    # lugar de enviarlo vacio, porque el PUT hace merge y asi no se destruye un
    # valor que otro proceso pueda haber calculado. En TD si se escribe.
    if mapeo.tabla == "TD":
        poner("tipo_cambio", config.TIPO_CAMBIO_FIJO_TD)
        nombre_eur = mapeo.nombre("tipo_cambio_eur")
        if nombre_eur:
            campos[nombre_eur] = ""
    else:
        for clave in ("tipo_cambio", "tipo_cambio_eur"):
            nombre = mapeo.nombre(clave)
            if nombre:
                omitidos[nombre] = "en blanco segun el apartado 5.2"

    return {"fields": campos, "omitidos": omitidos}


# ---------------------------------------------------------------------------
# Huella para el control de duplicados
# ---------------------------------------------------------------------------

def clave_duplicado(fila: Dict[str, str]) -> tuple:
    """Identidad funcional de una linea: referencia + fecha + importe.

    Se usa para avisar de lineas que ya existen en la tabla destino. El importe
    entra en la clave porque hay extractos con la misma referencia repetida
    (varias lineas de una misma operacion).
    """
    importe, es_ingreso = importe_de_fila(fila)
    return (
        (fila.get("referencia") or "").strip(),
        (fila.get("fecha_valor") or "").strip(),
        round(importe, 2) if importe is not None else None,
        es_ingreso,
    )


def clave_duplicado_ninox(campos: Dict[str, Any], mapeo: MapeoResuelto) -> tuple:
    """La misma clave, calculada desde un registro ya existente en Ninox."""
    ref = campos.get(mapeo.nombre("referencia") or "", "")
    fecha = campos.get(mapeo.nombre("fecha_valor") or "", "")
    imp = campos.get(mapeo.nombre("importe") or "", None)
    egreso = campos.get(mapeo.nombre("egreso_ingreso") or "", None)
    try:
        imp = round(float(imp), 2) if imp is not None else None
    except (TypeError, ValueError):
        imp = None
    if isinstance(fecha, str):
        fecha = fecha.strip()
    return (str(ref).strip() if ref is not None else "",
            str(fecha).strip(),
            imp,
            egreso if isinstance(egreso, bool) else None)


def marcar_duplicados(filas: List[Dict[str, str]],
                      existentes: Iterable[Dict[str, Any]],
                      mapeo: MapeoResuelto) -> List[Dict[str, str]]:
    """Devuelve las filas anotadas con ``_duplicado`` (bool) y ``_motivo``."""
    ya = {clave_duplicado_ninox(c, mapeo) for c in existentes}
    salida = []
    for fila in filas:
        copia = dict(fila)
        try:
            k = clave_duplicado(fila)
        except ErrorDeMapeo:
            copia["_duplicado"] = False
            copia["_motivo"] = "fila ambigua (debito y credito a la vez)"
            salida.append(copia)
            continue
        copia["_duplicado"] = k in ya
        copia["_motivo"] = "ya existe en %s" % mapeo.tabla if k in ya else ""
        salida.append(copia)
    return salida
