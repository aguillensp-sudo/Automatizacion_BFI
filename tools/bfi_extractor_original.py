"""Extractor original de los PDFs del BFI (version de partida, 2026).

SE CONSERVA COMO REFERENCIA, NO SE USA. La aplicacion ejecuta la version
refactorizada y con pruebas de ``bfi/extractor.py``, que produce exactamente las
mismas columnas de CSV.

Este fichero se puede ejecutar por separado:

    python tools/bfi_extractor_original.py <salida.csv> <archivo1.pdf> [mas.pdf]

Nota: su unica diferencia funcional es que escribe el CSV en UTF-8 sin BOM y que
no informa a ninguna interfaz; por lo demas el parseo es identico.
"""
"""
BFI Extractor - Banco Financiero Internacional
Extrae movimientos de extractos bancarios en PDF y genera un CSV estructurado.
"""

import re
import csv
import sys

try:
    import pdfplumber
except ImportError:
    print("ERROR: Instala pdfplumber con: pip install pdfplumber")
    sys.exit(1)


# La consola de Windows usa cp1252 por defecto y no puede representar los
# caracteres no ASCII de los mensajes de progreso, lo que aborta el script.
# Forzamos UTF-8 en la salida (con reemplazo como ultimo recurso).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fmt_date(d, m, y):
    if len(y) == 2:
        y = "20" + y
    return f"{y}-{m.zfill(2)}-{d.zfill(2)}"


def parse_amount(text):
    text = text.strip()
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
# Regex
# ---------------------------------------------------------------------------

# Línea de movimiento con DOS importes al final (movimiento + saldo)
# Ejemplo: "17 07 26 08 07 26 FT2619151273 TRANSFERENCIA RECIBIDA: USD 7,992.00 31,218.13"
TX_PAT2 = re.compile(
    r"^(\d{2})\s+(\d{2})\s+(\d{2,4})\s+"
    r"(\d{2})\s+(\d{2})\s+(\d{2,4})\s+"
    r"(\S+)\s+"
    r"(.+?)\s+"
    r"([\d,\.]+)\s+([\d,\.]+)\s*$"
)

