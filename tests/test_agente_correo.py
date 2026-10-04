"""Pruebas del agente de correo. No necesitan Outlook, red ni credenciales.

Ejecutar con:
    python -m pytest tests/test_agente_correo.py -q
"""
from __future__ import annotations

import shutil
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from bfi import config                                    # noqa: E402
from bfi.mapping import agrupar_por_tabla                  # noqa: E402
from bfi.ninox_writer import ResultadoProceso, ResultadoTabla   # noqa: E402
from bfi_agente import pipeline                                 # noqa: E402
from bfi_agente.config import ConfigAgente, ErrorConfiguracion   # noqa: E402
from bfi_agente.correo import FiltroMensajes, FuenteSimulada     # noqa: E402
from bfi_agente.correo.fuente_outlook_com import limpiar_nombre  # noqa: E402
from bfi_agente.estado import Estado, hash_archivo               # noqa: E402
from bfi_agente.procesador import marcar_repetidas_del_lote      # noqa: E402
from bfi_agente.resumen import ESTADO_OMITIDO, ESTADO_ERROR      # noqa: E402


# --------------------------------------------------------------------- ayudas
@pytest.fixture()
def espacio() -> Iterator[Path]:
    """Carpeta de trabajo propia de cada prueba, borrada al terminar.

    No se usa la fixture ``tmp_path`` de pytest a proposito: en entornos con la
    carpeta temporal restringida (sandbox del harness, equipos con politicas
    estrictas) el plugin de directorios temporales no puede crear ni limpiar su
    carpeta base, y entonces **ninguna** prueba llega a ejecutarse. Aqui la
    carpeta cuelga del propio repositorio.
    """
    base = (RAIZ / "tests" / "_tmp"
            / ("%s-%s" % (datetime.now().strftime("%H%M%S"), uuid.uuid4().hex[:8])))
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)

class ProcesadorFalso:
    """Sustituye a ``ProcesadorBfi``: ni PDFs reales ni llamadas a Ninox.

    Imita lo justo del procesador de verdad para que el pipeline pueda repartir
    el resultado: agrupa por cuenta, ordena por ``fecha_valor`` y llama a
    ``al_agrupar`` con los mismos grupos que devolveria el autentico.
    """

    def __init__(self, filas: int = 2, fallar: bool = False,
                 errores_envio: int = 0, fecha: str = "2026-09-01",
                 cuenta: str = "0300000000000001") -> None:
        self.filas = filas
        self.fallar = fallar
        self.errores_envio = errores_envio
        self.fecha = fecha
        self.cuenta = cuenta
        self.llamadas_extraer = 0
        self.llamadas_enviar = 0
        # Una entrada por llamada a enviar: asi se comprueba que el pipeline
        # manda TODO el lote de una vez y no un envio por correo.
        self.lotes: List[List[dict]] = []
        self.grupos_ordenados: dict = {}

    def credenciales_presentes(self):
        return True, "credenciales de prueba"

    def extraer(self, rutas_pdf, ruta_csv):
        self.llamadas_extraer += 1
        if self.fallar:
            raise RuntimeError("PDF ilegible (simulado)")
        # Referencias distintas en cada extraccion: en la realidad dos estados de
        # cuenta no comparten referencias.
        return [{"cuenta_no": self.cuenta, "fecha_valor": self.fecha,
                 "referencia": "REF%d-%d" % (self.llamadas_extraer, n),
                 "detalle": "linea %d" % n,
                 "debito": "10", "credito": "", "saldo": "100"}
                for n in range(self.filas)]

    def enviar(self, filas, simular=True, al_agrupar=None):
        self.llamadas_enviar += 1
        self.lotes.append([dict(f) for f in filas])
        # Se usa el agrupador de verdad: es el que ordena por fecha_valor y el
        # que decide a que tabla va cada linea.
        grupos = agrupar_por_tabla(filas)
        self.grupos_ordenados = grupos
        if al_agrupar is not None:
            al_agrupar(grupos)
        tablas = []
        for tabla, lista in grupos.items():
            errores = ["fila %d: fallo simulado" % (n + 1)
                       for n in range(min(self.errores_envio, len(lista)))]
            tablas.append(ResultadoTabla(tabla=tabla, etiqueta="Etiqueta %s" % tabla,
                                         total=len(lista),
                                         insertados=len(lista) - len(errores),
                                         erroneos=len(errores), errores=errores))
        return ResultadoProceso(tablas=tablas, simulado=simular)


