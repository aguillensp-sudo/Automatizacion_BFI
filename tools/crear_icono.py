"""Genera el icono de la aplicacion (recursos/bfi.ico) sin dependencias.

Un .ico es una cabecera ICONDIR + ICONDIRENTRY + un DIB (BITMAPINFOHEADER con
altura doble porque incluye la mascara AND). Se construye a mano para no anadir
Pillow al proceso de compilacion.

Diseno: cuadrado verde con una banda blanca que sugiere un extracto bancario.
"""
from __future__ import annotations

import struct
from pathlib import Path

LADO = 64
VERDE = (0x1F, 0x7A, 0x3D)      # BGR abajo
BLANCO = (0xFF, 0xFF, 0xFF)
GRIS = (0xE8, 0xE8, 0xE8)


def pixel(x: int, y: int) -> tuple:
    """Color BGR de cada pixel del icono."""
    margen = 6
    if x < margen or y < margen or x >= LADO - margen or y >= LADO - margen:
        return None                                  # transparente
    # Tres "lineas de texto" blancas sobre fondo verde.
    lineas = ((16, 20), (28, 32), (40, 44))
    for y0, y1 in lineas:
        if y0 <= y <= y1:
            if x < 14 or x > LADO - 14:
                return None
            return BLANCO if x <= LADO - 24 else GRIS
    return VERDE


def dib() -> bytes:
    """BITMAPINFOHEADER + pixeles BGRA (abajo arriba) + mascara AND."""
    cabecera = struct.pack("<IiiHHIIiiII", 40, LADO, LADO * 2, 1, 32, 0,
                           LADO * LADO * 4, 0, 0, 0, 0)
    filas = []
    for y in range(LADO - 1, -1, -1):
        fila = bytearray()
        for x in range(LADO):
            color = pixel(x, y)
            if color is None:
                fila += b"\x00\x00\x00\x00"
            else:
                b, g, r = color
                fila += bytes((b, g, r, 0xFF))
        filas.append(bytes(fila))
    mascara_fila = ((LADO + 31) // 32) * 4
    mascara = bytes(mascara_fila * LADO)
    return cabecera + b"".join(filas) + mascara


def main() -> int:
    destino = Path(__file__).resolve().parents[1] / "recursos"
    destino.mkdir(exist_ok=True)
    datos = dib()
    cabecera = struct.pack("<HHH", 0, 1, 1)
    entrada = struct.pack("<BBBBHHII", LADO, LADO, 0, 0, 1, 32, len(datos),
                          len(cabecera) + 16)
    ruta = destino / "bfi.ico"
    ruta.write_bytes(cabecera + entrada + datos)
    print("Icono generado: %s (%d bytes, %dx%d)"
          % (ruta, ruta.stat().st_size, LADO, LADO))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
