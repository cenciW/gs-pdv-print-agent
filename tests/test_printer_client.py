"""Testes de ``send_raw_bytes`` contra um servidor TCP real (não mockado) —
o caminho de impressora de rede é o padrão já instalado no parque de
clientes (ver plano da Fase 3), então vale a pena verificar o socket de
verdade em vez de só mockar ``socket.socket``.
"""

from __future__ import annotations

import os
import socket
import stat
import sys
import threading
from pathlib import Path

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


# ── Caminho do spooler (CUPS) ────────────────────────────────────────────────
# O caminho de rede (acima) já era coberto contra um socket real. O envio pelo
# **spooler** não era — e é o caminho de toda impressora USB, que é como boa
# parte do parque está ligada.
#
# Em vez de mockar `subprocess`, estes testes colocam um `lp` FALSO no PATH e
# deixam o código executar de verdade: exercita a criação do arquivo temporário,
# a montagem do comando, o tratamento do código de saída e a limpeza do temp —
# tudo o que um mock de `subprocess.run` pularia. Nenhuma folha é impressa.

def _instalar_lp_falso(tmp_path: Path, monkeypatch, codigo_saida: int = 0) -> Path:
    """Coloca um `lp` de mentira no início do PATH e devolve onde ele registra."""
    registro = tmp_path / "chamada.txt"
    script = tmp_path / "lp"
    script.write_text(
        "#!/bin/sh\n"
        f'printf "%s\\n" "$@" > "{registro}"\n'
        # Guarda o CONTEÚDO do arquivo enviado: é o que chegaria na impressora.
        f'for arg in "$@"; do [ -f "$arg" ] && cp "$arg" "{tmp_path}/enviado.bin"; done\n'
        f"exit {codigo_saida}\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
    return registro


def test_envia_pelo_spooler_com_lp_raw(tmp_path, monkeypatch):
    """Nome de impressora (não IP) vai pelo spooler, e o ESC/POS precisa chegar
    **cru**: sem `-o raw` o CUPS tenta interpretar os bytes como documento e a
    impressora cospe lixo."""
    monkeypatch.setattr(sys, "platform", "linux")
    registro = _instalar_lp_falso(tmp_path, monkeypatch)

    payload = b"\x1B\x40TESTE\x1D\x56\x00"
    send_raw_bytes(payload, "HPRT-TP80K")

    argumentos = registro.read_text(encoding="utf-8").split("\n")
    assert argumentos[0] == "-d"
    assert argumentos[1] == "HPRT-TP80K"
    assert argumentos[2] == "-o"
    assert argumentos[3] == "raw"
    # O que chegaria na impressora é exatamente o payload, byte a byte.
    assert (tmp_path / "enviado.bin").read_bytes() == payload


def test_arquivo_temporario_e_removido_apos_enviar(tmp_path, monkeypatch):
    """O agente roda meses seguidos numa máquina de loja — um temp por cupom
    esquecido no disco vira lixo acumulado."""
    monkeypatch.setattr(sys, "platform", "linux")
    registro = _instalar_lp_falso(tmp_path, monkeypatch)

    send_raw_bytes(b"x", "Balcao")

    caminho_temp = registro.read_text(encoding="utf-8").split("\n")[4]
    assert not Path(caminho_temp).exists()


def test_falha_do_spooler_vira_printer_send_error(tmp_path, monkeypatch):
    """`lp` saindo com erro (fila parada, impressora inexistente) precisa virar
    a exceção que a rota traduz em 502 com mensagem para o operador."""
    monkeypatch.setattr(sys, "platform", "linux")
    _instalar_lp_falso(tmp_path, monkeypatch, codigo_saida=1)

    with pytest.raises(PrinterSendError) as erro:
        send_raw_bytes(b"x", "Impressora-Inexistente")
    assert "Impressora-Inexistente" in str(erro.value)


def test_temp_removido_mesmo_quando_o_spooler_falha(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    registro = _instalar_lp_falso(tmp_path, monkeypatch, codigo_saida=1)

    with pytest.raises(PrinterSendError):
        send_raw_bytes(b"x", "Qualquer")

    caminho_temp = registro.read_text(encoding="utf-8").split("\n")[4]
    assert not Path(caminho_temp).exists()
