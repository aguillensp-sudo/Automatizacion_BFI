"""Cuentas que ven los tests.

``config`` carga el mapa real de ``cuentas.json`` si existe en la maquina de quien
ejecuta los tests. Los tests con fixtures sinteticas usan las cuentas ficticias y los
que leen PDF o CSV reales locales (ignorados por git) necesitan las reales, asi que
cada test ve la union de las dos: no dependen de si el fichero existe, y los que
solo conocen las ficticias siguen funcionando en una maquina sin datos reales.
"""
import pytest

from bfi import config


@pytest.fixture(autouse=True)
def cuentas_de_los_tests(monkeypatch):
    reales, etiquetas_reales, _ = config._cargar_cuentas()
    monkeypatch.setattr(config, "CUENTA_A_TABLA", {**reales, **config._CUENTAS_DEMO})
    monkeypatch.setattr(config, "TABLA_A_ETIQUETA", {**etiquetas_reales, **config._ETIQUETAS_DEMO})
