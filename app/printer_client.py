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

logger = logging.getLogger(__name__)

_NETWORK_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}(:\d+)?$")


class PrinterSendError(Exception):
    """Falha ao enviar bytes à impressora — mensagem já pronta pro operador."""


def _is_network_dest(printer_dest: str) -> bool:
    addr = printer_dest.replace("tcp://", "")
    return "tcp://" in printer_dest or bool(_NETWORK_RE.match(addr))


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
    addr_clean = printer_dest.replace("tcp://", "")

    try:
        if _is_network_dest(printer_dest):
            ip, port = addr_clean, 9100
            if ":" in addr_clean:
                ip, port_str = addr_clean.rsplit(":", 1)
                port = int(port_str)
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
