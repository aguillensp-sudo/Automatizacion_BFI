"""Extraccion de movimientos de los extractos PDF del Banco Financiero.

Modulo autonomo y **sin dependencias externas**: necesita unicamente la
biblioteca estandar, para que la interfaz grafica pueda importarlo (y mostrar su
version de la logica) incluso cuando pdfplumber aun no esta instalado.

La logica de parseo es la del fichero ``bfi_extractor.py`` que ya funcionaba,
reorganizada en funciones puras y con los nombres en espanol. Produce
exactamente las mismas columnas de CSV que consumia el proceso anterior:

    cuenta_no, moneda, nombre, estado_no, periodo_desde, periodo_hasta,
    fecha_emision, saldo_anterior, fecha, fecha_valor, referencia, detalle,
    debito, credito, saldo
"""
from __future__ import annotations

import csv
import re
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_date(d: str, m: str, y: str) -> str:
    """'17', '07', '26' -> '2026-07-17' (el PDF usa anos de 2 o 4 digitos)."""
    if len(y) == 2:
        y = "20" + y
    return "%s-%s-%s" % (y, m.zfill(2), d.zfill(2))


def parse_amount(text: str) -> Optional[float]:
    """Convierte '7,992.00' o '7.992,00' en float. Devuelve None si no hay numero."""
    text = (text or "").strip()
    if not text:
        return None
    t = re.sub(r"[^\d.,]", "", text)
    if not t:
        return None
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Expresiones regulares del extracto
# ---------------------------------------------------------------------------

# Movimiento con DOS importes al final (importe del movimiento + saldo).
TX_PAT2 = re.compile(
    r"^(\d{2})\s+(\d{2})\s+(\d{2,4})\s+"
    r"(\d{2})\s+(\d{2})\s+(\d{2,4})\s+"
    r"(\S+)\s+"
    r"(.+?)\s+"
    r"([\d,\.]+)\s+([\d,\.]+)\s*$"
)

# Movimiento con UN importe al final (solo saldo).
TX_PAT1 = re.compile(
    r"^(\d{2})\s+(\d{2})\s+(\d{2,4})\s+"
    r"(\d{2})\s+(\d{2})\s+(\d{2,4})\s+"
    r"(\S+)\s+"
    r"(.+?)\s+"
    r"([\d,\.]+)\s*$"
)

SALDO_ANT = re.compile(r"Saldo\s+Anterior\s+([\d,\.]+)", re.I)
SALDO_FAV = re.compile(r"Saldo\s+a\s+su\s+favor\s+([\d,\.]+)", re.I)

SKIP_PAT = re.compile(
    r"(BANCO FINANCIERO|MIRAMAR|ESTADO DE CUENTA|F\. EMISION|"
    r"C u e n t a|Moneda|Saldo Disponible|Estado No|Nombre|"
    r"Fecha\s+F\.Valor|D e t a l l e|Debitos|Creditos)",
    re.I,
)

FIELDNAMES = [
    "cuenta_no", "moneda", "nombre", "estado_no",
    "periodo_desde", "periodo_hasta", "fecha_emision",
    "saldo_anterior",
    "fecha", "fecha_valor", "referencia", "detalle",
    "debito", "credito", "saldo",
]


