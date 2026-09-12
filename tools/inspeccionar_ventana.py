"""Inspecciona la ventana REAL del programa y vuelca lo que encuentra.

Sirve para saber que version esta ejecutando el usuario: se abre la ventana de
verdad y se pregunta por sus botones y su estado. No depende de leer el codigo
fuente ni de adivinar.

Escribe el resultado en la consola y en un fichero de texto.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    lineas = []

    def di(*partes):
        texto = " ".join(str(p) for p in partes)
        print(texto)
        lineas.append(texto)

    try:
        import tkinter as tk
        from bfi import gui as g

        di("Modulo de la ventana:", g.__file__)
        raiz = tk.Tk()
        raiz.withdraw()
        app = g.AplicacionBFI(raiz)
        raiz.update_idletasks()
        raiz.update()

        di()
        di("=== BOTONES DE LA VENTANA (etiqueta -> estado) ===")
        for nombre in ("btn_procesar", "btn_volcar"):
            widget = getattr(app, nombre, None)
            if widget is None:
                di("   %-14s NO EXISTE" % nombre)
            else:
                try:
                    di("   %-14s '%s'  estado=%s"
                       % (nombre, widget.cget("text"), widget.cget("state")))
                except Exception as exc:            # noqa: BLE001
                    di("   %-14s error al leer: %s" % (nombre, exc))

        di()
        di("=== METODOS INTERNOS ===")
        for nombre in ("_tarea_leer", "_tarea_volcar", "_tarea_procesar",
                       "procesar", "volcar", "elegir_carpeta"):
            di("   %-20s %s" % (nombre, "existe" if hasattr(app, nombre) else "NO EXISTE"))

        di()
        di("=== COMPORTAMIENTO: rellenar la tabla ===")
        import tempfile
        from bfi import config
        from bfi.extractor import listar_pdfs

        # Carpeta de la aplicacion, donde estan los PDFs en este equipo.
        candidatas = [
            Path(__file__).resolve().parents[1] / "BFI Extractor" / "Extractos",
            Path(__file__).resolve().parents[1],
        ]
        elegida = next((c for c in candidatas if listar_pdfs(str(c))), None)
        if elegida is None:
            di("   (no hay PDFs para probar)")
        else:
            pdfs = listar_pdfs(str(elegida))
            di("   Carpeta de prueba: %s (%d PDFs)" % (elegida, len(pdfs)))
            app._directorio = str(elegida)
            app._pdfs = pdfs
            if hasattr(app, "_tarea_leer"):
                app._tarea_leer()
                app._vaciar_cola()
                raiz.update_idletasks()
                raiz.update()
                filas = [app.tabla.item(i)["values"] for i in app.tabla.get_children()]
                di("   Filas en la tabla tras leer: %d" % len(filas))
                for f in filas:
                    di("      %s" % (f,))
                di("   Etiqueta de resumen: %r" % app.lbl_resumen.cget("text"))
                di("   Estado del boton volcar: %s" % app.btn_volcar.cget("state"))
            else:
                di("   !! Esta version NO tiene _tarea_leer: es la ANTIGUA")
        raiz.destroy()
    except Exception:                                # noqa: BLE001
        di("FALLO:")
        di(traceback.format_exc())

    salida = Path(__file__).resolve().parents[1] / "logs" / "inspeccion_ventana.txt"
    salida.parent.mkdir(exist_ok=True)
    salida.write_text("\n".join(lineas), encoding="utf-8")
    print("\n(guardado en %s)" % salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