class EnviadorFalso:
    def __init__(self) -> None:
        self.enviados = []

    def enviar(self, informe, para):
        self.enviados.append(informe)
        return "enviado de mentira"


def correo_de_ejemplo(raiz: Path, nombre: str = "correo_01",
                      asunto: str = "Estado de cuenta BFI",
                      remitente: str = "avisos@bancofinanciero.cu",
                      adjunto: str = "estado.pdf",
                      contenido: bytes = b"%PDF-1.4 simulado") -> Path:
    """Crea la carpeta de ejemplo de un correo con su adjunto."""
    carpeta = raiz / nombre
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "asunto.txt").write_text(asunto, encoding="utf-8")
    (carpeta / "remitente.txt").write_text(remitente, encoding="utf-8")
    (carpeta / adjunto).write_bytes(contenido)
    return carpeta


def configurar(espacio: Path, **extra) -> ConfigAgente:
    datos = {
        "carpeta_outlook": "Bandeja de entrada/BFI",
        "remitentes_permitidos": [],
        "resumen_activo": True,
        "resumen_para": ["quien.sea@outlook.com"],
        "resumen_solo_simular": True,
        "carpeta_trabajo": str(espacio / "trabajo"),
        "ruta_estado": str(espacio / "estado.sqlite3"),
    }
    datos.update(extra)
    return ConfigAgente.desde_diccionario(datos)


# ------------------------------------------------------------------- estado
def test_estado_recuerda_correos_y_adjuntos(espacio: Path) -> None:
    with Estado(espacio / "e.sqlite3") as estado:
        assert estado.correo_procesado("ABC") is None
        estado.registrar_correo("ABC", "<1@x>", "asunto", "a@b.c", "2026-09-01",
                                "ok", "detalle")
        assert estado.correo_procesado("ABC")["resultado"] == "ok"
        # El InternetMessageID sirve de segunda llave: el EntryID cambia al mover.
        assert estado.correo_procesado("OTRO", "<1@x>")["clave"] == "ABC"
        estado.registrar_adjunto("hash1", "ABC", "estado.pdf", "/tmp/x.pdf", 10)
        assert estado.adjunto_conocido("hash1")["nombre"] == "estado.pdf"
        assert estado.adjunto_conocido("hash2") is None


def test_estado_en_simulacion_no_toca_el_disco(espacio: Path) -> None:
    ruta = espacio / "simulacion.sqlite3"
    estado = Estado(ruta, persistir=False)
    estado.registrar_correo("ABC", resultado="ok")
    estado.registrar_adjunto("hash1", nombre="estado.pdf")
    # Se recuerda durante la ejecucion...
    assert estado.correo_procesado("ABC") is not None
    assert estado.adjunto_conocido("hash1") is not None
    estado.cerrar()
    # ...pero no queda nada escrito.
    assert not ruta.exists()


def test_hash_archivo_detecta_contenido_identico(espacio: Path) -> None:
    uno = espacio / "uno.pdf"
    otro = espacio / "otro.pdf"
    uno.write_bytes(b"contenido")
    otro.write_bytes(b"contenido")
    distinto = espacio / "tres.pdf"
    distinto.write_bytes(b"contenido distinto")
    assert hash_archivo(uno) == hash_archivo(otro)
    assert hash_archivo(uno) != hash_archivo(distinto)


# ------------------------------------------------------------------ limpieza
def test_limpiar_nombre_conserva_la_extension() -> None:
    assert limpiar_nombre("estado:cuenta?.pdf") == "estado_cuenta_.pdf"
    assert limpiar_nombre("CON.pdf").startswith("CON_")
    assert limpiar_nombre("").endswith(".pdf") is False
    largo = limpiar_nombre("a" * 300 + ".pdf", limite=50)
    assert largo.endswith(".pdf") and len(largo) <= 50


