"""Descoberta do endereço deste computador na rede da loja.

Serve para a janela **sugerir** endereços em vez de exigir que alguém saiba o
IP de cor. Não é usado em nenhuma decisão de segurança: quem autoriza uma
origem é a pessoa clicando, não este módulo.
"""

from __future__ import annotations

import logging
import socket

logger = logging.getLogger(__name__)


def ip_local() -> str:
    """IP deste computador na rede local, ou string vazia se não descobrir.

    Usa o truque do socket UDP "conectado": o sistema escolhe a interface que
    sairia para a internet e revela o IP dela, **sem enviar pacote nenhum** (UDP
    não faz handshake). É mais confiável que ``gethostbyname(gethostname())``,
    que em muitas máquinas devolve ``127.0.1.1`` e não ajuda em nada.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(0.5)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError as exc:  # máquina sem rota de saída, sem rede, etc.
        logger.debug("Não foi possível descobrir o IP local: %s", exc)
        return ""
    finally:
        s.close()
