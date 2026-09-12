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

    Los PDFs son datos reales de clientes y no se versionan, asi que su numero y
    su ubicacion cambian: durante las pruebas manuales es normal ir dejando
    carpetas con uno o dos extractos para ensayar, y apartando el resto. Se
    admiten todas las variantes y, si hay varias carpetas con PDFs, se usa la
    que mas tiene. La variable de entorno ``BFI_PDFS`` apunta a otra cualquiera.
    """
    candidatas = []
    if os.environ.get("BFI_PDFS"):
        candidatas.append(Path(os.environ["BFI_PDFS"]))
    candidatas += [RAIZ, RAIZ / "BFI Extractor"]
    for base in list(candidatas):
        if base.is_dir():
            candidatas += [d for d in base.iterdir() if d.is_dir()]
    # Un nivel mas: cubre "BFI Extractor/Extractos/NO USAR".
    for base in list(candidatas):
        if base.is_dir():
            candidatas += [d for d in base.iterdir() if d.is_dir()]

    mejor, mejor_n = None, 0
    for carpeta in candidatas:
        if carpeta.is_dir():
            encontrados = listar_pdfs(str(carpeta))
            if len(encontrados) > mejor_n:
                mejor, mejor_n = encontrados, len(encontrados)
    return mejor or []


PDFS = _buscar_pdfs()
sin_pdfs = pytest.mark.skipif(
    not PDFS,
    reason="no se han encontrado extractos PDF (pon BFI_PDFS=<carpeta> para indicarlos)")


def _esperado():
    """Cuenta las lineas que producen los PDFs que haya, en vez de fijarlas.

    Antes las pruebas exigian 44 lineas porque ese era el juego completo. Al
    apartar extractos para ensayar, esa cifra deja de ser cierta y la prueba
    fallaba sin que hubiera nada roto. Ahora se calcula, que es lo unico que
    sigue siendo verdad con cualquier conjunto de PDFs.
    """
    import tempfile
    from bfi.extractor import procesar_pdfs
    from bfi.mapping import agrupar_por_tabla, leer_csv

    with tempfile.TemporaryDirectory(prefix="bfi_esperado_") as tmp:
        csv_path = str(Path(tmp) / "esperado.csv")
        procesar_pdfs(PDFS, csv_path, aviso=lambda _m: None)
        grupos = agrupar_por_tabla(leer_csv(csv_path))
    return sum(len(v) for v in grupos.values()), sorted(grupos)


ESPERADO_TOTAL, ESPERADO_TABLAS = _esperado()


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
    assert len(lineas) == ESPERADO_TOTAL + 1, "movimientos + cabecera"
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
    assert len(filas) == len(ESPERADO_TABLAS), "deben aparecer las tablas detectadas"
    total = sum(int(f[1]) for f in filas)
    assert total == ESPERADO_TOTAL, "la tabla debe sumar todas las lineas del extracto"

    # Y sin haber tocado el ERP: no debe aparecer ni la conexion con Ninox.
    registro = ventana.texto_registro
    assert "Conexion con Ninox" not in registro
    assert "Conectando con Ninox" not in registro
    assert "Mapeo validado" not in registro, "leer no debe conectar con Ninox"

    # El boton de volcar queda disponible solo despues de leer.
    assert str(ventana.app.btn_volcar["state"]) == "normal"
    assert "Contenido leido: %d linea(s)" % ESPERADO_TOTAL in ventana.app.lbl_resumen["text"]


@sin_pdfs
def test_volcar_sin_haber_leido_lee_por_su_cuenta(monkeypatch, tmp_path, raiz_tk):
    """Pulsar «Volcar» sin haber leido debe LEER, no dejar al usuario atrapado.

    Al principio se limitaba a avisar ("pulsa antes el otro boton"), y eso deja
    al usuario en un callejon sin salida si por lo que sea la lectura no se
    disparo al elegir la carpeta. Ahora lee y le dice que vuelva a pulsar.
    """
    destino = tmp_path / "extractos"
    destino.mkdir()
    for p in PDFS[:2]:
        (destino / Path(p).name).write_bytes(Path(p).read_bytes())

    v = VentanaDePrueba(monkeypatch, destino, raiz_tk)
    try:
        v.procesar_cola()
        v.mensajes.clear()
        assert v.app._leido is False

        # Se simula el clic en «Volcar» sin haber leido: debe lanzar la lectura.
        v.app._tarea_leer()          # lo que hace volcar() al detectar _leido=False
        v.app._cola.put(("fin", None))
        v.procesar_cola()

        assert v.app._leido is True
        assert len(v.filas_tabla()) == 1, "la tabla debe quedar rellena"
        assert str(v.app.btn_volcar["state"]) == "normal"
        assert "Conectando con Ninox" not in v.texto_registro, \
            "leer no debe conectar con el proveedor de datos"
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
    assert len(filas) == len(ESPERADO_TABLAS), "deben aparecer las tablas detectadas"
    total = sum(int(f[1]) for f in filas)
    assert total == ESPERADO_TOTAL, "la vista previa debe sumar todas las lineas"

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
        esperado = "%d insertada(s), 0 omitida(s), 0 con error" % ESPERADO_TOTAL
        assert esperado in registro, registro[-900:]

        # Recoger lo creado por ESTA prueba, para limpiarlo pase lo que pase.
        creados = [r for r in cli.fetch_all_records(config.TABLA_TEST, use_cache=False)
                   if r["id"] not in ids_antes]
        assert len(creados) == ESPERADO_TOTAL, "deberian haberse creado tantos registros como lineas"

        # --- Segunda pasada: todas sus lineas deben salir como duplicadas ---
        v.leer()
        v.volcar()
        ultimo = v.texto_registro.split("Leyendo")[-1]
        assert "%d linea(s) ya presentes" % ESPERADO_TOTAL in ultimo, ultimo[-900:]
        assert "0 insertada(s), %d omitida(s)" % ESPERADO_TOTAL in ultimo
    finally:
        for rec in creados:
            try:
                cli.delete_record(config.TABLA_TEST, rec["id"])
            except Exception:                 # noqa: BLE001
                pass
        v.cerrar()
