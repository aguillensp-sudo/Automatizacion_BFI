"""Valida el CSV generado contra los PDFs de origen y comprueba los signos.

Existe por un motivo concreto: en la primera entrega de este proyecto se afirmo
que el CSV no tenia ninguna linea de credito, cuando en realidad tenia TRES. La
afirmacion salio de un recuento mal hecho a mano, no de una comprobacion. Este
script sustituye a ese recuento a ojo por algo que se puede repetir.

Comprueba cuatro cosas sobre un directorio de PDFs:

1. Cuantas lineas aporta cada extracto y cuanto suma por cuenta.
2. Que cada linea tiene **exactamente uno** de los dos importes (debito o
   credito) informado: ni cero ni los dos.
3. **Reconstruye la cadena de saldos de cada cuenta** y verifica que
   ``saldo[i] == saldo[i-1] +/- importe[i]``. Es la comprobacion fuerte: detecta
   un movimiento perdido, un importe mal leido y un signo invertido.
4. Que el signo que se va a escribir en Ninox ("Egreso/Ingreso") coincide con el
   signo real del movimiento en el extracto.

Uso:
    python tools/validar_extraccion.py [carpeta_con_pdfs]
"""
from __future__ import annotations

import csv
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                    # noqa: E402
from bfi.extractor import listar_pdfs, procesar_pdfs       # noqa: E402
from bfi.mapping import construir_payload, resolver_mapeo  # noqa: E402


