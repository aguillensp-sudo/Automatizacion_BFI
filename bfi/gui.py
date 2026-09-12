"""Interfaz grafica de la aplicacion (tkinter, incluido en Python).

Diseno pensado para usuarios de ofimatica:

* Una sola ventana, pasos numerados de arriba abajo. Nada de menus ni consolas.
* Al elegir la carpeta, la aplicacion **ya cuenta** que hay: PDFs, lineas por
  tabla y cuantas de esas lineas existen ya en Ninox. Asi el usuario decide con
  informacion, no a ciegas.
* El modo por defecto es **SIMULACION**: no escribe nada. Para escribir de
  verdad hay que marcar la casilla y confirmar en un dialogo.
* El boton "Solo extraer a CSV" permite trabajar sin conexion.
* Todo lo que pasa se escribe en la caja de registro y en ``logs/``.
"""
from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from . import APP_NAME, __version__, config
from .dialogo_credenciales import faltantes, pedir_credenciales
from .extractor import listar_pdfs, procesar_pdfs
from .logging_setup import conectar_a_ventana, configurar_logger
from .mapping import ErrorDeMapeo, agrupar_por_tabla, leer_csv
from .ninox_client import NinoxClient
from .ninox_writer import EscritorNinox, ResultadoProceso


class AplicacionBFI(ttk.Frame):
    """Ventana principal."""

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=12)
        self.master: tk.Tk = master
        self.grid(sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        self.logger = configurar_logger(consola=False)
        conectar_a_ventana(self._encolar_log)

        self._cola: "queue.Queue[tuple]" = queue.Queue()
        self._hilo: Optional[threading.Thread] = None
        self._directorio: str = ""
        self._pdfs: List[str] = []
        self._ruta_csv: str = ""
        self._grupos: Dict[str, List[Dict[str, str]]] = {}
        self._duplicados_totales = 0
        self._escritor: Optional[EscritorNinox] = None
        self._pedir_credenciales = False
        self._motivo_credenciales = ""
        # Contenido ya leido y mostrado en la tabla, listo para volcar.
        self._leido = False

        self._construir_widgets()
        self.after(120, self._vaciar_cola)
        self.logger.info("%s v%s iniciado.", APP_NAME, __version__)
        self.after(400, self._comprobar_credenciales_al_arrancar)

    # ------------------------------------------------------------- widgets
    def _construir_widgets(self) -> None:
        pad = dict(padx=6, pady=4)

        # --- 1. carpeta -----------------------------------------------------
        marco1 = ttk.LabelFrame(self, text=" 1. Carpeta con los extractos PDF ", padding=8)
        marco1.grid(row=0, column=0, sticky="ew", **pad)
        marco1.columnconfigure(1, weight=1)

        ttk.Label(marco1, text="Carpeta:").grid(row=0, column=0, sticky="w")
        self.var_carpeta = tk.StringVar()
        ttk.Entry(marco1, textvariable=self.var_carpeta, state="readonly"
                  ).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(marco1, text="Elegir carpeta...",
                   command=self.elegir_carpeta).grid(row=0, column=2)
        self.lbl_resumen = ttk.Label(marco1, text="Ninguna carpeta seleccionada.",
                                     foreground="#555")
        self.lbl_resumen.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))

        ttk.Button(marco1, text="Solo extraer a CSV (sin Ninox)",
                   command=self.solo_extraer).grid(row=2, column=2, sticky="e", pady=(6, 0))
        ttk.Button(marco1, text="Configurar acceso a Ninox...",
                   command=self.configurar_acceso).grid(row=2, column=0, sticky="w",
                                                        pady=(6, 0))
        ttk.Button(marco1, text="Volver a leer esta carpeta",
                   command=self.procesar).grid(row=2, column=1, sticky="w",
                                               padx=6, pady=(6, 0))

        # --- 2. vista previa -------------------------------------------------
        marco2 = ttk.LabelFrame(self, text=" 2. Contenido detectado ", padding=8)
        marco2.grid(row=1, column=0, sticky="nsew", **pad)
        marco2.columnconfigure(0, weight=1)
        marco2.rowconfigure(0, weight=1)
        self.tabla = ttk.Treeview(marco2,
                                  columns=("tabla", "lineas", "nuevas", "duplicadas"),
                                  show="headings", height=5)
        for col, titulo, ancho in (("tabla", "Tabla Ninox", 200),
                                   ("lineas", "Lineas", 80),
                                   ("nuevas", "Nuevas", 80),
                                   ("duplicadas", "Ya existen", 90)):
            self.tabla.heading(col, text=titulo)
            self.tabla.column(col, width=ancho, anchor="center" if col != "tabla" else "w")
        self.tabla.grid(row=0, column=0, sticky="nsew")

        # --- 3. opciones -----------------------------------------------------
        marco3 = ttk.LabelFrame(self, text=" 3. Opciones ", padding=8)
        marco3.grid(row=2, column=0, sticky="ew", **pad)
        self.var_simular = tk.BooleanVar(value=True)
        self.var_omitir_dup = tk.BooleanVar(value=True)
        self.var_verificar = tk.BooleanVar(value=True)
        self.var_corregir = tk.BooleanVar(value=True)
        ttk.Checkbutton(marco3, text="Modo simulacion (no escribe nada en Ninox)",
                        variable=self.var_simular).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(marco3, text="Omitir las lineas que ya existen en Ninox",
                        variable=self.var_omitir_dup).grid(row=1, column=0, sticky="w")
        ttk.Checkbutton(marco3, text="Comprobar cada registro tras insertarlo",
                        variable=self.var_verificar).grid(row=2, column=0, sticky="w")
        ttk.Checkbutton(marco3,
                        text="Corregir los campos que Ninox descarte en el alta "
                             "(segundo envio)",
                        variable=self.var_corregir).grid(row=3, column=0, sticky="w")

        # --- 4. ejecucion: primero leer, despues volcar ---
        marco4 = ttk.Frame(self)
        marco4.grid(row=3, column=0, sticky="ew", **pad)
        marco4.columnconfigure(0, weight=1)
        self.barra = ttk.Progressbar(marco4, mode="determinate")
        self.barra.grid(row=0, column=0, sticky="ew")
        self.btn_procesar = ttk.Button(marco4, text="Leer PDFs y mostrar el contenido",
                                       command=self.procesar)
        self.btn_procesar.grid(row=0, column=1, padx=(8, 0))
        self.btn_volcar = ttk.Button(marco4, text="Volcar a Ninox",
                                     command=self.volcar, state="disabled")
        self.btn_volcar.grid(row=0, column=2, padx=(8, 0))
        self.lbl_estado = ttk.Label(marco4, text="Preparado.")
        self.lbl_estado.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- 5. registro -----------------------------------------------------
        marco5 = ttk.LabelFrame(self, text=" Registro de actividad ", padding=6)
        marco5.grid(row=4, column=0, sticky="nsew", **pad)
        marco5.columnconfigure(0, weight=1)
        marco5.rowconfigure(0, weight=1)
        self.texto = tk.Text(marco5, height=16, wrap="word", state="disabled",
                             background="#f7f7f7")
        self.texto.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(marco5, command=self.texto.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.texto.configure(yscrollcommand=scroll.set)

    # ------------------------------------------------------- utilidades GUI
    def _encolar_log(self, linea: str) -> None:
        """Lo llama el handler de logging. Nunca bloquea."""
        self._cola.put(("log", linea))

    def _vaciar_cola(self) -> None:
        # Un error inesperado aqui no debe dejar la ventana sorda para siempre:
        # se anota y se sigue vaciando la cola. Antes, una excepcion al pintar la
        # tabla dejaba el bucle de mensajes muerto y la tabla vacia sin rastro.
        try:
            while True:
                tipo, dato = self._cola.get_nowait()
                try:
                    if tipo == "log":
                        self._escribir(dato)
                    elif tipo == "estado":
                        self.lbl_estado.configure(text=dato)
                    elif tipo == "tabla":
                        self._pintar_tabla(dato)
                    elif tipo == "listo_para_volcar":
                        self.lbl_resumen.configure(
                            text="Contenido leido: %d linea(s). Pulsa «Volcar a Ninox» "
                                 "cuando quieras insertarlas." % dato,
                            foreground="#0b6e0b")
                    elif tipo == "popup":
                        self._popup_pendiente = dato
                    elif tipo == "fin":
                        self._al_terminar(dato)
                except Exception as exc:            # noqa: BLE001
                    self.logger.error("Fallo al mostrar el mensaje %r: %s", tipo, exc)
        except queue.Empty:
            pass
        self.after(120, self._vaciar_cola)

    def _escribir(self, linea: str) -> None:
        self.texto.configure(state="normal")
        self.texto.insert("end", linea.rstrip() + "\n")
        self.texto.see("end")
        self.texto.configure(state="disabled")

    def _pintar_tabla(self, grupos: Dict[str, List[Dict[str, str]]]) -> None:
        for item in self.tabla.get_children():
            self.tabla.delete(item)
        for tabla in sorted(grupos):
            filas = grupos[tabla]
            dup = sum(1 for f in filas if f.get("_duplicado"))
            etiqueta = config.TABLA_A_ETIQUETA.get(tabla, tabla)
            self.tabla.insert("", "end", values=(etiqueta, len(filas),
                                                 len(filas) - dup, dup))

    def _ocupado(self, activo: bool, estado: str = "") -> None:
        self.btn_procesar.configure(state="disabled" if activo else "normal")
        # «Volcar» solo se habilita cuando hay contenido leido y la ventana no
        # esta trabajando: asi es imposible intentar volcar algo que no existe.
        self.btn_volcar.configure(
            state="normal" if (self._leido and not activo) else "disabled")
        self.barra.configure(mode="indeterminate" if activo else "determinate")
        if activo:
            self.barra.start(12)
        else:
            self.barra.stop()
            self.barra.configure(value=0)
        if estado:
            self.lbl_estado.configure(text=estado)

    # ------------------------------------------------------------ acciones
    def elegir_carpeta(self) -> None:
        self.logger.info("Abriendo el dialogo para elegir carpeta...")
        carpeta = filedialog.askdirectory(title="Selecciona la carpeta con los PDFs")
        self.logger.info("Dialogo cerrado. Carpeta elegida: %r", carpeta)
        if not carpeta:
            return
        self._directorio = carpeta
        self.var_carpeta.set(carpeta)
        self._pdfs = listar_pdfs(carpeta)
        self.logger.info("Encontrados %d fichero(s) .pdf.", len(self._pdfs))
        # Al cambiar de carpeta se olvida lo leido antes: si no, se volcaria el
        # contenido de la carpeta anterior.
        self._leido = False
        self._grupos = {}
        self._limpiar_tabla()
        self.btn_volcar.configure(state="disabled")
        if not self._pdfs:
            self.lbl_resumen.configure(
                text="No se han encontrado ficheros .pdf en esa carpeta.",
                foreground="#b00020")
            messagebox.showwarning(APP_NAME,
                                   "En esa carpeta no hay ningun fichero .pdf.")
            return
        # Se leen YA, para que el usuario vea el contenido sin tener que pulsar
        # nada. Al principio solo se ponia un mensaje y la tabla seguia vacia
        # hasta pulsar «Procesar», lo que hacia dudar de si algo habia fallado.
        self.lbl_resumen.configure(
            text="%d fichero(s) PDF encontrados. Leyendo su contenido..."
                 % len(self._pdfs), foreground="#0b6e0b")
        self._lanzar(self._tarea_leer, "Leyendo los PDFs...")
        self.logger.info("Lectura solicitada tras elegir la carpeta.")

    def _limpiar_tabla(self) -> None:
        for item in self.tabla.get_children():
            self.tabla.delete(item)

    def solo_extraer(self) -> None:
        if not self._comprobar_carpeta():
            return
        self._lanzar(self._tarea_solo_extraer, "Extrayendo PDFs...")

    def volcar(self) -> None:
        """Segundo paso: escribe en Ninox lo que ya se leyo y se mostro."""
        if not self._comprobar_carpeta():
            return
        if not self._leido:
            # En vez de pedirle al usuario que busque el boton correcto, se lee
            # ahora y se le dice que vuelva a pulsar. Un callejon sin salida es
            # peor que un paso extra.
            self.logger.info("Se pulso «Volcar» sin haber leido: se lee primero.")
            messagebox.showinfo(
                APP_NAME,
                "Todavia no se ha leido el contenido de esta carpeta.\n\n"
                "Se va a leer ahora. Cuando termine, vuelve a pulsar "
                "«Volcar a Ninox».")
            self._lanzar(self._tarea_leer, "Leyendo los PDFs...")
            return
        if not self.var_simular.get():
            if not messagebox.askyesno(
                    APP_NAME,
                    "Vas a INSERTAR registros REALES en el ERP Ninox.\n\n"
                    "Las tablas destino son OD (BFI 05399610), PD (BFI 06074740) "
                    "y TD (BFI 61020).\n"
                    "En Ninox no hay transacciones ni deshacer.\n\n"
                    "¿Continuar?"):
                return
        self._lanzar(self._tarea_volcar, "Procesando...")

    # ------------------------------------------------------- credenciales
    def _comprobar_credenciales_al_arrancar(self) -> None:
        """Si faltan credenciales, se piden aqui y no al fallar el proceso."""
        ausentes = faltantes()
        if ausentes:
            self.logger.warning("Faltan credenciales de Ninox: %s", ausentes)
            self.configurar_acceso(
                "Para volcar a Ninox hace falta configurar el acceso.\n"
                "Faltan: %s" % ausentes)
        else:
            self.logger.info("Credenciales de Ninox encontradas.")

    def configurar_acceso(self, motivo: str = "") -> None:
        """Abre el dialogo de credenciales y comprueba que funcionan."""
        if pedir_credenciales(self, motivo):
            self.logger.info("Comprobando el acceso con Ninox...")
            try:
                escritor = EscritorNinox(aviso=self.logger.info)
                ok, mensaje = escritor.comprobar_conexion()
            except Exception as exc:                    # noqa: BLE001
                ok, mensaje = False, "No se pudo comprobar: %s" % exc
            self.logger.info(mensaje)
            if ok:
                messagebox.showinfo(APP_NAME, "Acceso a Ninox correcto.")
            else:
                messagebox.showwarning(APP_NAME, mensaje)

    def procesar(self) -> None:
        """Primer paso: leer los PDFs y mostrar el contenido. No escribe nada."""
        if not self._comprobar_carpeta():
            return
        self._lanzar(self._tarea_leer, "Leyendo los PDFs...")

    def _comprobar_carpeta(self) -> bool:
        if not self._directorio:
            messagebox.showinfo(APP_NAME, "Primero elige la carpeta con los PDFs.")
            return False
        if not self._pdfs:
            self._pdfs = listar_pdfs(self._directorio)
        if not self._pdfs:
            messagebox.showwarning(APP_NAME, "Esa carpeta no contiene ningun PDF.")
            return False
        return True

    def _lanzar(self, tarea, estado: str) -> None:
        if self._hilo and self._hilo.is_alive():
            # Si el hilo anterior sigue vivo, esta llamada se descartaba EN
            # SILENCIO: el usuario pulsaba y no pasaba nada. Ahora se avisa.
            self.logger.warning("Ya hay un proceso en marcha (%s): no se lanza %s.",
                                getattr(tarea, "__name__", tarea), estado)
            messagebox.showinfo(APP_NAME, "Ya hay un proceso en marcha.")
            return
        self.logger.info("Lanzando '%s'...", estado)
        self._ocupado(True, estado)
        self._hilo = threading.Thread(target=self._envolver, args=(tarea,), daemon=True)
        self._hilo.start()
        self.logger.info("Hilo iniciado para '%s'.", estado)

    def _envolver(self, tarea) -> None:
        nombre = getattr(tarea, "__name__", str(tarea))
        self.logger.info("== Empieza %s ==", nombre)
        try:
            tarea()
            self.logger.info("== Termina %s ==", nombre)
        except Exception as exc:                    # noqa: BLE001
            self.logger.error("Fallo inesperado en %s: %s", nombre, exc)
            self.logger.error(traceback.format_exc())
            self._cola.put(("log", "FALLO: %s" % exc))
            self._cola.put(("estado", "Terminado con errores."))
        finally:
            self._cola.put(("fin", None))

    # --------------------------------------------------------------- tareas
    def _ruta_csv_destino(self) -> str:
        return str(Path(self._directorio) / config.CSV_BASENAME)

    def _tarea_solo_extraer(self) -> None:
        """Extrae los PDFs y deja el CSV. No toca la red ni el ERP."""
        ruta = self._ruta_csv_destino()
        filas = procesar_pdfs(self._pdfs, ruta, aviso=self.logger.info)
        self._cola.put(("log", "Extraccion terminada: %d lineas en %s" % (len(filas), ruta)))
        self._cola.put(("estado", "CSV generado."))

    def _tarea_leer(self) -> None:
        """Lee los PDFs y muestra el contenido. NO escribe en Ninox.

        Es el primer paso, y el unico que hace falta para que el usuario vea lo
        que hay antes de decidir nada. Ademas deja el CSV preparado.
        """
        self.logger.info("Leyendo %d PDF(s) de %s ...", len(self._pdfs), self._directorio)
        ruta = self._ruta_csv_destino()
        filas = procesar_pdfs(self._pdfs, ruta, aviso=self.logger.info)
        self.logger.info("Extraccion terminada: %d linea(s).", len(filas))
        if not filas:
            self._cola.put(("log", "Los PDFs no han producido ninguna linea."))
            self._cola.put(("estado", "Sin lineas que procesar."))
            return
        grupos = agrupar_por_tabla(leer_csv(ruta))
        for tabla in sorted(grupos):
            self.logger.info("Cuenta -> %s: %d linea(s)",
                             config.TABLA_A_ETIQUETA.get(tabla, tabla), len(grupos[tabla]))
        self._grupos = grupos
        self._leido = True
        self._cola.put(("tabla", grupos))
        self.logger.info("Tabla rellenada con %d tabla(s).", len(grupos))
        self._cola.put(("log", "Contenido leido: %d linea(s). El CSV esta en %s"
                        % (len(filas), ruta)))
        self._cola.put(("estado", "Contenido listo. Pulsa «Volcar a Ninox» para insertarlo."))
        self._cola.put(("listo_para_volcar", len(filas)))

    def _tarea_volcar(self) -> None:
        """Comprueba duplicados e inserta (o simula) lo que ya se leyo."""
        ruta = self._ruta_csv_destino()
        if not self._leido or not self._grupos:
            self._cola.put(("log", "No hay contenido leido. Pulsa antes «Leer PDFs»."))
            return
        grupos = {t: [dict(f) for f in filas] for t, filas in self._grupos.items()}

        # --- Conexion y deteccion de duplicados (solo lectura) ---
        self._cola.put(("estado", "Conectando con Ninox..."))
        escritor = EscritorNinox(aviso=self.logger.info)
        ok, mensaje = escritor.comprobar_conexion()
        self.logger.info(mensaje)
        if not ok:
            self._cola.put(("log", "No se pudo preparar la insercion: %s" % mensaje))
            self._cola.put(("log", "El CSV se ha generado igualmente en %s" % ruta))
            self._cola.put(("estado", "Sin conexion con Ninox: solo se genero el CSV."))
            # Se pide la configuracion desde el hilo principal, no desde aqui.
            self._pedir_credenciales = True
            self._motivo_credenciales = mensaje
            return
        self._escritor = escritor

        self._cola.put(("estado", "Buscando lineas ya existentes..."))
        try:
            grupos = escritor.detectar_duplicados(grupos)
        except ErrorDeMapeo as exc:
            self.logger.error("%s", exc)
            self._cola.put(("log", "AVISO: %s" % exc))
            self._cola.put(("log", "Se continua SIN control de duplicados."))
            for tabla in grupos:
                grupos[tabla] = [dict(f, _duplicado=False, _motivo="") for f in grupos[tabla]]

        self._cola.put(("tabla", grupos))
        total_dup = sum(1 for filas in grupos.values() for f in filas if f.get("_duplicado"))
        self._duplicados_totales = total_dup

        # --- Insercion ---
        simular = self.var_simular.get()
        self._cola.put(("estado", "Simulando..." if simular else "Insertando en Ninox..."))
        resultado = escritor.insertar(
            grupos,
            simular=simular,
            omitir_duplicados=self.var_omitir_dup.get(),
            verificar=self.var_verificar.get(),
            corregir=self.var_corregir.get() and self.var_verificar.get(),
        )

        # --- Informe al usuario ---
        self._informar(resultado, ruta)
        # El CSV se borra UNICAMENTE si el volcado fue real y limpio. Si hubo
        # errores se conserva: es la unica prueba de que lineas fallaron.
        if simular:
            self.logger.info("Simulacion: el CSV se conserva en %s", ruta)
        elif resultado.insertados > 0 and resultado.erroneos == 0:
            self.logger.info("Borrando el CSV generado (%s)...", ruta)
            try:
                Path(ruta).unlink()
                self.logger.info("CSV eliminado: %s", ruta)
            except OSError as exc:
                self.logger.warning("No se pudo borrar el CSV: %s", exc)
        elif resultado.erroneos:
            self.logger.warning(
                "El CSV se conserva en %s porque hubo %d linea(s) con error.",
                ruta, resultado.erroneos)

    # ---------------------------------------------------------------- salida
    def _informar(self, resultado: ResultadoProceso, ruta_csv: str) -> None:
        partes: List[str] = []
        if resultado.simulado:
            partes.append("SIMULACION completada — no se ha escrito nada en Ninox.\n")
        else:
            partes.append("Proceso terminado.\n")
        for t in resultado.tablas:
            partes.append("• %s: %d insertada(s), %d omitida(s), %d con error"
                          % (t.etiqueta, t.insertados, t.omitidos, t.erroneos))
        if self.var_omitir_dup.get() and resultado.omitidos:
            partes.append("\nSe han omitido %d linea(s) que ya estaban en el ERP."
                          % resultado.omitidos)
        if resultado.erroneos:
            partes.append("\n%d linea(s) fallaron. Detalle en el registro y en "
                          "la carpeta logs." % resultado.erroneos)
        discrepancias = [d for t in resultado.tablas for d in t.discrepancias]
        corregidos = [c for t in resultado.tablas for c in t.corregidos]
        if corregidos:
            partes.append("\n%d campo(s) se habian quedado con el valor por defecto "
                          "de Ninox y se corrigieron con un segundo envio "
                          "(detalle en el registro)." % len(corregidos))
        if discrepancias:
            partes.append("\n%d campo(s) no se pudieron guardar (Ninox los calcula "
                          "y no admite escritura). Detalle en el registro."
                          % len(discrepancias))
        if resultado.simulado and resultado.insertados:
            partes.append("\nPara escribir de verdad, desmarca «Modo simulacion» "
                          "y vuelve a pulsar Procesar.")
        texto = "\n".join(partes)
        self.logger.info("RESULTADO:\n%s", texto)
        self._cola.put(("estado", "Terminado."))
        self._cola.put(("popup", texto))

    def _al_terminar(self, _dato: Any) -> None:
        self._ocupado(False, "")
        if self._pedir_credenciales:
            self._pedir_credenciales = False
            motivo = self._motivo_credenciales
            self._motivo_credenciales = ""
            self.configurar_acceso(motivo)
        texto, self._popup_pendiente = self._popup_pendiente, ""
        if texto:
            messagebox.showinfo(APP_NAME, texto)

    # Mensaje de resultado que el hilo deja para mostrar al terminar.
    _popup_pendiente = ""


def main() -> int:
    raiz = tk.Tk()
    raiz.title("%s v%s" % (APP_NAME, __version__))
    raiz.geometry("880x720")
    raiz.minsize(760, 620)
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    app = AplicacionBFI(raiz)
    raiz.mainloop()
    return 0
