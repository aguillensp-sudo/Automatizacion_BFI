"""Punto de entrada: ``python -m bfi_agente``.

Se anade la raiz del proyecto al ``sys.path`` porque la tarea programada puede
arrancar el modulo con un directorio de trabajo distinto del repositorio.
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from bfi_agente.cli import main      # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