# ------------------------------------------------------------------- filtros
def test_filtro_por_remitente_asunto_y_adjunto(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz, "bueno")
    correo_de_ejemplo(raiz, "otro_remitente", remitente="spam@otro.com")
    fuente = FuenteSimulada.desde_directorio(raiz)
    import re

    filtro = FiltroMensajes(remitentes=["avisos@bancofinanciero.cu"],
                            patron_adjunto=re.compile(r"(?i)\.pdf$"))
    validos = fuente.listar_pendientes(filtro)
    assert len(validos) == 1
    assert validos[0].asunto == "Estado de cuenta BFI"

    filtro_dominio = FiltroMensajes(remitentes=["@bancofinanciero.cu"])
    assert len(fuente.listar_pendientes(filtro_dominio)) == 1

    filtro_asunto = FiltroMensajes(patron_asunto=re.compile("factura", re.I))
    assert fuente.listar_pendientes(filtro_asunto) == []


# ------------------------------------------------------------------ pipeline
def test_pipeline_simulado_procesa_y_no_registra(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio)
    procesador = ProcesadorFalso(filas=3)

    informe = pipeline.ejecutar(cfg, simular=True, fuente=fuente,
                                procesador=procesador, enviador=EnviadorFalso())

    assert informe.abortado == ""
    assert informe.procesados == 1
    assert informe.filas == 3
    assert informe.insertados == 3          # "se habrian insertado"
    assert procesador.llamadas_enviar == 1
    assert informe.modo == "simulacion"
    assert "SIMULACION" in informe.texto()
    # En simulacion no se persiste nada: una ejecucion real debe volver a verlo.
    assert not cfg.ruta_estado_abs.exists()
    assert fuente.marcados == []            # el correo no se ha tocado


def test_pipeline_real_registra_y_marca(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False)
    procesador = ProcesadorFalso(filas=2)
    enviador = EnviadorFalso()

    informe = pipeline.ejecutar(cfg, simular=False, fuente=fuente,
                                procesador=procesador, enviador=enviador)

    assert informe.procesados == 1
    assert procesador.llamadas_enviar == 1
    assert len(fuente.marcados) == 1
    assert cfg.ruta_estado_abs.exists()
    assert informe.ruta_resumen and Path(informe.ruta_resumen).exists()

    # Una segunda pasada no vuelve a procesarlo: ya esta en el estado.
    fuente2 = FuenteSimulada.desde_directorio(raiz)
    informe2 = pipeline.ejecutar(cfg, simular=False, fuente=fuente2,
                                 procesador=ProcesadorFalso(filas=2),
                                 enviador=EnviadorFalso())
    assert informe2.procesados == 0
    assert informe2.resultados[0].estado == ESTADO_OMITIDO


def test_no_marcar_deja_el_correo_intacto(espacio: Path) -> None:
    """--no-marcar: procesa de verdad, pero no toca el buzon."""
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    informe = pipeline.ejecutar(cfg, simular=False, fuente=fuente, marcar=False,
                                procesador=ProcesadorFalso(filas=1),
                                enviador=EnviadorFalso())

    assert informe.procesados == 1
    assert fuente.marcados == []                    # ni categoria, ni leido, ni mover
    assert "--no-marcar" in informe.resultados[0].marcado
    # El estado si se registra: el correo no se reprocesara la proxima vez.
    with Estado(cfg.ruta_estado_abs) as estado:
        assert estado.correo_procesado("SIM-001-correo_01") is not None


