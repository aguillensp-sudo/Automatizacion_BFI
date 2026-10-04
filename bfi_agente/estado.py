"""Estado persistente del agente: que correos y adjuntos ya se procesaron.

Sin esto, un reintento o un reenvio volveria a insertar los mismos movimientos
en el ERP. Dos llaves distintas, a proposito:

* el **correo** se identifica por su ``EntryID`` (y de reserva por el
  ``InternetMessageID``), y
* cada **adjunto** por el sha256 de su contenido.

La segunda es la que evita el duplicado real: si alguien reenvia el mismo
estado de cuenta dentro de otro correo, el ``EntryID`` cambia pero el PDF no.
"""
from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ESQUEMA = """
CREATE TABLE IF NOT EXISTS correos (
    clave               TEXT PRIMARY KEY,
    internet_message_id TEXT,
    asunto              TEXT,
    remitente           TEXT,
    recibido            TEXT,
    procesado_en        TEXT,
    resultado           TEXT,
    detalle             TEXT
);
CREATE TABLE IF NOT EXISTS adjuntos (
    hash         TEXT PRIMARY KEY,
    clave_correo TEXT,
    nombre       TEXT,
    ruta         TEXT,
    bytes        INTEGER,
    procesado_en TEXT
);
CREATE TABLE IF NOT EXISTS ejecuciones (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    inicio     TEXT,
    fin        TEXT,
    modo       TEXT,
    correos    INTEGER,
    adjuntos   INTEGER,
    insertados INTEGER,
    errores    INTEGER,
    resumen    TEXT
);
"""


def marca_ahora() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def hash_archivo(ruta: Any, bloque: int = 65536) -> str:
    """sha256 del contenido de un fichero."""
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        while True:
            datos = f.read(bloque)
            if not datos:
                break
            h.update(datos)
    return h.hexdigest()


class Estado:
    """Base SQLite con el historial de procesamiento.

    Con ``persistir=False`` (modo simulacion) **no se escribe nada en disco**:
    las consultas miran solo lo registrado durante esta misma ejecucion. Asi una
    prueba con ``--dry-run`` no envenena el estado y no impide que la ejecucion
    real del lunes procese esos correos.
    """

    def __init__(self, ruta: Any, persistir: bool = True) -> None:
        self.ruta = Path(ruta)
        self.persistir = persistir
        self._correos_memoria: Dict[str, str] = {}
        self._adjuntos_memoria: Dict[str, str] = {}
        self.con: Optional[sqlite3.Connection] = None
        if self.persistir:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.con = sqlite3.connect(str(self.ruta))
            self.con.row_factory = sqlite3.Row
            self.con.executescript(ESQUEMA)
            self.con.commit()

    # ------------------------------------------------------------ correos
    def correo_procesado(self, clave: str,
                         internet_message_id: str = "") -> Optional[Dict[str, Any]]:
        """Devuelve el registro previo del correo, o None si es nuevo."""
        if not clave:
            return None
        if self.persistir:
            fila = self.con.execute(  # type: ignore[union-attr]
                "SELECT * FROM correos WHERE clave = ?", (clave,)).fetchone()
            if fila is not None:
                return dict(fila)
            if internet_message_id:
                fila = self.con.execute(  # type: ignore[union-attr]
                    "SELECT * FROM correos WHERE internet_message_id = ?",
                    (internet_message_id,)).fetchone()
                if fila is not None:
                    return dict(fila)
            return None
        if clave in self._correos_memoria:
            return {"clave": clave, "resultado": self._correos_memoria[clave]}
        return None

    def registrar_correo(self, clave: str, internet_message_id: str = "",
                         asunto: str = "", remitente: str = "",
                         recibido: str = "", resultado: str = "",
                         detalle: str = "") -> None:
        if not clave:
            return
        momento = marca_ahora()
        if not self.persistir:
            self._correos_memoria[clave] = resultado
            return
        self.con.execute(  # type: ignore[union-attr]
            "INSERT OR REPLACE INTO correos (clave, internet_message_id, asunto,"
            " remitente, recibido, procesado_en, resultado, detalle)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (clave, internet_message_id, asunto, remitente, recibido,
             momento, resultado, detalle))
        self.con.commit()  # type: ignore[union-attr]

    # ----------------------------------------------------------- adjuntos
    def adjunto_conocido(self, hash_adjunto: str) -> Optional[Dict[str, Any]]:
        if not hash_adjunto:
            return None
        if self.persistir:
            fila = self.con.execute(  # type: ignore[union-attr]
                "SELECT * FROM adjuntos WHERE hash = ?", (hash_adjunto,)).fetchone()
            return dict(fila) if fila is not None else None
        if hash_adjunto in self._adjuntos_memoria:
            return {"hash": hash_adjunto}
        return None

    def registrar_adjunto(self, hash_adjunto: str, clave_correo: str = "",
                          nombre: str = "", ruta: str = "", bytes_: int = 0) -> None:
        if not hash_adjunto:
            return
        if not self.persistir:
            self._adjuntos_memoria[hash_adjunto] = nombre
            return
        self.con.execute(  # type: ignore[union-attr]
            "INSERT OR REPLACE INTO adjuntos (hash, clave_correo, nombre, ruta,"
            " bytes, procesado_en) VALUES (?, ?, ?, ?, ?, ?)",
            (hash_adjunto, clave_correo, nombre, ruta, bytes_, marca_ahora()))
        self.con.commit()  # type: ignore[union-attr]

    # -------------------------------------------------------- ejecuciones
    def iniciar_ejecucion(self, modo: str) -> Optional[int]:
        if not self.persistir:
            return None
        cur = self.con.execute(  # type: ignore[union-attr]
            "INSERT INTO ejecuciones (inicio, modo, correos, adjuntos, insertados,"
            " errores, resumen) VALUES (?, ?, 0, 0, 0, 0, '')",
            (marca_ahora(), modo))
        self.con.commit()  # type: ignore[union-attr]
        return int(cur.lastrowid)

    def cerrar_ejecucion(self, id_ejecucion: Optional[int], correos: int = 0,
                         adjuntos: int = 0, insertados: int = 0, errores: int = 0,
                         resumen: str = "") -> None:
        if not self.persistir or id_ejecucion is None:
            return
        self.con.execute(  # type: ignore[union-attr]
            "UPDATE ejecuciones SET fin = ?, correos = ?, adjuntos = ?, insertados = ?,"
            " errores = ?, resumen = ? WHERE id = ?",
            (marca_ahora(), correos, adjuntos, insertados, errores, resumen,
             id_ejecucion))
        self.con.commit()  # type: ignore[union-attr]

    def ultimas_ejecuciones(self, limite: int = 5) -> List[Dict[str, Any]]:
        if not self.persistir:
            return []
        filas = self.con.execute(  # type: ignore[union-attr]
            "SELECT * FROM ejecuciones ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [dict(f) for f in filas]

    def cerrar(self) -> None:
        if self.con is not None:
            self.con.close()
            self.con = None

    def __enter__(self) -> "Estado":
        return self

    def __exit__(self, *_excepcion: Any) -> None:
        self.cerrar()
