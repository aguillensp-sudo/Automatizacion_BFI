"""Los tests usan siempre las cuentas ficticias de demostracion.

``config`` carga el mapa real de ``cuentas.json`` si existe en la maquina de quien
ejecuta los tests; sin este aislamiento, los resultados dependerian de ese fichero.
"""
import pytest

from bfi import config


@pytest.fixture(autouse=True)
def cuentas_de_demostracion(monkeypatch):
    monkeypatch.setattr(config, "CUENTA_A_TABLA", dict(config._CUENTAS_DEMO))
    monkeypatch.setattr(config, "TABLA_A_ETIQUETA", dict(config._ETIQUETAS_DEMO))