# ---------------------------------------------------------------------------
# Parseo
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path: str) -> Dict[str, Any]:
    """Extrae cabecera y movimientos de un PDF. Devuelve {'meta', 'transactions'}."""
    import pdfplumber   # import local: la GUI funciona sin pdfplumber instalado

    meta: Dict[str, Any] = {}
    transactions: List[Dict[str, Any]] = []

    with pdfplumber.open(pdf_path) as pdf:
        lines: List[str] = []
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            lines.extend(text.splitlines())

    # --- Cabecera -----------------------------------------------------------
    for i, line in enumerate(lines):
        m = re.search(
            r"De\s+(\d{2})\s+(\d{2})\s+(\d{2,4})\s+a\s+(\d{2})\s+(\d{2})\s+(\d{2,4})"
            r"(?:\s+(\d{2})\s+(\d{2})\s+(\d{2,4}))?",
            line,
        )
        if m and "periodo_desde" not in meta:
            meta["periodo_desde"] = fmt_date(m.group(1), m.group(2), m.group(3))
            meta["periodo_hasta"] = fmt_date(m.group(4), m.group(5), m.group(6))
            if m.group(7):
                meta["fecha_emision"] = fmt_date(m.group(7), m.group(8), m.group(9))

        m2 = re.match(
            r"^(\d{10,20})\s+(USD|CUP|EUR|CUC|MLC)\s+([\d,\.]+)\s+(\d+)\s+(\d+)\s*$",
            line.strip(),
        )
        if m2 and "cuenta_no" not in meta:
            meta["cuenta_no"] = m2.group(1)
            meta["moneda"] = m2.group(2)
            meta["saldo_disponible"] = parse_amount(m2.group(3))
            meta["estado_no"] = m2.group(4)
            meta["hoja_no"] = m2.group(5)

        if line.strip() == "Nombre" and i + 1 < len(lines):
            meta["nombre"] = lines[i + 1].strip()

        m3 = SALDO_ANT.search(line)
        if m3 and "saldo_anterior" not in meta:
            meta["saldo_anterior"] = parse_amount(m3.group(1))

        m4 = SALDO_FAV.search(line)
        if m4:
            meta["saldo_final"] = parse_amount(m4.group(1))

    # --- Movimientos --------------------------------------------------------
    current: Optional[Dict[str, Any]] = None

    for line in lines:
        if SKIP_PAT.search(line):
            continue
        if SALDO_ANT.search(line) or SALDO_FAV.search(line):
            if current:
                transactions.append(current)
                current = None
            continue

        m = TX_PAT2.match(line)
        if m:
            if current:
                transactions.append(current)
            d1, m1, y1, d2, m2_, y2, ref, detalle, imp1, imp2 = m.groups()
            current = {
                "fecha": fmt_date(d1, m1, y1),
                "fecha_valor": fmt_date(d2, m2_, y2),
                "referencia": ref,
                "detalle": detalle.strip(),
                "_imp_mov": parse_amount(imp1),
                "_saldo": parse_amount(imp2),
            }
            continue

        m = TX_PAT1.match(line)
        if m:
            if current:
                transactions.append(current)
            d1, m1, y1, d2, m2_, y2, ref, detalle, imp1 = m.groups()
            current = {
                "fecha": fmt_date(d1, m1, y1),
                "fecha_valor": fmt_date(d2, m2_, y2),
                "referencia": ref,
                "detalle": detalle.strip(),
                "_imp_mov": None,
                "_saldo": parse_amount(imp1),
            }
            continue

        # Continuacion del detalle en la linea siguiente.
        if current and line.strip():
            current["detalle"] += " " + line.strip()

    if current:
        transactions.append(current)

    # --- Debito / credito a partir de la variacion del saldo ----------------
    saldo_prev = meta.get("saldo_anterior")
    rows: List[Dict[str, Any]] = []
    for tx in transactions:
        saldo_tx = tx["_saldo"]
        imp_mov = tx["_imp_mov"]

        debito = credito = None
        if saldo_prev is not None and saldo_tx is not None:
            diff = round(saldo_tx - saldo_prev, 2)
            if diff < 0:
                debito = imp_mov if imp_mov is not None else abs(diff)
            elif diff > 0:
                credito = imp_mov if imp_mov is not None else diff

        saldo_prev = saldo_tx

        rows.append({
            "cuenta_no": meta.get("cuenta_no", ""),
            "moneda": meta.get("moneda", ""),
            "nombre": meta.get("nombre", ""),
            "estado_no": meta.get("estado_no", ""),
            "periodo_desde": meta.get("periodo_desde", ""),
            "periodo_hasta": meta.get("periodo_hasta", ""),
            "fecha_emision": meta.get("fecha_emision", ""),
            "saldo_anterior": meta.get("saldo_anterior", ""),
            "fecha": tx["fecha"],
            "fecha_valor": tx["fecha_valor"],
            "referencia": tx["referencia"],
            "detalle": tx["detalle"],
            "debito": debito,
            "credito": credito,
            "saldo": saldo_tx,
        })

    return {"meta": meta, "transactions": rows}


def listar_pdfs(directorio: str) -> List[str]:
    """PDFs de un directorio, ordenados de forma natural (2 antes que 10)."""
    from pathlib import Path

    def clave(p) -> Any:
        return [int(t) if t.isdigit() else t.lower()
                for t in re.split(r"(\d+)", p.name)]

    pdfs = [p for p in Path(directorio).iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"]
    return [str(p) for p in sorted(pdfs, key=clave)]


def escribir_csv(registros: List[Dict[str, Any]], ruta_salida: str) -> None:
    """Escribe el CSV con BOM UTF-8 para que Excel lo abra bien."""
    with open(ruta_salida, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in registros:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def procesar_pdfs(pdfs: List[str], ruta_csv: str,
                  aviso=None) -> List[Dict[str, Any]]:
    """Extrae todos los PDFs y escribe un unico CSV. Devuelve las filas.

    ``aviso`` es un callback opcional ``f(texto)`` para ir informando a la GUI.
    Un PDF que falle no aborta el lote: se avisa y se continua con el resto.
    """
    def _di(texto: str) -> None:
        if aviso:
            aviso(texto)

    todas: List[Dict[str, Any]] = []
    for path in pdfs:
        _di("Procesando: %s" % path)
        try:
            data = parse_pdf(path)
            txs = data["transactions"]
            todas.extend(txs)
            _di("   -> %d movimiento(s) | cuenta %s | estado %s" % (
                len(txs), data["meta"].get("cuenta_no", "?"),
                data["meta"].get("estado_no", "")))
        except Exception as exc:            # noqa: BLE001 - queremos seguir
            _di("   ERROR en %s: %s" % (path, exc))

    escribir_csv(todas, ruta_csv)
    _di("CSV generado: %s (%d filas)" % (ruta_csv, len(todas)))
    return todas
