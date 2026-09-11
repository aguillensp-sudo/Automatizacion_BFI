"""Cliente REST de Ninox, minimo y autocontenido.

Solo depende de la biblioteca estandar (``urllib``), igual que el proyecto
hermano ``Automatizacion JI``: menos dependencias = un ``.exe`` mas pequeno y
menos cosas que puedan fallar en el portatil del usuario final.

Toda la logica de red vive aqui. Las reglas de negocio (que campo recibe que
columna del CSV) viven en ``bfi/mapping.py``.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .config import (
    MAX_RETRIES,
    NINOX_BASE_URL,
    PAGE_SIZE,
    REQUEST_TIMEOUT_SEC,
    RETRY_BACKOFF_SEC,
)
from .credentials import load_credentials


class NinoxError(Exception):
    """Error base del cliente Ninox."""


class NinoxAuthError(NinoxError):
    """Credenciales invalidas (401/403)."""


class NinoxNotFoundError(NinoxError):
    """Tabla o registro inexistente (404)."""


class NinoxServerError(NinoxError):
    """Error del servidor (5xx) o de red tras agotar los reintentos."""


def _decode(body: str) -> Any:
    text = (body or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return body


class NinoxClient:
    """Cliente ligero sobre la API REST de Ninox.

    Lee y escribe. El endpoint de registros **no filtra en servidor**, asi que
    para comparar hay que descargar la tabla y filtrar en cliente; por eso
    ``fetch_all_records`` cachea el resultado por tabla dentro de la instancia.
    """

    def __init__(self, api_key: Optional[str] = None, team_id: Optional[str] = None,
                 db_id: Optional[str] = None, logger=None) -> None:
        if api_key and team_id and db_id:
            self._api_key, self._team_id, self._db_id = api_key, team_id, db_id
        else:
            creds = load_credentials()
            self._api_key = creds["NINOX_API_KEY"]
            self._team_id = creds["NINOX_TEAM_ID"]
            self._db_id = creds["NINOX_DB_ID"]
        self._log = logger
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._meta_cache: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ HTTP
    def _url(self, suffix: str = "") -> str:
        return "%s/teams/%s/databases/%s%s" % (
            NINOX_BASE_URL, self._team_id, self._db_id, suffix)

    def _info(self, msg: str, *a) -> None:
        if self._log:
            self._log.info(msg, *a)

    def _warn(self, msg: str, *a) -> None:
        if self._log:
            self._log.warning(msg, *a)

    def request_raw(self, method: str, path: str, payload: Any = None,
                    retry_5xx: bool = True) -> Tuple[int, Any]:
        """Peticion que **no** lanza por codigo de estado: devuelve (status, cuerpo).

        Existe para poder ver la respuesta exacta de la API (incluidos los 4xx)
        en lugar de convertirla en excepcion. Con ``retry_5xx=False`` devuelve el
        5xx tal cual, que es lo que se quiere al explorar un caso limite: Ninox
        responde **500** ante un nombre de campo mal escrito, y con reintentos la
        prueba abortaria en vez de registrar el hallazgo.
        """
        url = self._url(path)
        data = None
        headers = {"Authorization": "Bearer %s" % self._api_key,
                   "Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                req = urllib.request.Request(url, data=data, headers=headers,
                                             method=method)
                with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SEC) as resp:
                    body = resp.read().decode("utf-8", "replace")
                    return resp.status, _decode(body)
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", "replace")
                if exc.code < 500 and exc.code != 429:
                    return exc.code, _decode(body)
                if not retry_5xx:
                    return exc.code, _decode(body)
                last_exc = exc
                self._warn("HTTP %d en %s %s (reintentable)", exc.code, method, path)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_exc = exc
                self._warn("Error de red en %s %s: %r", method, path, exc)
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_BACKOFF_SEC * (2 ** (attempt - 1)))
        raise NinoxServerError(
            "Fallo tras %d intentos en %s %s: %r" % (MAX_RETRIES, method, path, last_exc))

    def request(self, path: str) -> Any:
        """GET con reintentos que si lanza ante error."""
        status, body = self.request_raw("GET", path)
        if status in (401, 403):
            raise NinoxAuthError(
                "Ninox rechazo las credenciales (HTTP %d). Revisa NINOX_API_KEY." % status)
        if status == 404:
            raise NinoxNotFoundError("Recurso no encontrado: %s" % path)
        if status >= 400:
            raise NinoxError("HTTP %d en %s: %s" % (status, path, body))
        return body

    # -------------------------------------------------------------- Lectura
    def list_tables(self) -> List[Dict[str, Any]]:
        return self.request("/tables")

    def get_table(self, table_id: str) -> Dict[str, Any]:
        """Metadatos de una tabla (id, nombre y lista de campos con tipo)."""
        if table_id not in self._meta_cache:
            self._meta_cache[table_id] = self.request("/tables/%s" % table_id)
        return self._meta_cache[table_id]

    def field_names(self, table_id: str) -> Dict[str, str]:
        """{id de campo: nombre} de la tabla. Base de la validacion del mapeo."""
        return {f["id"]: f["name"] for f in self.get_table(table_id).get("fields", [])}

    def fetch_all_records(self, table_id: str, use_cache: bool = True) -> List[Dict[str, Any]]:
        """Descarga TODOS los registros de una tabla, paginando hasta agotar."""
        if use_cache and table_id in self._cache:
            return self._cache[table_id]
        records: List[Dict[str, Any]] = []
        page = 0
        while True:
            chunk = self.request(
                "/tables/%s/records?perPage=%d&page=%d" % (table_id, PAGE_SIZE, page))
            if not isinstance(chunk, list):
                break
            records.extend(chunk)
            if len(chunk) < PAGE_SIZE:
                break
            page += 1
            if page > 5000:      # red de seguridad
                break
        if use_cache:
            self._cache[table_id] = records
        self._info("Tabla %s: %d registros", table_id, len(records))
        return records

    # ------------------------------------------------------------- Escritura
    def create_record(self, table_id: str, payload: Dict[str, Any]) -> Tuple[int, Any]:
        """POST de un registro. ``payload`` va tal cual: ``{"fields": {...}}``."""
        return self.request_raw("POST", "/tables/%s/records" % table_id, payload)

    def update_record(self, table_id: str, record_id: int,
                      payload: Dict[str, Any]) -> Tuple[int, Any]:
        """PUT de un registro. Hace *merge*: basta enviar lo que cambia."""
        return self.request_raw(
            "PUT", "/tables/%s/records/%s" % (table_id, record_id), payload)

    def delete_record(self, table_id: str, record_id: int) -> Tuple[int, Any]:
        return self.request_raw("DELETE", "/tables/%s/records/%s" % (table_id, record_id))

    def get_record(self, table_id: str, record_id: int) -> Optional[Dict[str, Any]]:
        """Lee un registro suelto (evita paginar la tabla entera)."""
        status, body = self.request_raw("GET", "/tables/%s/records/%s" % (table_id, record_id))
        if status == 200 and isinstance(body, dict):
            return body
        return None

    def invalidate_cache(self, table_id: Optional[str] = None) -> None:
        if table_id is None:
            self._cache.clear()
        else:
            self._cache.pop(table_id, None)
