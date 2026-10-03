"""Unit tier: no network (sockets may only reach loopback or unix addresses), no docker, no GitHub."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from typing import Any

import pytest

_LOOPBACK_NAMES = {"localhost", "localhost.localdomain"}


def _is_local(sock: socket.socket, address: Any) -> bool:
    """True for unix sockets and loopback destinations."""
    if sock.family == getattr(socket, "AF_UNIX", None):
        return True
    host = address[0] if isinstance(address, tuple) and address else address
    if not isinstance(host, str):
        return False
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@pytest.fixture(autouse=True)
def _no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail any socket connection to a non-loopback address."""
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def connect(self: socket.socket, address: Any) -> None:
        """socket.connect limited to local destinations."""
        if not _is_local(self, address):
            raise RuntimeError(f"network access is not allowed in unit tests: {address!r}")
        original_connect(self, address)

    def connect_ex(self: socket.socket, address: Any) -> int:
        """socket.connect_ex limited to local destinations."""
        if not _is_local(self, address):
            raise RuntimeError(f"network access is not allowed in unit tests: {address!r}")
        return original_connect_ex(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    monkeypatch.setattr(socket.socket, "connect_ex", connect_ex)
    yield