# Línea de movimiento con UN importe al final (saldo)
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
    re.I
)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_pdf(pdf_path: str) -> dict:
    meta = {}
    transactions = []

    with pdfplumber.open(pdf_path) as pdf:
        lines = []
        for page in pdf.pages:
            text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
            lines.extend(text.splitlines())

    # --- Cabecera ---
    for i, line in enumerate(lines):
        m = re.search(
            r"De\s+(\d{2})\s+(\d{2})\s+(\d{2,4})\s+a\s+(\d{2})\s+(\d{2})\s+(\d{2,4})"
            r"(?:\s+(\d{2})\s+(\d{2})\s+(\d{2,4}))?",
            line
        )
        if m and "periodo_desde" not in meta:
            meta["periodo_desde"] = fmt_date(m.group(1), m.group(2), m.group(3))
            meta["periodo_hasta"] = fmt_date(m.group(4), m.group(5), m.group(6))
            if m.group(7):
                meta["fecha_emision"] = fmt_date(m.group(7), m.group(8), m.group(9))

        m2 = re.match(
            r"^(\d{10,20})\s+(USD|CUP|EUR|CUC|MLC)\s+([\d,\.]+)\s+(\d+)\s+(\d+)\s*$",
            line.strip()
        )
        if m2 and "cuenta_no" not in meta:
            meta["cuenta_no"]        = m2.group(1)
            meta["moneda"]           = m2.group(2)
            meta["saldo_disponible"] = parse_amount(m2.group(3))
            meta["estado_no"]        = m2.group(4)
            meta["hoja_no"]          = m2.group(5)

        if line.strip() == "Nombre" and i + 1 < len(lines):
            meta["nombre"] = lines[i + 1].strip()

        m3 = SALDO_ANT.search(line)
        if m3 and "saldo_anterior" not in meta:
            meta["saldo_anterior"] = parse_amount(m3.group(1))

        m4 = SALDO_FAV.search(line)
        if m4:
            meta["saldo_final"] = parse_amount(m4.group(1))

    # --- Movimientos ---
    current = None

    for line in lines:
        if SKIP_PAT.search(line):
            continue
        if SALDO_ANT.search(line) or SALDO_FAV.search(line):
            if current:
                transactions.append(current)
                current = None
            continue

        # Dos importes al final
        m = TX_PAT2.match(line)
        if m:
            if current:
                transactions.append(current)
            d1,m1,y1, d2,m2,y2, ref, detalle, imp1, imp2 = m.groups()
            current = {
                "fecha":       fmt_date(d1, m1, y1),
                "fecha_valor": fmt_date(d2, m2, y2),
                "referencia":  ref,
                "detalle":     detalle.strip(),
                "_imp_mov":    parse_amount(imp1),
                "_saldo":      parse_amount(imp2),
            }
            continue

        # Un importe al final
        m = TX_PAT1.match(line)
        if m:
            if current:
                transactions.append(current)
            d1,m1,y1, d2,m2,y2, ref, detalle, imp1 = m.groups()
            current = {
                "fecha":       fmt_date(d1, m1, y1),
                "fecha_valor": fmt_date(d2, m2, y2),
                "referencia":  ref,
                "detalle":     detalle.strip(),
                "_imp_mov":    None,
                "_saldo":      parse_amount(imp1),
            }
            continue

        # Continuación del detalle
        if current and line.strip():
            current["detalle"] += " " + line.strip()

    if current:
        transactions.append(current)

    # --- Asignar débito / crédito ---
    saldo_prev = meta.get("saldo_anterior")
    rows = []
    for tx in transactions:
        saldo_tx = tx["_saldo"]
        imp_mov  = tx["_imp_mov"]

        debito = credito = None
        if saldo_prev is not None and saldo_tx is not None:
            diff = round(saldo_tx - saldo_prev, 2)
            if diff < 0:
                debito  = imp_mov if imp_mov is not None else abs(diff)
            elif diff > 0:
                credito = imp_mov if imp_mov is not None else diff

        saldo_prev = saldo_tx

        rows.append({
            "cuenta_no":      meta.get("cuenta_no", ""),
            "moneda":         meta.get("moneda", ""),
            "nombre":         meta.get("nombre", ""),
            "estado_no":      meta.get("estado_no", ""),
            "periodo_desde":  meta.get("periodo_desde", ""),
            "periodo_hasta":  meta.get("periodo_hasta", ""),
            "fecha_emision":  meta.get("fecha_emision", ""),
            "saldo_anterior": meta.get("saldo_anterior", ""),
            "fecha":          tx["fecha"],
            "fecha_valor":    tx["fecha_valor"],
            "referencia":     tx["referencia"],
            "detalle":        tx["detalle"],
            "debito":         debito,
            "credito":        credito,
            "saldo":          saldo_tx,
        })

    return {"meta": meta, "transactions": rows}


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------

FIELDNAMES = [
    "cuenta_no", "moneda", "nombre", "estado_no",
    "periodo_desde", "periodo_hasta", "fecha_emision",
    "saldo_anterior",
    "fecha", "fecha_valor", "referencia", "detalle",
    "debito", "credito", "saldo",
]


def write_csv(records: list, output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in records:
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def process_pdfs(pdf_paths: list, output_csv: str):
    all_rows = []
    for path in pdf_paths:
        print(f"  Procesando: {path}")
        try:
            data = parse_pdf(path)
            txs = data["transactions"]
            all_rows.extend(txs)
            print(f"    → {len(txs)} movimiento(s) | estado {data['meta'].get('estado_no','')}")
        except Exception as e:
            import traceback
            print(f"    ERROR en {path}: {e}")
            traceback.print_exc()
    write_csv(all_rows, output_csv)
    print(f"\nCSV generado: {output_csv}  ({len(all_rows)} filas totales)")
    return all_rows


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python bfi_extractor.py <output.csv> <archivo1.pdf> [archivo2.pdf ...]")
        sys.exit(1)
    process_pdfs(sys.argv[2:], sys.argv[1])
