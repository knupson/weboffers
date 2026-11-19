"""Las esperas de reintento dentro de un paso (F-21) no se duermen de verdad en los tests.

19/11: los tests tampoco salen a internet. Un test que se olvide de simular HTTP podría mandar un WhatsApp (WAHA)
o un mensaje de Telegram reales; con esto falla con TEST_SIN_RED. Se permiten 127.0.0.1/localhost y sockets Unix.
"""
import ipaddress
import os
import socket

import pytest

os.environ.setdefault("TEST_MODE", "1")
_connect_real = socket.socket.connect


def _solo_local(self, address):
    if not isinstance(address, tuple):  # socket Unix
        return _connect_real(self, address)
    host = address[0]
    try:
        local = host == "localhost" or ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = False
    if local:
        return _connect_real(self, address)
    raise OSError(f"TEST_SIN_RED: un test intentó conectarse a {host}:{address[1]}")


@pytest.fixture(autouse=True)
def sin_red(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _solo_local)


@pytest.fixture(autouse=True)
def sin_esperas_de_reintento(monkeypatch):
    import ml_prices
    monkeypatch.setattr(ml_prices, "RETRY_WAIT_SECONDS", 0.0)
