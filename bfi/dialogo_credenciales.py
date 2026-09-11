"""Dialogo modal para configurar las credenciales de Ninox.

Evita el ``setx`` en una terminal: el usuario pega los tres valores, pulsa
Guardar y quedan escritos en su perfil de Windows (ver
``configuracion_usuario.guardar_credenciales``).

Es modal de verdad (``grab_set`` + ``wait_window``), porque un dialogo de
credenciales que se pueda dejar de lado acaba con el usuario trabajando con una
configuracion a medias.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, Optional

from .config import ENV_API_KEY, ENV_DB_ID, ENV_TEAM_ID
from .configuracion_usuario import (credenciales_actuales,
                                    guardar_credenciales)

AYUDA = (
    "Estos tres datos los facilita el administrador de la base de datos Ninox.\n"
    "Se guardan en tu usuario de Windows, no hace falta ser administrador y no\n"
    "hay que volver a escribirlos."
)

CAMPOS = (
    (ENV_API_KEY, "Clave de la API (NINOX_API_KEY)", True),
    (ENV_TEAM_ID, "Identificador del equipo (NINOX_TEAM_ID)", False),
    (ENV_DB_ID, "Identificador de la base de datos (NINOX_DB_ID)", False),
)


class DialogoCredenciales(tk.Toplevel):
    """Ventana modal. Tras crearla, ``self.guardado`` dice si se guardaron."""

    def __init__(self, padre: tk.Misc, motivo: str = "") -> None:
        super().__init__(padre)
        self.title("Configuracion de acceso a Ninox")
        self.resizable(False, False)
        self.transient(padre)
        self.guardado = False
        self._vars: Dict[str, tk.StringVar] = {}

        marco = ttk.Frame(self, padding=14)
        marco.grid(sticky="nsew")
        marco.columnconfigure(1, weight=1)

        fila = 0
        if motivo:
            ttk.Label(marco, text=motivo, foreground="#b00020",
                      wraplength=460, justify="left"
                      ).grid(row=fila, column=0, columnspan=2, sticky="w", pady=(0, 8))
            fila += 1
        ttk.Label(marco, text=AYUDA, justify="left"
                  ).grid(row=fila, column=0, columnspan=2, sticky="w", pady=(0, 10))
        fila += 1

        actuales = credenciales_actuales()
        self._entradas: Dict[str, ttk.Entry] = {}
        for nombre, etiqueta, es_secreto in CAMPOS:
            ttk.Label(marco, text=etiqueta + ":").grid(row=fila, column=0,
                                                       sticky="w", pady=3)
            var = tk.StringVar(value=actuales.get(nombre) or "")
            self._vars[nombre] = var
            entrada = ttk.Entry(marco, textvariable=var, width=52,
                                show="\u2022" if es_secreto else "")
            entrada.grid(row=fila, column=1, sticky="ew", padx=(8, 0), pady=3)
            self._entradas[nombre] = entrada
            fila += 1

        self.mostrar = tk.BooleanVar(value=False)
        ttk.Checkbutton(marco, text="Mostrar la clave",
                        variable=self.mostrar,
                        command=self._alternar_clave
                        ).grid(row=fila, column=1, sticky="w", pady=(2, 8))
        fila += 1

        botones = ttk.Frame(marco)
        botones.grid(row=fila, column=0, columnspan=2, sticky="e", pady=(6, 0))
        ttk.Button(botones, text="Cancelar", command=self._cancelar).grid(row=0, column=0,
                                                                         padx=4)
        ttk.Button(botones, text="Guardar", command=self._guardar).grid(row=0, column=1)

        self.protocol("WM_DELETE_WINDOW", self._cancelar)
        self.bind("<Return>", lambda _e: self._guardar())
        self.bind("<Escape>", lambda _e: self._cancelar())
        self.grab_set()
        self.wait_window(self)

    # ------------------------------------------------------------------ interno
    def _alternar_clave(self) -> None:
        entrada = self._entradas.get(ENV_API_KEY)
        if entrada is not None:
            entrada.configure(show="" if self.mostrar.get() else "\u2022")

    def _guardar(self) -> None:
        valores = {k: v.get() for k, v in self._vars.items()}
        ok, mensaje = guardar_credenciales(valores)
        if not ok:
            messagebox.showerror("No se pudo guardar", mensaje, parent=self)
            return
        self.guardado = True
        messagebox.showinfo("Configuracion guardada", mensaje, parent=self)
        self.destroy()

    def _cancelar(self) -> None:
        self.guardado = False
        self.destroy()


def pedir_credenciales(padre: tk.Misc, motivo: str = "") -> bool:
    """Abre el dialogo y devuelve si el usuario guardo una configuracion valida."""
    dialogo = DialogoCredenciales(padre, motivo)
    return bool(dialogo.guardado)


def hay_credenciales() -> bool:
    """?Estan las tres variables definidas (entorno o registro)?"""
    from .credentials import get_credential
    from .config import ENV_VARS
    return all(get_credential(n) for n in ENV_VARS)


def faltantes() -> Optional[str]:
    """Nombres de las credenciales que faltan, o None si estan todas."""
    from .credentials import get_credential
    from .config import ENV_VARS
    ausentes = [n for n in ENV_VARS if not get_credential(n)]
    return ", ".join(ausentes) if ausentes else None
