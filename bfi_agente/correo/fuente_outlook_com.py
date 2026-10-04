"""Fuente de correo sobre el Outlook **clasico** de este equipo, via COM.

Por que COM y no Microsoft Graph: la suscripcion de Microsoft es **personal**,
asi que no hay inquilino de Entra ID donde registrar una aplicacion, no hay
administrador que conceda permisos y las cuentas personales no admiten
consentimiento de administrador. Ademas, Microsoft desactivo la autenticacion
basica en las cuentas personales, de modo que IMAP/SMTP tampoco sirve. COM
sobre el Outlook de escritorio no necesita nada de eso: usa la sesion que ya
tiene el usuario.

Tres limitaciones que condicionan el diseno, y que conviene tener presentes:

1. **Necesita una sesion interactiva de Windows** con el perfil de Outlook
   cargado. Una tarea programada que corra como SYSTEM, o con "ejecutar tanto si
   el usuario inicio sesion como si no", **no puede** automatizar Outlook.
2. La "nueva" aplicacion de Outlook (la empaquetada de la Store) **no expone COM**.
   Hay que usar el Outlook clasico (``OUTLOOK.EXE``).
3. El ``EntryID`` **cambia** cuando un elemento se mueve de carpeta. Por eso el
   estado guarda tambien el ``InternetMessageID``, que es estable.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .fuente import ErrorFuenteCorreos, FuenteCorreos
from .modelo import Adjunto, FiltroMensajes, MensajeCorreo

OL_MAIL = 43
OL_FOLDER_INBOX = 6

# Etiquetas MAPI que no estan en el modelo de objetos de Outlook.
TAG_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptags/0x1035001E"
TAG_SMTP_ADDRESS = "http://schemas.microsoft.com/mapi/proptags/0x39FE001E"

CARACTERES_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
NOMBRES_RESERVADOS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{n}" for n in range(1, 10)),
    *(f"LPT{n}" for n in range(1, 10)),
}

ALIAS_BANDEJA = {"bandeja de entrada", "inbox", "entrada", "inbox - "}


def limpiar_nombre(nombre: str, limite: int = 150) -> str:
    """Nombre de fichero seguro para Windows, conservando la extension.

    El recorte se aplica al principio del nombre, no al final: al final esta la
    extension (``.pdf``), y perderla dejaria el adjunto sin poder abrirse.
    """
    base = Path(str(nombre or "").strip()).name
    base = CARACTERES_INVALIDOS.sub("_", base).strip(" .")
    if not base:
        base = "adjunto"
    raiz, punto, extension = base.rpartition(".")
    if punto and raiz.upper() in NOMBRES_RESERVADOS:
        raiz = raiz + "_"
    elif not punto and base.upper() in NOMBRES_RESERVADOS:
        raiz, punto, extension = base + "_", "", ""
    if punto:
        disponible = max(1, limite - len(extension) - 1)
        recortado = raiz[:disponible] + "." + extension
    else:
        recortado = base[:limite]
    return recortado or "adjunto"


def _a_datetime(valor: Any) -> Optional[datetime]:
    """Convierte una fecha de ``pywintypes`` a ``datetime`` de la biblioteca estandar."""
    if valor is None:
        return None
    if isinstance(valor, datetime):
        return datetime(valor.year, valor.month, valor.day,
                        valor.hour, valor.minute, valor.second)
    try:
        return datetime.fromisoformat(str(valor))
    except ValueError:
        return None


def _es_com_error(exc: BaseException) -> bool:
    return type(exc).__name__ in ("com_error", "com_error_") or hasattr(exc, "hresult")


class FuenteOutlookCom(FuenteCorreos):
    """Lee una carpeta del buzon abierto en el Outlook clasico."""

    nombre = "Outlook (COM)"

    def __init__(self, carpeta: str = "Bandeja de entrada/BFI",
                 carpeta_procesados: str = "", categoria: str = "",
                 max_correos: int = 0,
                 log: Optional[Callable[[str], None]] = None) -> None:
        self.ruta_carpeta = carpeta
        self.ruta_procesados = carpeta_procesados
        self.categoria = categoria
        self.max_correos = max_correos
        self.log = log or (lambda texto: None)
        self._pythoncom: Any = None
        self._app: Any = None
        self._ns: Any = None
        self._carpeta: Any = None
        # Los objetos COM se guardan por EntryID: sirve para no volver a buscar
        # el correo al descargar y, sobre todo, sobrevive al cambio de EntryID
        # que provoca mover el elemento a la carpeta de procesados.
        self._cache: Dict[str, Any] = {}
        self._abierta = False

    # ------------------------------------------------------------- apertura
    def abrir(self) -> None:
        if self._abierta:
            return
        try:
            import pythoncom                                  # noqa: PLC0415
            import win32com.client                            # noqa: PLC0415
        except ImportError as exc:                            # pragma: no cover
            raise ErrorFuenteCorreos(
                "Falta pywin32, que es lo que permite hablar con Outlook.\n"
                "Instalalo con:  pip install pywin32") from exc

        self._pythoncom = pythoncom
        pythoncom.CoInitialize()
        try:
            self._app = win32com.client.Dispatch("Outlook.Application")
            self._ns = self._app.GetNamespace("MAPI")
            try:
                self._ns.GetDefaultFolder(OL_FOLDER_INBOX)
            except Exception as exc:                      # noqa: BLE001
                raise ErrorFuenteCorreos(
                    "Outlook no tiene ningun perfil de correo abierto.\n"
                    "Abre Outlook, inicia sesion y deja el perfil configurado "
                    "antes de ejecutar el agente.\nDetalle: %s" % exc) from exc
            self._carpeta = self.resolver_carpeta(self.ruta_carpeta)
        except ErrorFuenteCorreos:
            self.cerrar()
            raise
        except Exception as exc:                          # noqa: BLE001
            self.cerrar()
            raise ErrorFuenteCorreos(
                "No se pudo abrir Outlook por COM: %s\n"
                "Comprueba que esta instalado el Outlook **clasico** "
                "(la aplicacion nueva de la Store no expone COM)." % exc) from exc

        self._abierta = True
        self.log("Outlook abierto. Carpeta vigilada: %s" % self.ruta_carpeta)

    def cerrar(self) -> None:
        for atributo in ("_carpeta", "_ns", "_app"):
            if getattr(self, atributo, None) is not None:
                try:
                    delattr(self, atributo)
                except Exception:                         # noqa: BLE001
                    pass
                setattr(self, atributo, None)
        self._cache.clear()
        if self._pythoncom is not None:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:                             # noqa: BLE001
                pass
            self._pythoncom = None
        self._abierta = False

    # ------------------------------------------------------------ carpetas
    def _raiz(self) -> Any:
        """Carpeta raiz del almacen por defecto (contiene "Bandeja de entrada")."""
        return self._ns.GetDefaultFolder(OL_FOLDER_INBOX).Parent

    def _hija(self, padre: Any, nombre: str) -> Any:
        """Subcarpeta por nombre, sin distinguir mayusculas."""
        try:
            return padre.Folders.Item(nombre)
        except Exception:                                 # noqa: BLE001
            pass
        buscado = nombre.strip().lower()
        for indice in range(1, int(padre.Folders.Count) + 1):
            hija = padre.Folders.Item(indice)
            if str(hija.Name).strip().lower() == buscado:
                return hija
        disponibles = [str(padre.Folders.Item(i).Name)
                       for i in range(1, int(padre.Folders.Count) + 1)]
        raise ErrorFuenteCorreos(
            "No existe la carpeta '%s' dentro de '%s'.\nCarpetas disponibles: %s"
            % (nombre, getattr(padre, "Name", "?"), ", ".join(disponibles) or "(ninguna)"))

    def resolver_carpeta(self, ruta: str) -> Any:
        """Carpeta de Outlook a partir de una ruta tipo ``Buzon/Subcarpeta``.

        Se admite el nombre visible del buzon como primer tramo y el alias
        "Bandeja de entrada" para la bandeja de entrada del almacen por defecto.
        """
        partes = [p.strip() for p in re.split(r"[\\/]", str(ruta or "")) if p.strip()]
        if not partes:
            return self._ns.GetDefaultFolder(OL_FOLDER_INBOX)
        try:
            inicio = self._ns.Folders.Item(partes[0])
            partes = partes[1:]
        except Exception:                                 # noqa: BLE001
            inicio = self._raiz()
        if partes and partes[0].strip().lower() in ALIAS_BANDEJA:
            inicio = self._hija(inicio, partes[0])
            partes = partes[1:]
        for nombre in partes:
            inicio = self._hija(inicio, nombre)
        return inicio

    def listar_carpetas(self, profundidad: int = 3) -> List[str]:
        """Rutas de las carpetas del almacen por defecto (diagnostico)."""
        self.abrir()
        salida: List[str] = []

        def recorrer(carpeta: Any, prefijo: str, nivel: int) -> None:
            total = int(carpeta.Folders.Count)
            for indice in range(1, total + 1):
                hija = carpeta.Folders.Item(indice)
                ruta = "%s/%s" % (prefijo, hija.Name) if prefijo else str(hija.Name)
                try:
                    cuenta = int(hija.Items.Count)
                except Exception:                         # noqa: BLE001
                    cuenta = -1
                salida.append("%s  (%d elemento(s))" % (ruta, cuenta))
                if nivel < profundidad:
                    recorrer(hija, ruta, nivel + 1)

        recorrer(self._raiz(), "", 1)
        return salida

    # -------------------------------------------------------------- correos
    def _direccion_smtp(self, item: Any) -> str:
        for intento in (lambda: item.PropertyAccessor.GetProperty(TAG_SMTP_ADDRESS),
                        lambda: item.SenderEmailAddress):
            try:
                valor = intento()
            except Exception:                             # noqa: BLE001
                continue
            if valor and "@" in str(valor):
                return str(valor)
        # Remitente interno de Exchange: se resuelve contra la libreta.
        try:
            remitente = item.Sender
            if remitente is not None:
                usuario = remitente.GetExchangeUser()
                if usuario is not None and usuario.PrimarySmtpAddress:
                    return str(usuario.PrimarySmtpAddress)
        except Exception:                                 # noqa: BLE001
            pass
        try:
            return str(item.SenderEmailAddress or "")
        except Exception:                                 # noqa: BLE001
            return ""

    def _internet_message_id(self, item: Any) -> str:
        try:
            return str(item.PropertyAccessor.GetProperty(TAG_INTERNET_MESSAGE_ID) or "")
        except Exception:                                 # noqa: BLE001
            return ""

    def _mensaje(self, item: Any) -> MensajeCorreo:
        adjuntos: List[Adjunto] = []
        try:
            total = int(item.Attachments.Count)
        except Exception:                                 # noqa: BLE001
            total = 0
        for indice in range(1, total + 1):
            try:
                adjunto = item.Attachments.Item(indice)
                adjuntos.append(Adjunto(nombre=str(adjunto.FileName),
                                        bytes_=int(adjunto.Size or 0)))
            except Exception:                             # noqa: BLE001
                continue
        mensaje = MensajeCorreo(
            entry_id=str(item.EntryID),
            asunto=str(item.Subject or ""),
            remitente=str(item.SenderName or ""),
            direccion=self._direccion_smtp(item),
            recibido=_a_datetime(item.ReceivedTime),
            internet_message_id=self._internet_message_id(item),
            adjuntos=adjuntos,
        )
        self._cache[mensaje.entry_id] = item
        return mensaje

    def listar_pendientes(self, filtro: FiltroMensajes) -> List[MensajeCorreo]:
        self.abrir()
        items = self._carpeta.Items
        ordenado = True
        try:
            # Descendente por fecha: asi basta con parar al llegar al corte, sin
            # depender del formato de fecha del sistema (los filtros DASL de
            # Outlook son sensibles a la configuracion regional).
            items.Sort("[ReceivedTime]", True)
        except Exception as exc:                          # noqa: BLE001
            ordenado = False
            self.log("   aviso: no se pudo ordenar por fecha (%s); "
                     "se revisan todos los elementos de la carpeta." % exc)

        total = int(items.Count)
        pendientes: List[MensajeCorreo] = []
        for indice in range(1, total + 1):
            try:
                item = items.Item(indice)
            except Exception:                             # noqa: BLE001
                continue
            if int(getattr(item, "Class", 0)) != OL_MAIL:
                continue
            mensaje = self._mensaje(item)
            if not filtro.dentro_de_ventana(mensaje):
                # Los elementos vienen del mas nuevo al mas antiguo: el primero
                # que se queda fuera marca el final de la ventana.
                if ordenado:
                    break
                continue
            motivo = filtro.motivo_rechazo(mensaje)
            if motivo:
                self.log("   se ignora '%s' (%s): %s"
                         % (mensaje.asunto[:60] or "(sin asunto)",
                            mensaje.recibido_texto, motivo))
                continue
            pendientes.append(mensaje)
            if self.max_correos and len(pendientes) >= self.max_correos:
                self.log("   limite de max_correos (%d) alcanzado." % self.max_correos)
                break
        return pendientes

    # ------------------------------------------------------------- adjuntos
    def _item(self, mensaje: MensajeCorreo) -> Any:
        item = self._cache.get(mensaje.entry_id)
        if item is not None:
            return item
        try:
            item = self._ns.GetItemFromID(mensaje.entry_id)
        except Exception as exc:                          # noqa: BLE001
            raise ErrorFuenteCorreos(
                "El correo '%s' ya no esta en la carpeta (puede que lo hayan "
                "movido o borrado mientras corria el agente)." % mensaje.asunto) from exc
        self._cache[mensaje.entry_id] = item
        return item

    def descargar_adjuntos(self, mensaje: MensajeCorreo, destino: Path,
                           filtro: FiltroMensajes) -> List[Adjunto]:
        item = self._item(mensaje)
        destino.mkdir(parents=True, exist_ok=True)
        usados: set = set()
        descargados: List[Adjunto] = []
        total = int(item.Attachments.Count)
        for indice in range(1, total + 1):
            try:
                adjunto = item.Attachments.Item(indice)
                nombre = str(adjunto.FileName)
            except Exception:                             # noqa: BLE001
                continue
            if not filtro.adjunto_interesa(nombre):
                continue
            limpio = self._nombre_libre(nombre, usados)
            ruta = destino / limpio
            try:
                adjunto.SaveAsFile(str(ruta))
            except Exception as exc:                      # noqa: BLE001
                raise ErrorFuenteCorreos(
                    "No se pudo guardar el adjunto '%s' en %s: %s"
                    % (nombre, destino, exc)) from exc
            descargados.append(Adjunto(nombre=limpio, ruta=str(ruta),
                                       bytes_=ruta.stat().st_size))
        return descargados

    @staticmethod
    def _nombre_libre(nombre: str, usados: set) -> str:
        limpio = limpiar_nombre(nombre)
        if limpio not in usados:
            usados.add(limpio)
            return limpio
        raiz = Path(limpio)
        contador = 2
        while True:
            candidato = "%s_%d%s" % (raiz.stem, contador, raiz.suffix)
            if candidato not in usados:
                usados.add(candidato)
                return candidato
            contador += 1

    # ------------------------------------------------------------ marcado
    def marcar_procesado(self, mensaje: MensajeCorreo) -> str:
        item = self._item(mensaje)
        hecho: List[str] = []
        if self.categoria:
            try:
                item.Categories = self.categoria
                hecho.append("categoria '%s'" % self.categoria)
            except Exception as exc:                      # noqa: BLE001
                self.log("   aviso: no se pudo poner la categoria: %s" % exc)
        try:
            item.UnRead = False
        except Exception:                                 # noqa: BLE001
            pass
        try:
            item.Save()
        except Exception:                                 # noqa: BLE001
            pass
        if self.ruta_procesados:
            destino = self.resolver_carpeta(self.ruta_procesados)
            try:
                item.Move(destino)
                hecho.append("movido a '%s'" % self.ruta_procesados)
            except Exception as exc:                      # noqa: BLE001
                self.log("   aviso: no se pudo mover el correo: %s" % exc)
        return ", ".join(hecho) or "sin cambios"

    # ----------------------------------------------------------- respuesta
    def responder(self, mensaje: MensajeCorreo, texto: str) -> str:
        """Responde al remitente, en el mismo hilo del correo original.

        Se usa ``Reply`` y no ``ReplyAll``: el aviso es para quien envio el
        estado de cuenta, no para el resto de destinatarios.

        El texto propio se **antepone** al cuerpo citado que Outlook prepara
        solo, para no perder el contexto de la conversacion.
        """
        item = self._item(mensaje)
        try:
            respuesta = item.Reply()
        except Exception as exc:                          # noqa: BLE001
            raise ErrorFuenteCorreos(
                "No se pudo preparar la respuesta a '%s': %s"
                % (mensaje.asunto, exc)) from exc
        try:
            citado = ""
            try:
                citado = str(respuesta.Body or "")
            except Exception:                             # noqa: BLE001
                citado = ""
            respuesta.Body = (texto + "\n\n" + citado) if citado else texto
            destinatario = ""
            try:
                destinatario = str(respuesta.To or "")
            except Exception:                             # noqa: BLE001
                destinatario = mensaje.direccion
            respuesta.Send()
        except Exception as exc:                          # noqa: BLE001
            raise ErrorFuenteCorreos(
                "No se pudo enviar la respuesta a '%s': %s"
                % (mensaje.direccion or mensaje.remitente, exc)) from exc
        self.log("   respuesta enviada a %s" % (destinatario or mensaje.direccion))
        return "respuesta enviada a %s" % (destinatario or mensaje.direccion)


def outlook_disponible() -> tuple:
    """Comprueba si se puede hablar con Outlook. Devuelve ``(ok, mensaje)``."""
    try:
        import pythoncom                                      # noqa: PLC0415
        import win32com.client                                # noqa: PLC0415
    except ImportError:
        return False, "pywin32 no esta instalado (pip install pywin32)."
    try:
        pythoncom.CoInitialize()
        app = win32com.client.Dispatch("Outlook.Application")
        ns = app.GetNamespace("MAPI")
        carpeta = ns.GetDefaultFolder(OL_FOLDER_INBOX)
        nombre = str(carpeta.Name)
        perfil = ""
        try:
            perfil = str(ns.CurrentProfileName)
        except Exception:                                     # noqa: BLE001
            perfil = "(desconocido)"
        return True, "Outlook responde. Perfil: %s. Bandeja: %s" % (perfil, nombre)
    except Exception as exc:                                  # noqa: BLE001
        return False, "Outlook no responde por COM: %s" % exc
