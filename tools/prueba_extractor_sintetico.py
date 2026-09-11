"""Comprueba el circuito completo con un extracto sintetico del BFI.

El documento funcional apunta a unos PDFs de prueba en la carpeta del proyecto,
pero en el momento de escribir esto la carpeta solo contenia el extractor, el
CSV de ejemplo y este documento; los PDFs no estaban.

Para no dejar la extraccion sin verificar, esta prueba construye un PDF con el
**mismo formato de texto** que produce un extracto real (y que el extractor ya
parseaba con exito: el CSV `movimientos_bfi.csv` salio de uno), lo pasa por el
parser y comprueba que:

* se detecta la cabecera (cuenta, moneda, saldo anterior),
* se extraen los movimientos con su referencia y detalle,
* y se decide bien debito/credito comparando el saldo con el anterior.

Se escribe el PDF en un directorio temporal: no ensucia el repositorio.

    python tools/prueba_extractor_sintetico.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bfi import config                                          # noqa: E402
from bfi.extractor import parse_pdf                             # noqa: E402

# Texto calcado de un extracto real del banco.
LINEAS = [
    "BANCO FINANCIERO INTERNACIONAL",
    "MIRAMAR",
    "ESTADO DE CUENTA",
    "Nombre",
    "FINESP-JULSA INDUSTRIAL, S.A.",
    "C u e n t a : 0300000006102035 Moneda: USD",
    "De 23 06 26 a 01 07 26 02 07 26",
    "Fecha F.Valor D e t a l l e Debitos Creditos",
    "0300000006102035 USD 27,251.15 522 1",
    "Saldo Anterior 27,251.15",
    "30 06 26 30 06 26 FT2619000001 COMISION BANCARIA 1.00 27,250.15",
    "30 06 26 30 06 26 FT2619000002 TRANSFERENCIA RECIBIDA: USD 4,019.99 31,270.14",
    "01 07 26 01 07 26 DC2618000003 PAGO PROVEEDOR ACOREC S.A. 2,500.00 28,770.14",
    "Saldo a su favor 28,770.14",
]


def main() -> int:
    try:
        from reportlab.pdfgen import canvas          # type: ignore
        motor = "reportlab"
    except ImportError:
        canvas = None
        motor = None

    tmp = Path(tempfile.mkdtemp(prefix="bfi_extracto_"))
    pdf = tmp / "extracto_sintetico.pdf"

    if motor is None:
        # Sin reportlab se usa el propio pdfplumber solo si esta disponible.
        try:
            from pdfplumber.pdfminer.pdfparser import PDFParser  # noqa: F401
        except Exception:                            # noqa: BLE001
            pass
        print("AVISO: reportlab no esta instalado; se omite la generacion del PDF.")
        print("       Instalalo con: pip install reportlab")
        return 0

    c = canvas.Canvas(str(pdf))
    y = 800
    for linea in LINEAS:
        c.drawString(40, y, linea)
        y -= 14
        if y < 40:
            c.showPage()
            y = 800
    c.save()

    datos = parse_pdf(str(pdf))
    meta, txs = datos["meta"], datos["transactions"]

    print("PDF sintetico:", pdf)
    print("Cabecera detectada:")
    for clave in ("cuenta_no", "moneda", "saldo_anterior", "estado_no",
                  "periodo_desde", "periodo_hasta", "fecha_emision"):
        print("   %-15s = %r" % (clave, meta.get(clave)))
    print("Movimientos: %d" % len(txs))
    for t in txs:
        print("   %s | %-16s | debito=%-10s credito=%-10s saldo=%s"
              % (t["fecha_valor"], t["referencia"][:16], t["debito"],
                 t["credito"], t["saldo"]))

    fallos = []
    if meta.get("cuenta_no") != "0300000006102035":
        fallos.append("no se detecto la cuenta")
    if meta.get("saldo_anterior") != 27251.15:
        fallos.append("no se detecto el saldo anterior")
    if len(txs) != 3:
        fallos.append("se esperaban 3 movimientos y hay %d" % len(txs))
    else:
        if txs[0]["debito"] != 1.00 or txs[0]["credito"] is not None:
            fallos.append("el primer movimiento deberia ser un debito de 1.00")
        if txs[1]["credito"] != 4019.99 or txs[1]["debito"] is not None:
            fallos.append("el segundo deberia ser un credito de 4019.99")
        if txs[2]["debito"] != 2500.00:
            fallos.append("el tercero deberia ser un debito de 2500.00")

    # Y ademas: la cuenta debe resolver a la tabla TD del mapa de negocio.
    tabla = config.CUENTA_A_TABLA.get(meta.get("cuenta_no", ""))
    print("Cuenta -> tabla Ninox:", tabla)
    if tabla != "TD":
        fallos.append("la cuenta no resuelve a la tabla TD")

    print()
    if fallos:
        print("FALLOS:")
        for f in fallos:
            print("   -", f)
        return 1
    print("OK: extraccion, cabecera, importes y mapa de cuentas correctos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
