"""Prueba de la INTERFAZ GRAFICA por su camino real.

Las demas pruebas cubren la logica (mapeo, extraccion, escritura). Esta cubre lo
unico que faltaba: que la ventana haga de verdad lo que promete cuando el usuario
elige una carpeta y pulsa «Procesar».

Metodo: se construye la ventana real, se le inyecta la carpeta (como si la
hubiera elegido) y se ejecuta ``_tarea_procesar`` —la misma funcion que corre en
el hilo de trabajo—, drenando la cola de mensajes como hace el bucle de eventos.
Se neutralizan solo los dialogos modales (``messagebox`` y el de credenciales),
que si no bloquearian la prueba esperando un clic.

Requiere:
  * los extractos PDF en la carpeta del proyecto (no se versionan por ser datos
    reales de clientes). Si no estan, las pruebas que dependen de ellos se
    SALTAN en lugar de fallar.
  * credenciales de Ninox en el entorno: sin ellas, Ninox no se toca y solo se
    comprueba la parte de extraccion.

Uso:
    python -m pytest tests/test_gui.py -q -s
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bfi import config                                   # noqa: E402
from bfi.extractor import listar_pdfs                    # noqa: E402

tk = pytest.importorskip("tkinter", reason="tkinter no disponible")


def _buscar_pdfs():
    """Extractos de prueba, buscando en los sitios donde suelen estar.

    Los PDFs son datos reales de clientes y no se versionan, asi que su ubicacion
    cambia: en el proyecto durante el desarrollo, y en la carpeta de la
    aplicacion cuando alguien copia el programa para usarlo. Se admite tambien
    la variable de entorno ``BFI_PDFS`` para apuntar a cualquier otra carpeta.
    """
    candidatas = []
    if os.environ.get("BFI_PDFS"):
        candidatas.append(Path(os.environ["BFI_PDFS"]))
    candidatas.append(RAIZ)
    candidatas.append(RAIZ / "BFI Extractor")
    for carpeta in candidatas:
        if carpeta.is_dir():
            encontrados = listar_pdfs(str(carpeta))
            if encontrados:
                return encontrados
    return []


PDFS = _buscar_pdfs()
sin_pdfs = pytest.mark.skipif(
    not PDFS,
    reason="no se han encontrado extractos PDF (pon BFI_PDFS=<carpeta> para indicarlos)")


@pytest.fixture(scope="module")
def raiz_tk():
    """Una UNICA raiz de Tk para todo el modulo.

    Crear y destruir una raiz por prueba funciona, pero deja a Tcl en un estado
    que hace fallar de forma intermitente la siguiente inicializacion
    ("Can't find a usable tk.tcl" / "Tcl wasn't installed properly"). No es un
    problema de la aplicacion: lo mismo se reproduce en cualquier suite que
    cree varias raices. Con una sola raiz compartida las pruebas son estables.

    Si el entorno no puede inicializar Tk en absoluto (una instalacion de Python
    sin las librerias de Tcl/Tk), se saltan las pruebas en lugar de fallar: el
    `.exe` que se entrega al usuario lleva sus propias Tcl/Tk empaquetadas y no
    depende de esto.
    """
    try:
        raiz = tk.Tk()
    except tk.TclError as exc:                    # pragma: no cover
        pytest.skip("Tk no se puede inicializar en este entorno: %s" % exc)
    raiz.withdraw()
    yield raiz
    try:
        raiz.destroy()
    except tk.TclError:
        pass


def _hay_credenciales() -> bool:
    try:
        from bfi.dialogo_credenciales import hay_credenciales
        return hay_credenciales()
    except Exception:            # noqa: BLE001
        return False


class VentanaDePrueba:
    """Envuelve la ventana real y simula los clics del usuario."""

    def __init__(self, monkeypatch, tmp_path, raiz, con_pdfs=True):
        from bfi import gui as modulo_gui

        # Dialogos modales: se anulan y se registra que se habrian mostrado.
        self.mensajes = []
        monkeypatch.setattr(modulo_gui.messagebox, "showinfo",
                            lambda *a, **k: self.mensajes.append(("info", a[-1])))
        monkeypatch.setattr(modulo_gui.messagebox, "showwarning",
                            lambda *a, **k: self.mensajes.append(("aviso", a[-1])))
        monkeypatch.setattr(modulo_gui.messagebox, "showerror",
                            lambda *a, **k: self.mensajes.append(("error", a[-1])))
        monkeypatch.setattr(modulo_gui.messagebox, "askyesno", lambda *a, **k: True)
        # El arranque pide credenciales si faltan: no queremos ese dialogo aqui.
        monkeypatch.setattr(modulo_gui.AplicacionBFI,
                            "_comprobar_credenciales_al_arrancar", lambda self: None)

        # La ventana principal es un Toplevel sobre la raiz compartida: al
        # destruirla solo se cierra esa ventana, no el interprete de Tcl.
        self.ventana = tk.Toplevel(raiz)
        self.ventana.withdraw()
        self.app = modulo_gui.AplicacionBFI(self.ventana)
        self.ventana.update()

        # Simula «Elegir carpeta...»: escribe el estado que dejaria el dialogo.
        self.app._directorio = str(tmp_path)
        self.app._pdfs = listar_pdfs(str(tmp_path)) if con_pdfs else []
        self.app.var_carpeta.set(str(tmp_path))

    def leer(self):
        """Primer paso: «Leer PDFs y mostrar el contenido». No escribe en Ninox."""
        self.app._tarea_leer()
        self.app._cola.put(("fin", None))
        self.procesar_cola()
        return self

    def volcar(self):
        """Segundo paso: «Volcar a Ninox» (en simulacion o de verdad)."""
        self.app._tarea_volcar()
        self.app._cola.put(("fin", None))
        self.procesar_cola()
        return self

    def ejecutar_solo_extraer(self):
        self.app._tarea_solo_extraer()
        self.app._cola.put(("fin", None))
        self.procesar_cola()
        return self

    def procesar_cola(self):
        """Equivale a unos ciclos del bucle de eventos.

        Se llama a ``_vaciar_cola`` **directamente**: es el mismo metodo que la
        ventana programa con ``after(120, ...)`` en su bucle real, pero en una
        prueba los temporizadores de Tk no se disparan de forma fiable (ni
        ``update`` ni ``update_idletasks`` los ejecutan), asi que esperarlos
        haria la prueba intermitente. ``update`` se mantiene despues para que la
        ventana procese lo que haya quedado pendiente.
        """
        self.app._vaciar_cola()
        self.ventana.update_idletasks()
        self.ventana.update()

    @property
    def texto_registro(self) -> str:
        return self.app.texto.get("1.0", "end")

    def filas_tabla(self):
        return [self.app.tabla.item(i)["values"] for i in self.app.tabla.get_children()]

    def cerrar(self):
        try:
            self.ventana.destroy()
        except tk.TclError:
            pass


@pytest.fixture
def ventana(monkeypatch, tmp_path, raiz_tk):
    """Ventana con los PDFs reales copiados a un directorio temporal."""
    destino = tmp_path / "extractos"
    destino.mkdir()
    for p in PDFS:
        (destino / Path(p).name).write_bytes(Path(p).read_bytes())
    v = VentanaDePrueba(monkeypatch, destino, raiz_tk)
    yield v
    v.cerrar()


# ---------------------------------------------------------------------------
# La ventana se construye con todo lo que el usuario necesita
# ---------------------------------------------------------------------------

def test_la_ventana_arranca_con_las_opciones_en_su_sitio(monkeypatch, tmp_path, raiz_tk):
    v = VentanaDePrueba(monkeypatch, tmp_path, raiz_tk, con_pdfs=False)
    try:
        # El mensaje de arranque se registra DURANTE la construccion de la
        # ventana, asi que hay que drenar la cola para verlo en la caja.
        v.procesar_cola()
        assert v.app.var_simular.get() is True, \
            "el modo simulacion debe venir activado: es la red de seguridad"
        assert v.app.var_omitir_dup.get() is True
        assert v.app.var_verificar.get() is True
        assert v.app.var_corregir.get() is True
        assert tuple(v.app.tabla["columns"]) == ("tabla", "lineas", "nuevas", "duplicadas")
        assert "iniciado" in v.texto_registro, \
            "la caja de registro debe recibir las lineas del registro de la app"
    finally:
        v.cerrar()


# ---------------------------------------------------------------------------
# «Solo extraer a CSV»: no debe tocar Ninox
# ---------------------------------------------------------------------------

@sin_pdfs
def test_solo_extraer_genera_el_csv_y_deja_el_fichero(ventana):
    ventana.ejecutar_solo_extraer()
    csv = Path(ventana.app._directorio) / config.CSV_BASENAME
    assert csv.exists(), "el CSV debe quedar en la carpeta elegida por el usuario"
    lineas = csv.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(lineas) == 45, "44 movimientos + cabecera"
    assert "CSV generado" in ventana.texto_registro
    assert "No se pudo conectar" not in ventana.texto_registro


# ---------------------------------------------------------------------------
# Paso 1: «Leer PDFs» rellena la tabla SIN escribir en Ninox
# ---------------------------------------------------------------------------

@sin_pdfs
def test_leer_rellena_la_tabla_y_no_toca_ninox(ventana):
    """Al leer, la tabla debe mostrar el contenido de inmediato.

    Esta prueba existe por un problema real de uso: la ventana decia «20 ficheros
    PDF encontrados» pero dejaba la tabla vacia hasta pulsar «Procesar», asi que
    el usuario no sabia si algo habia fallado o si faltaba un paso.
    """
    ventana.leer()

    filas = ventana.filas_tabla()
    assert len(filas) == 3, "deben aparecer OD, PD y TD en la tabla"
    total = sum(int(f[1]) for f in filas)
    assert total == 44, "la tabla debe sumar las 44 lineas del extracto"

    # Y sin haber tocado el ERP: no debe aparecer ni la conexion con Ninox.
    registro = ventana.texto_registro
    assert "Conexion con Ninox" not in registro
    assert "Conectando con Ninox" not in registro
    assert "Mapeo validado" not in registro, "leer no debe conectar con Ninox"

    # El boton de volcar queda disponible solo despues de leer.
    assert str(ventana.app.btn_volcar["state"]) == "normal"
    assert "Contenido leido: 44 linea(s)" in ventana.app.lbl_resumen["text"]


@sin_pdfs
def test_volcar_sin_haber_leido_avisa_y_no_hace_nada(monkeypatch, tmp_path, raiz_tk):
    """Pulsar «Volcar» antes de leer debe avisar, no volcar la carpeta anterior."""
    destino = tmp_path / "extractos"
    destino.mkdir()
    # Se copian PDFs para que el unico motivo del aviso sea no haber leido.
    for p in PDFS[:2]:
        (destino / Path(p).name).write_bytes(Path(p).read_bytes())

    v = VentanaDePrueba(monkeypatch, destino, raiz_tk)
    try:
        v.procesar_cola()
        v.mensajes.clear()
        v.app.volcar()
        assert v.mensajes, "debe avisarse al usuario"
        tipo, texto = v.mensajes[-1]
        assert tipo == "info", v.mensajes
        assert "leer" in texto.lower(), texto
        assert str(v.app.btn_volcar["state"]) == "disabled"
        # Y no debe haber conectado con Ninox ni escrito nada.
        assert "Conectando con Ninox" not in v.texto_registro
    finally:
        v.cerrar()


# ---------------------------------------------------------------------------
# Paso 2: «Volcar» en modo simulacion recorre todo y NO escribe
# ---------------------------------------------------------------------------

@sin_pdfs
def test_volcar_en_simulacion_recorre_todo_el_flujo(ventana):
    ventana.app.var_simular.set(True)
    ventana.leer()
    ventana.volcar()

    registro = ventana.texto_registro
    # Los pasos que el usuario debe ver en la caja de registro.
    assert "Mapeo validado para OD" in registro
    assert "Mapeo validado para PD" in registro
    assert "Mapeo validado para TD" in registro
    assert "MODO SIMULACION" in registro

    # La tabla debe seguir mostrando el contenido.
    filas = ventana.filas_tabla()
    assert len(filas) == 3, "deben aparecer OD, PD y TD en la vista previa"
    total = sum(int(f[1]) for f in filas)
    assert total == 44, "la vista previa debe sumar las 44 lineas del extracto"

    # En simulacion el CSV se conserva.
    csv = Path(ventana.app._directorio) / config.CSV_BASENAME
    assert csv.exists(), "en simulacion no se debe borrar el CSV"
    assert "Simulacion: el CSV se conserva" in registro

    # Y se avisa al usuario con el resumen final.
    assert ventana.mensajes, "debe mostrarse el resumen al terminar"
    tipo, texto = ventana.mensajes[-1]
    assert tipo == "info"
    assert "SIMULACION" in texto
    assert "OD" in texto and "PD" in texto and "TD" in texto


@sin_pdfs
def test_la_vista_previa_no_marca_duplicados_cuando_no_los_hay(ventana):
    ventana.app.var_simular.set(True)
    ventana.leer()
    ventana.volcar()
    for _tabla, lineas, nuevas, duplicadas in ventana.filas_tabla():
        assert int(duplicadas) == 0, "no hay duplicados: DF estaba vacia"
        assert int(nuevas) == int(lineas)


# ---------------------------------------------------------------------------
# Segunda pasada: la ventana debe avisar de los duplicados
# ---------------------------------------------------------------------------

@sin_pdfs
@pytest.mark.skipif(not _hay_credenciales(),
                    reason="sin credenciales de Ninox no se puede comprobar duplicados")
def test_una_segunda_pasada_detecta_lo_ya_insertado(monkeypatch, tmp_path, raiz_tk):
    """Inserta de verdad en DF (tabla de prueba), y vuelve a pasar.

    Es la prueba que cierra el circulo: la ventana debe decir al usuario cuantas
    lineas ya existen antes de volver a insertar nada.
    """
    destino = tmp_path / "extractos"
    destino.mkdir()
    for p in PDFS:
        (destino / Path(p).name).write_bytes(Path(p).read_bytes())

    from bfi.ninox_client import NinoxClient
    cli = NinoxClient()
    # Se anota lo que YA hubiera en DF: la tabla es auxiliar y puede tener
    # residuos de otra prueba. La prueba mide su propio efecto, no el estado
    # absoluto de la tabla.
    ids_antes = {r["id"] for r in cli.fetch_all_records(config.TABLA_TEST, use_cache=False)}

    v = VentanaDePrueba(monkeypatch, destino, raiz_tk)
    creados = []
    try:
        from bfi import gui as modulo_gui
        original = modulo_gui.EscritorNinox

        class EscritorDirigido(original):
            """Redirige a DF tanto la busqueda de duplicados como la escritura.

            Hay que redirigir LAS DOS: ``detectar_duplicados`` recibe el mapeo de
            tablas del CSV, asi que sin esto la prueba compararia contra las
            tablas de negocio reales (llego a leer TD con sus 866 registros) y
            ademas escribiria en DF lo que no esta en DF.
            """

            def detectar_duplicados(self, grupos):
                todos = [f for filas in grupos.values() for f in filas]
                return super().detectar_duplicados({config.TABLA_TEST: todos})

            def insertar(self, grupos, **kwargs):
                todos = [f for filas in grupos.values() for f in filas]
                return super().insertar({config.TABLA_TEST: todos}, **kwargs)

        monkeypatch.setattr(modulo_gui, "EscritorNinox", EscritorDirigido)

        v.app.var_simular.set(False)
        v.leer()
        v.volcar()
        registro = v.texto_registro
        assert "44 insertada(s), 0 omitida(s), 0 con error" in registro, registro[-900:]

        # Recoger lo creado por ESTA prueba, para limpiarlo pase lo que pase.
        creados = [r for r in cli.fetch_all_records(config.TABLA_TEST, use_cache=False)
                   if r["id"] not in ids_antes]
        assert len(creados) == 44, "deberian haberse creado 44 registros nuevos"

        # --- Segunda pasada: sus 44 lineas deben salir como duplicadas ---
        v.leer()
        v.volcar()
        ultimo = v.texto_registro.split("Leyendo")[-1]
        assert "44 linea(s) ya presentes" in ultimo, ultimo[-900:]
        assert "0 insertada(s), 44 omitida(s)" in ultimo
    finally:
        for rec in creados:
            try:
                cli.delete_record(config.TABLA_TEST, rec["id"])
            except Exception:                 # noqa: BLE001
                pass
        v.cerrar()