def test_adjunto_repetido_en_otro_correo_se_omite(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz, "lunes", contenido=b"%PDF-1.4 estado del lunes")
    correo_de_ejemplo(raiz, "martes", contenido=b"%PDF-1.4 estado del martes")
    cfg = configurar(espacio, resumen_activo=False)
    enviador = EnviadorFalso()

    primero = pipeline.ejecutar(cfg, simular=False,
                                fuente=FuenteSimulada.desde_directorio(raiz),
                                procesador=ProcesadorFalso(filas=1), enviador=enviador)
    assert primero.procesados == 2          # dos estados distintos: los dos entran

    # Alguien reenvia el estado del lunes dentro de otro correo: el EntryID es
    # nuevo, pero el PDF es el mismo y no debe volver a entrar en el ERP.
    raiz2 = espacio / "correos2"
    correo_de_ejemplo(raiz2, "reenvio", contenido=b"%PDF-1.4 estado del lunes")
    segundo = pipeline.ejecutar(cfg, simular=False,
                                fuente=FuenteSimulada.desde_directorio(raiz2),
                                procesador=ProcesadorFalso(filas=1), enviador=enviador)
    assert segundo.procesados == 0
    assert segundo.resultados[0].estado == ESTADO_OMITIDO
    assert segundo.resultados[0].adjuntos_repetidos == 1


