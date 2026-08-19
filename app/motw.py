"""O aviso do Windows a cada início — "marca da web" no executável.

Arquivo baixado da internet chega com um fluxo alternativo de dados chamado
``Zone.Identifier`` grudado nele (a "Mark of the Web"). Enquanto ele existir, o
Windows pergunta se você confia no programa **toda vez** que ele abre — e num
computador de loja isso significa que o agente **não sobe sozinho de verdade**:
ele fica esperando alguém clicar, e o primeiro cupom do dia não sai.

Foi exatamente o relato: *"agora inicializou sozinho, mas ele pede uma permissão
para executar"*.

Desbloquear é o mesmo que o Windows faz em Propriedades → **Desbloquear**: apaga
esse fluxo. Não altera o programa nem desliga proteção nenhuma — só registra que
esta cópia já foi aceita por quem a instalou. O agente **oferece**, nunca faz
sozinho: mexer em metadado de segurança pelas costas de quem usa é pior que a
pergunta repetida.

> A causa de fundo é o executável não ser assinado digitalmente. Assinar tem
> custo anual e ficou para depois (decisão do usuário em 2026-08-19); enquanto
> isso, desbloquear resolve para a cópia instalada.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_FLUXO = ":Zone.Identifier"


def _executavel() -> Path | None:
    """O `.exe` empacotado, ou ``None`` quando não faz sentido falar em MOTW."""
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable)


def esta_bloqueado() -> bool:
    """Se o Windows vai pedir confirmação para abrir este executável."""
    exe = _executavel()
    if exe is None:
        return False
    try:
        with open(f"{exe}{_FLUXO}", "rb"):
            return True
    except OSError:
        # Inclui "não existe" (o caso comum: já desbloqueado) e sistema de
        # arquivos sem suporte a fluxo alternativo (pendrive em FAT32).
        return False


def desbloquear() -> bool:
    """Remove a marca. Devolve se, ao final, o arquivo está liberado."""
    exe = _executavel()
    if exe is None:
        return True
    try:
        os.remove(f"{exe}{_FLUXO}")
        logger.info("Marca da web removida de %s — o Windows para de pedir confirmação.", exe)
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        # Sem permissão de escrita na pasta (instalado em Arquivos de
        # Programas por outro usuário, por exemplo). Não é falha do agente.
        logger.warning("Não foi possível remover a marca da web: %s", exc)
        return False
