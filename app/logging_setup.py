"""Log do agente — console **e** arquivo.

O arquivo deixou de ser opcional quando o agente virou aplicação de bandeja
(2026-08-17): build ``windowed`` no Windows não tem console nenhum, então sem
isto qualquer diagnóstico vira adivinhação. Há um precedente concreto — o
".exe não abre nada" registrado em SESSAO-PDV-WEB-2026-08-07.md §21 ficou sem
causa raiz justamente por não haver onde ler o que aconteceu.

O arquivo fica **ao lado do ``config.json``**, usando o mesmo
``_default_config_dir()`` já corrigido para o caso empacotado — pedir para o
lojista "mandar o log" só funciona se o log estiver onde ele já sabe procurar.

Rotação por tamanho: o agente roda meses seguidos numa máquina de loja, e um
log infinito acaba enchendo o disco de quem nunca vai olhar para ele.
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import log_path

_FORMATO = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_TAMANHO_MAXIMO_BYTES = 1_000_000
_ARQUIVOS_MANTIDOS = 3


def setup_logging(nivel: int = logging.INFO) -> Path | None:
    """Configura o log raiz para escrever no console e no arquivo.

    Returns:
        O caminho do arquivo de log, ou ``None`` se não foi possível escrever
        (pasta somente-leitura, permissão negada). Nesse caso o console segue
        funcionando — perder o arquivo nunca pode impedir o agente de subir.
    """
    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    formatador = logging.Formatter(_FORMATO)

    # Console: existe no build de terminal e no `python main.py`. No build
    # windowed, `sys.stderr` pode ser None — daí o guard.
    if sys.stderr is not None:
        console = logging.StreamHandler()
        console.setFormatter(formatador)
        raiz.addHandler(console)

    caminho = log_path()
    try:
        caminho.parent.mkdir(parents=True, exist_ok=True)
        arquivo = RotatingFileHandler(
            caminho, maxBytes=_TAMANHO_MAXIMO_BYTES, backupCount=_ARQUIVOS_MANTIDOS, encoding="utf-8",
        )
        arquivo.setFormatter(formatador)
        raiz.addHandler(arquivo)
        return caminho
    except OSError as exc:
        logging.getLogger(__name__).warning("Sem arquivo de log (%s): %s", caminho, exc)
        return None