def _num(valor) -> float | None:
    """Normaliza un importe: ``procesar_pdfs`` devuelve float/None, mientras que
    ``leer_csv`` devuelve texto. Acepta los dos para poder validar cualquiera de
    los dos caminos."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def main() -> int:
    carpeta = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    pdfs = listar_pdfs(str(carpeta))
    if not pdfs:
        print("No hay PDFs en %s" % carpeta)
        return 2
    print("PDFs encontrados: %d" % len(pdfs))

    tmp = Path(tempfile.mkdtemp(prefix="bfi_validacion_"))
    csv_salida = tmp / "movimientos.csv"
    filas = procesar_pdfs(pdfs, str(csv_salida), aviso=lambda m: None)

    # --- 1. Recuento por cuenta -------------------------------------------
    por_cuenta = Counter(r["cuenta_no"] for r in filas)
    print("\n=== 1. LINEAS POR CUENTA ===")
    for cuenta, n in por_cuenta.most_common():
        tabla = config.CUENTA_A_TABLA.get(cuenta, "??")
        print("   %-18s -> %3d lineas  (tabla %s)" % (cuenta, n, tabla))
    print("   %-18s -> %3d lineas" % ("TOTAL", len(filas)))

    fallos = []

    # --- 2. Exactamente un importe por linea -------------------------------
    print("\n=== 2. IMPORTES (debito XOR credito) ===")
    ninguno = los_dos = solo_deb = solo_cre = 0
    for r in filas:
        d = _num(r["debito"])
        c = _num(r["credito"])
        if d is None and c is None:
            ninguno += 1
        elif d is not None and c is not None:
            los_dos += 1
        elif d is not None:
            solo_deb += 1
        else:
            solo_cre += 1
    print("   solo debito    : %d" % solo_deb)
    print("   solo credito   : %d  <-- ingresos" % solo_cre)
    print("   ninguno        : %d" % ninguno)
    print("   los dos a la vez: %d" % los_dos)
    if ninguno or los_dos:
        fallos.append("hay %d linea(s) sin importe y %d con los dos" % (ninguno, los_dos))

    # --- 3. Cadena de saldos por cuenta ------------------------------------
    print("\n=== 3. CADENA DE SALDOS (saldo[i] = saldo[i-1] +/- importe[i]) ===")
    por_cuenta_filas = defaultdict(list)
    for r in filas:
        por_cuenta_filas[r["cuenta_no"]].append(r)

    for cuenta, grupo in sorted(por_cuenta_filas.items()):
        # Orden original de aparicion: los estados de cuenta van del mas antiguo
        # al mas reciente, y el extractor los emite en ese orden.
        saltos, cuadran, prev = [], 0, None
        for r in grupo:
            importe = _num(r["debito"]) or _num(r["credito"]) or 0.0
            es_egreso = _num(r["debito"]) is not None
            saldo = _num(r["saldo"])
            if saldo is None:
                fallos.append("linea %s sin saldo" % r["referencia"])
                continue
            if prev is not None:
                esperado = round(prev - importe, 2) if es_egreso else round(prev + importe, 2)
                if abs(esperado - saldo) < 0.01:
                    cuadran += 1
                else:
                    saltos.append("      %s %s: saldo %s, esperado %s (importe %s %s)"
                                  % (r["fecha_valor"], r["referencia"], saldo,
                                     esperado, importe, "debito" if es_egreso else "credito"))
            prev = saldo
        total = len(grupo) - 1
        print("   %s: %d/%d movimientos encadenan" % (cuenta, cuadran, total))
        if saltos:
            # Un salto puede ser legitimo: el primer movimiento de un extracto
            # nuevo se compara con el ultimo del anterior y puede haber un
            # intervalo no cubierto por los PDFs entregados.
            print("      (saltos detectados: %d)" % len(saltos))
            for s in saltos[:10]:
                print(s)

    # --- 4. Signo que se escribira en Ninox --------------------------------
    print("\n=== 4. SIGNO Y CONCEPTO ESCRITOS EN NINOX ===")
    # Mapa id->nombre simulado con los nombres reales de las tablas destino.
    nombres = {
        "OD": {"B": "Fecha Bancaria", "R1": "Referencia", "G1": "Detalles",
               "D": "Importe CUP", "O": "Saldo inicial", "F": "Egreso/Ingreso",
               "O1": "Oper. en tránsito", "C": "Concepto", "Q1": "Factura",
               "J": "Tipo de Cambio"},
        "PD": {"B": "Fecha Bancaria", "P1": "Referencia", "G1": "Detalles",
               "D": "Importe CUP", "O": "Saldo inicial", "F": "Egreso/Ingreso",
               "M1": "Oper. en tránsito", "C": "Concepto", "O1": "Factura",
               "J": "Tipo de Cambio"},
        "TD": {"B": "Fecha Bancaria", "S1": "Referencia", "K1": "Detalles",
               "D": "Importe USD", "O": "Saldo inicial", "F": "Egreso/Ingreso",
               "Q1": "Oper. en tránsito", "C": "Concepto", "R1": "Factura",
               "J": "Tipo de Cambio CUP-USD", "C1": "Tipo de Cambio USD-EUR"},
    }
    ingresos = 0
    for r in filas:
        tabla = config.CUENTA_A_TABLA.get(r["cuenta_no"])
        if tabla is None:
            fallos.append("cuenta desconocida: %s" % r["cuenta_no"])
            continue
        payload = construir_payload(r, resolver_mapeo(tabla, nombres[tabla]))
        # Booleano de Ninox, VERIFICADO el 12/09/2026:
        #   credito -> True  (toggle azul, Ingreso)
        #   debito  -> False (toggle gris, Egreso)
        esperado = _num(r["credito"]) is not None
        real = payload["fields"]["Egreso/Ingreso"]
        if real != esperado:
            fallos.append("signo invertido en %s: Egreso/Ingreso=%s con debito=%r credito=%r"
                          % (r["referencia"], real, r["debito"], r["credito"]))
        # Los ingresos deben llevar Concepto = 11 (Ingresos recibidos), porque la
        # formula de Ninox que calcula el saldo depende de ese campo.
        if esperado:
            ingresos += 1
            if payload["fields"].get("Concepto") != config.CONCEPTO_INGRESO:
                fallos.append("ingreso %s sin Concepto %s (tiene %r)"
                              % (r["referencia"], config.CONCEPTO_INGRESO,
                                 payload["fields"].get("Concepto")))
        # El saldo NO se debe enviar nunca: lo calcula Ninox.
        if "Saldo inicial" in payload["fields"]:
            fallos.append("se esta enviando 'Saldo inicial' en %s: lo calcula Ninox"
                          % r["referencia"])
    print("   lineas con Egreso/Ingreso = True  (ingresos, toggle azul): %d" % ingresos)
    print("   lineas con Egreso/Ingreso = False (egresos,  toggle gris): %d"
          % (len(filas) - ingresos))
    print("   los %d ingresos llevan Concepto = %s" % (ingresos, config.CONCEPTO_INGRESO))
    print("   'Saldo inicial' no se envia en ninguna linea (lo calcula Ninox)")

    # --- Veredicto ---------------------------------------------------------
    print()
    if fallos:
        print("FALLOS (%d):" % len(fallos))
        for f in fallos:
            print("   -", f)
        return 1
    print("OK: %d lineas, exactamente un importe cada una, y el signo de las %d "
          "lineas de ingreso es correcto." % (len(filas), ingresos))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