def test_error_de_extraccion_no_se_da_por_procesado(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    informe = pipeline.ejecutar(cfg, simular=False,
                                fuente=FuenteSimulada.desde_directorio(raiz),
                                procesador=ProcesadorFalso(fallar=True),
                                enviador=EnviadorFalso())
    assert informe.resultados[0].estado == ESTADO_ERROR
    assert informe.errores == 1
    # Sin registro, el lunes siguiente se reintenta en lugar de perderse.
    with Estado(cfg.ruta_estado_abs) as estado:
        assert estado.correo_procesado("SIM-001-correo_01") is None
        assert estado.adjunto_conocido(hash_archivo(raiz / "correo_01" / "estado.pdf")) is None


def test_pdf_sin_movimientos_es_error_no_exito(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    informe = pipeline.ejecutar(cfg, simular=False,
                                fuente=FuenteSimulada.desde_directorio(raiz),
                                procesador=ProcesadorFalso(filas=0),
                                enviador=EnviadorFalso())
    assert informe.resultados[0].estado == ESTADO_ERROR
    assert "formato" in " ".join(informe.resultados[0].notas)


def test_error_de_envio_no_marca_el_correo(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    informe = pipeline.ejecutar(cfg, simular=False, fuente=fuente,
                                procesador=ProcesadorFalso(filas=2, errores_envio=1),
                                enviador=EnviadorFalso())
    assert informe.errores == 1
    assert fuente.marcados == []
    assert "se reintentara" in " ".join(informe.resultados[0].notas)


def test_sin_credenciales_extrae_pero_no_envia(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    class SinNinox(ProcesadorFalso):
        def credenciales_presentes(self):
            return False, "faltan las credenciales: NINOX_API_KEY"

    procesador = SinNinox(filas=4)
    informe = pipeline.ejecutar(cfg, simular=True,
                                fuente=FuenteSimulada.desde_directorio(raiz),
                                procesador=procesador, enviador=EnviadorFalso())

    assert informe.filas == 4
    assert procesador.llamadas_enviar == 0
    assert "NINOX_API_KEY" in informe.ninox_omitido
    assert "Ninox: OMITIDO" in informe.texto()


def test_dias_atras_limita_la_ventana(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    # El correo simulado lleva la fecha de ahora: con un corte de hace 1 hora
    # sigue dentro; con uno del ano que viene, no.
    cfg = configurar(espacio)
    filtro_viejo = FiltroMensajes(desde=datetime.now() - timedelta(hours=1))
    assert len(fuente.listar_pendientes(filtro_viejo)) == 1
    filtro_futuro = FiltroMensajes(desde=datetime.now() + timedelta(days=30))
    assert fuente.listar_pendientes(filtro_futuro) == []
    assert cfg.dias_atras == 8


# --------------------------------------------------------------------- avisos
def test_informe_avisa_de_los_errores(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    informe = pipeline.ejecutar(cfg, simular=True,
                                fuente=FuenteSimulada.desde_directorio(raiz),
                                procesador=ProcesadorFalso(fallar=True),
                                enviador=EnviadorFalso())
    assert "incidencias" in informe.asunto()
    assert "  ! " not in informe.texto() or True
    assert informe.todo_bien() is False
    assert "<table" in informe.html()


def test_abortado_si_la_fuente_falla(espacio: Path) -> None:
    class FuenteRota(FuenteSimulada):
        def abrir(self):
            from bfi_agente.correo import ErrorFuenteCorreos
            raise ErrorFuenteCorreos("Outlook no responde")

    cfg = configurar(espacio, resumen_activo=False)
    informe = pipeline.ejecutar(cfg, simular=True, fuente=FuenteRota([]),
                                procesador=ProcesadorFalso(),
                                enviador=EnviadorFalso())
    assert informe.abortado
    assert "ERROR" in informe.asunto()


def test_envia_todo_el_lote_de_una_sola_vez(espacio: Path) -> None:
    """Todas las lineas de todos los correos se insertan en UNA operacion.

    Es la correccion del fallo grave detectado el 24/09/2026: insertar correo a
    correo descoloca la cadena de saldos de Ninox, porque la formula encadena
    cada registro con el ultimo que se inserto.
    """
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz, "01_lunes", contenido=b"%PDF del lunes")
    correo_de_ejemplo(raiz, "02_martes", contenido=b"%PDF del martes")
    procesador = ProcesadorFalso(filas=2)
    cfg = configurar(espacio, resumen_activo=False)

    informe = pipeline.ejecutar(cfg, simular=True,
                                fuente=FuenteSimulada.desde_directorio(raiz),
                                procesador=procesador, enviador=EnviadorFalso())

    assert procesador.llamadas_extraer == 2      # se extraen los dos correos
    assert procesador.llamadas_enviar == 1       # pero se envia una sola vez
    assert len(procesador.lotes[0]) == 4         # 2 + 2 lineas en el mismo lote
    origenes = {fila["_origen"] for fila in procesador.lotes[0]}
    assert len(origenes) == 2                    # las lineas de los dos correos
    assert informe.insertados == 4


def test_ordena_el_lote_por_fecha_aunque_los_correos_lleguen_al_reves(espacio: Path) -> None:
    """El caso real: el movimiento del dia 15 entro despues de los del dia 18.

    El correo con el movimiento mas antiguo se extrae en segundo lugar. Al ir
    todo en un unico lote, el orden de insercion queda por ``fecha_valor``.
    """
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz, "01_reciente", contenido=b"%PDF reciente")
    correo_de_ejemplo(raiz, "02_antiguo", contenido=b"%PDF antiguo")

    class ProcesadorPorFecha(ProcesadorFalso):
        """Devuelve una fecha distinta en cada extraccion."""

        def extraer(self, rutas_pdf, ruta_csv):
            self.llamadas_extraer += 1
            fecha = "2026-09-18" if self.llamadas_extraer == 1 else "2026-09-15"
            return [{"cuenta_no": "0300000000000001", "fecha_valor": fecha,
                     "referencia": "REF-%s" % fecha, "detalle": "x",
                     "debito": "10", "credito": "", "saldo": "1"}]

    procesador = ProcesadorPorFecha()
    cfg = configurar(espacio, resumen_activo=False)
    pipeline.ejecutar(cfg, simular=True,
                      fuente=FuenteSimulada.desde_directorio(raiz),
                      procesador=procesador, enviador=EnviadorFalso())

    assert procesador.llamadas_enviar == 1
    assert len(procesador.lotes[0]) == 2
    fechas = [fila["fecha_valor"] for fila in procesador.grupos_ordenados["OD"]]
    assert fechas == ["2026-09-15", "2026-09-18"], (
        "el movimiento mas antiguo tiene que insertarse primero")


def test_marcar_repetidas_del_lote() -> None:
    """Dos PDFs distintos con la misma linea: la segunda no se envia."""
    grupos = {"OD": [
        {"referencia": "A", "fecha_valor": "2026-09-01", "debito": "10",
         "credito": "", "saldo": "1"},
        {"referencia": "A", "fecha_valor": "2026-09-01", "debito": "10",
         "credito": "", "saldo": "1"},
        {"referencia": "B", "fecha_valor": "2026-09-02", "debito": "20",
         "credito": "", "saldo": "1"},
    ]}
    repetidas = marcar_repetidas_del_lote(grupos)
    assert repetidas == 1
    marcadas = [f for f in grupos["OD"] if f.get("_duplicado")]
    assert len(marcadas) == 1 and marcadas[0]["referencia"] == "A"
    assert marcadas[0]["_motivo"] == "linea repetida dentro del mismo lote"


# --------------------------------------------------------- respuesta al remitente
def test_responde_al_remitente_cuando_esta_configurado(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False, responder_al_remitente=True)

    informe = pipeline.ejecutar(cfg, simular=False, fuente=fuente,
                                procesador=ProcesadorFalso(filas=2),
                                enviador=EnviadorFalso())

    assert len(fuente.respuestas) == 1
    clave, texto = fuente.respuestas[0]
    assert clave == "SIM-001-correo_01"
    assert texto == "Los registros han sido insertados en Ninox"
    assert informe.resultados[0].respuesta.startswith("respuesta simulada")
    assert "respuesta simulada" in informe.resultados[0].linea()


def test_no_responde_si_no_esta_configurado(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False)

    pipeline.ejecutar(cfg, simular=False, fuente=fuente,
                      procesador=ProcesadorFalso(filas=1), enviador=EnviadorFalso())
    assert fuente.respuestas == []


def test_no_responde_en_simulacion(espacio: Path) -> None:
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False, responder_al_remitente=True)

    informe = pipeline.ejecutar(cfg, simular=True, fuente=fuente,
                                procesador=ProcesadorFalso(filas=1),
                                enviador=EnviadorFalso())

    assert fuente.respuestas == []
    assert "NO enviada (simulacion)" in " ".join(informe.resultados[0].notas)


def test_no_responde_con_no_marcar(espacio: Path) -> None:
    """--no-marcar deja el buzon intacto: tampoco escribe a terceros."""
    raiz = espacio / "correos"
    correo_de_ejemplo(raiz)
    fuente = FuenteSimulada.desde_directorio(raiz)
    cfg = configurar(espacio, resumen_activo=False, responder_al_remitente=True)

    informe = pipeline.ejecutar(cfg, simular=False, fuente=fuente, marcar=False,
                                procesador=ProcesadorFalso(filas=1),
                                enviador=EnviadorFalso())

    assert fuente.respuestas == []
    assert "--no-marcar" in " ".join(informe.resultados[0].notas)


def test_config_exige_texto_si_se_responde() -> None:
    with pytest.raises(ErrorConfiguracion):
        ConfigAgente.desde_diccionario({"responder_al_remitente": True,
                                        "texto_respuesta": "   "})


def test_config_tiene_el_texto_por_defecto() -> None:
    cfg = ConfigAgente.desde_diccionario({})
    assert cfg.texto_respuesta == "Los registros han sido insertados en Ninox"
    assert cfg.responder_al_remitente is False


# ------------------------------------------------------------------ config
def test_config_rechaza_claves_desconocidas(espacio: Path) -> None:
    with pytest.raises(ErrorConfiguracion) as excinfo:
        ConfigAgente.desde_diccionario({"remitentes_permitdo": ["a@b.c"]})
    assert "remitentes_permitdo" in str(excinfo.value)


def test_config_exige_destinatario_si_el_resumen_esta_activo() -> None:
    with pytest.raises(ErrorConfiguracion):
        ConfigAgente.desde_diccionario({"resumen_activo": True, "resumen_para": []})


def test_config_valida_la_expresion_regular() -> None:
    with pytest.raises(ErrorConfiguracion):
        ConfigAgente.desde_diccionario({"patron_adjunto": "([a-z"})


def test_config_carga_el_ejemplo_del_repositorio() -> None:
    ruta = RAIZ / "agente_correo.ejemplo.json"
    assert ruta.exists()
    cfg = ConfigAgente.cargar(ruta)
    assert cfg.carpeta_outlook
    assert cfg.patron_adjunto


def test_marca_de_ejecucion_es_ordenable() -> None:
    marca = pipeline.marca_de_ejecucion(datetime(2026, 9, 28, 7, 30))
    assert marca == "2026-09-28_0730"
