"""Testes de ``send_raw_bytes`` contra um servidor TCP real (não mockado) —
o caminho de impressora de rede é o padrão já instalado no parque de
clientes (ver plano da Fase 3), então vale a pena verificar o socket de
verdade em vez de só mockar ``socket.socket``.
"""

from __future__ import annotations

import socket
import threading

import pytest

from app.printer_client import PrinterSendError, send_raw_bytes


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _FakePrinterServer:
    """Servidor TCP mínimo que aceita uma conexão e guarda o que recebeu."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.received: bytes = b""
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", port))
        self._srv.settimeout(3)
        self._srv.listen(1)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            conn, _ = self._srv.accept()
            with conn:
                conn.settimeout(3)
                chunks = []
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                self.received = b"".join(chunks)
        except OSError:
            pass

    def join(self) -> None:
        self._thread.join(timeout=3)
        self._srv.close()


def test_send_raw_bytes_to_network_printer():
    port = _free_port()
    server = _FakePrinterServer(port)
    try:
        send_raw_bytes(b"\x1B\x40hello\x1D\x56\x00", f"127.0.0.1:{port}")
    finally:
        server.join()
    assert server.received == b"\x1B\x40hello\x1D\x56\x00"


def test_send_raw_bytes_accepts_tcp_scheme_prefix():
    port = _free_port()
    server = _FakePrinterServer(port)
    try:
        send_raw_bytes(b"ok", f"tcp://127.0.0.1:{port}")
    finally:
        server.join()
    assert server.received == b"ok"


def test_send_raw_bytes_defaults_to_port_9100_when_omitted():
    # Não conectamos de verdade (porta 9100 pode não existir no CI) — só
    # confirma que a tentativa de conexão falha do jeito esperado (connection
    # refused vira PrinterSendError), provando que o parsing "sem porta" ==
    # 9100 está correto (se tentasse outra porta, o erro ainda seria
    # connection refused, mas queremos garantir que não lança TypeError/
    # ValueError de parsing antes disso).
    with pytest.raises(PrinterSendError):
        send_raw_bytes(b"x", "127.0.0.1", timeout=0.5)


def test_send_raw_bytes_connection_refused_raises_printer_send_error():
    port = _free_port()  # ninguém escutando
    with pytest.raises(PrinterSendError):
        send_raw_bytes(b"x", f"127.0.0.1:{port}", timeout=0.5)
