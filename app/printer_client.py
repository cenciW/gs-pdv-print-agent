"""Envio de bytes crus à impressora — portado de ``_send_raw_bytes`` no GS-PDV
desktop. Suporta impressora de rede (``ip[:porta]``, porta 9100 se omitida —
o padrão já instalado no parque de clientes), Windows (``win32print``) e
Linux/CUPS (``lp -o raw``). Quem chama trata a exceção.
"""

from __future__ import annotations

import logging
import os
import re
import socket
import subprocess
import sys
import tempfile
import time

logger = logging.getLogger(__name__)

_NETWORK_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}(:\d+)?$")


class PrinterSendError(Exception):
    """Falha ao enviar bytes à impressora — mensagem já pronta pro operador."""


def _is_network_dest(printer_dest: str) -> bool:
    addr = printer_dest.replace("tcp://", "")
    return "tcp://" in printer_dest or bool(_NETWORK_RE.match(addr))


def _parse_network_dest(printer_dest: str) -> tuple[str, int]:
    """``"192.168.1.50:9100"`` → ``("192.168.1.50", 9100)``. Porta 9100 é o padrão.

    Extraído de dentro de ``send_raw_bytes`` para o teste de conexão poder
    alcançar exatamente o mesmo endereço que a impressão alcançaria — um teste
    que resolve o endereço de outro jeito pode passar e a impressão falhar.
    """
    addr = printer_dest.replace("tcp://", "")
    if ":" in addr:
        host, porta = addr.rsplit(":", 1)
        return host, int(porta)
    return addr, 9100


def test_connection(printer_dest: str, timeout: float = 3.0) -> float:
    """Abre e fecha uma conexão TCP com a impressora. Devolve o tempo em ms.

    **Não envia byte nenhum** — de propósito. Testar se o computador enxerga a
    impressora não pode gastar papel, e o operador precisa poder conferir a rede
    quantas vezes quiser enquanto acerta o IP.

    Separar isto do teste de impressão é o ponto: "o computador não alcança a
    impressora" (IP errado, impressora desligada, firewall, outra faixa de rede)
    e "alcança mas não imprimiu" (papel, largura, ESC/POS) são problemas com
    soluções diferentes, e hoje os dois davam a mesma mensagem genérica.

    Raises:
        PrinterSendError: Mensagem já pronta para a tela, dizendo o que fazer.
    """
    if not _is_network_dest(printer_dest):
        raise PrinterSendError(
            "Este teste é só para impressora de rede. Para impressora instalada "
            "no computador, use 'Testar impressão'.",
        )

    host, porta = _parse_network_dest(printer_dest)
    inicio = time.monotonic()
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect((host, porta))
    except socket.timeout as exc:
        raise PrinterSendError(
            f"A impressora {host}:{porta} não respondeu em {timeout:g}s. "
            "Verifique se ela está ligada e na mesma rede deste computador.",
        ) from exc
    except ConnectionRefusedError as exc:
        raise PrinterSendError(
            f"O computador alcança {host}, mas a porta {porta} está fechada. "
            "Confira se esse é o IP da impressora e se a porta está certa "
            "(a maioria usa 9100).",
        ) from exc
    except OSError as exc:
        raise PrinterSendError(
            f"Não foi possível alcançar {host}:{porta} — {exc}. "
            "Confira o IP e se este computador está na mesma rede da impressora.",
        ) from exc
    finally:
        s.close()
    return (time.monotonic() - inicio) * 1000


def send_raw_bytes(raw_data: bytes, printer_dest: str, timeout: float = 5.0) -> None:
    """Envia ``raw_data`` (payload ESC/POS já pronto) para ``printer_dest``.

    Args:
        raw_data: Bytes ESC/POS (ver ``escpos.wrap_escpos``).
        printer_dest: ``"192.168.1.50"``, ``"192.168.1.50:9100"``,
            ``"tcp://192.168.1.50:9100"`` (impressora de rede) — ou, fora de
            Linux/Windows, um nome de impressora do sistema.
        timeout: Timeout do socket TCP, em segundos.

    Raises:
        PrinterSendError: Qualquer falha de conexão/escrita, com mensagem
            already amigável pro operador ver na tela.
    """
    try:
        if _is_network_dest(printer_dest):
            ip, port = _parse_network_dest(printer_dest)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.settimeout(timeout)
                s.connect((ip, port))
                s.sendall(raw_data)
            finally:
                s.close()
        elif sys.platform == "win32":
            import win32print  # type: ignore[import-not-found]

            hp = win32print.OpenPrinter(printer_dest)
            try:
                win32print.StartDocPrinter(hp, 1, ("Cupom", None, "RAW"))
                try:
                    win32print.StartPagePrinter(hp)
                    win32print.WritePrinter(hp, raw_data)
                    win32print.EndPagePrinter(hp)
                finally:
                    win32print.EndDocPrinter(hp)
            finally:
                win32print.ClosePrinter(hp)
        else:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".bin") as tf:
                tf.write(raw_data)
                tmp = tf.name
            try:
                subprocess.run(
                    ["lp", "-d", printer_dest, "-o", "raw", tmp],
                    check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                )
            finally:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
    except PrinterSendError:
        raise
    except Exception as exc:  # noqa: BLE001 — normaliza qualquer falha de I/O de impressão
        logger.warning("Falha ao enviar para a impressora %s: %s", printer_dest, exc)
        raise PrinterSendError(f"Não foi possível imprimir em '{printer_dest}': {exc}") from exc
