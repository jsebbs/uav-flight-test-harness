"""Transports between the test harness and the simulator.

The same test suite runs against every transport, so a test proves the
behaviour of the vehicle, not of one particular wiring.
"""

from __future__ import annotations

import socket
import socketserver
import threading
from collections import deque
from typing import Protocol

from .endpoint import SimEndpoint


class Transport(Protocol):
    def write(self, data: bytes) -> None: ...
    def read(self, timeout_s: float) -> bytes: ...
    def close(self) -> None: ...


class LoopbackTransport:
    """In-process transport. Fast; good for the bulk of the suite."""

    def __init__(self, endpoint: SimEndpoint) -> None:
        self._session = endpoint.new_session()
        self._rx: deque[bytes] = deque()

    def write(self, data: bytes) -> None:
        reply = self._session.receive(data)
        if reply:
            self._rx.append(reply)

    def read(self, timeout_s: float) -> bytes:
        return self._rx.popleft() if self._rx else b""

    def close(self) -> None:
        self._rx.clear()


class TcpTransport:
    """Real socket transport — exercises the process/network boundary."""

    def __init__(self, host: str, port: int, connect_timeout_s: float = 2.0) -> None:
        self._sock = socket.create_connection((host, port), timeout=connect_timeout_s)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    def write(self, data: bytes) -> None:
        self._sock.sendall(data)

    def read(self, timeout_s: float) -> bytes:
        self._sock.settimeout(timeout_s)
        try:
            return self._sock.recv(4096)
        except TimeoutError:
            return b""

    def close(self) -> None:
        self._sock.close()


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        session = self.server.endpoint.new_session()  # type: ignore[attr-defined]
        while True:
            try:
                data = self.request.recv(4096)
            except OSError:
                return
            if not data:
                return
            reply = session.receive(data)
            if reply:
                self.request.sendall(reply)


class SimTcpServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, endpoint: SimEndpoint, host: str = "127.0.0.1", port: int = 0) -> None:
        super().__init__((host, port), _Handler)
        self.endpoint = endpoint
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        host, port = self.server_address[:2]
        return str(host), int(port)

    def start(self) -> SimTcpServer:
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()
        if self._thread:
            self._thread.join(timeout=2)
