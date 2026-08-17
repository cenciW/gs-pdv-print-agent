"""Iniciar junto com o computador, sem o lojista abrir editor de texto.

Até 2026-08-17 isto era um passo manual descrito em ``docs/AUTOSTART.md``
(criar atalho na pasta Startup do Windows, ou escrever uma unit do systemd).
Passo manual em máquina de loja é passo que não acontece: a impressora "para de
funcionar" toda vez que o computador reinicia, e ninguém liga os pontos.

O guia continua valendo para quem quer systemd de verdade (serviço com
``Restart=on-failure``, roda sem usuário logado). O que está aqui é o caminho
simples: um atalho na sessão do usuário, ligado e desligado por um clique no
menu da bandeja.

Tudo aqui é **best-effort**: falhar em criar o atalho não pode impedir o agente
de rodar agora.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_NOME = "gs-pdv-print-agent"


def _executavel() -> tuple[str, list[str]]:
    """Como reinvocar este mesmo agente.

    Empacotado (``sys.frozen``), o próprio binário é o comando. Rodando via
    ``python main.py``, é o interpretador com o script — mesmo raciocínio já
    usado em ``_delayed_restart`` no ``main.py``.
    """
    if getattr(sys, "frozen", False):
        return sys.executable, []
    return sys.executable, [str(Path(sys.argv[0]).resolve())]


# ── Windows: atalho .cmd na pasta Startup ────────────────────────────────────
# Um .cmd em vez de um .lnk de propósito: atalho do Windows exige COM
# (pywin32/WScript.Shell) e falha de formas obscuras quando o caminho tem
# acento ou espaço. Um .cmd de duas linhas é inspecionável pelo próprio
# lojista, e o `start ""` faz o console fechar em vez de ficar aberto.

def _pasta_startup_windows() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _atalho_windows() -> Path:
    return _pasta_startup_windows() / f"{_NOME}.cmd"


def _instalar_windows() -> None:
    comando, argumentos = _executavel()
    linha = " ".join(f'"{parte}"' for parte in [comando, *argumentos])
    atalho = _atalho_windows()
    atalho.parent.mkdir(parents=True, exist_ok=True)
    atalho.write_text(f'@echo off\r\nstart "" {linha}\r\n', encoding="utf-8")


# ── Linux: .desktop em ~/.config/autostart ───────────────────────────────────

def _atalho_linux() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{_NOME}.desktop"


def _instalar_linux() -> None:
    comando, argumentos = _executavel()
    linha = " ".join([comando, *argumentos])
    atalho = _atalho_linux()
    atalho.parent.mkdir(parents=True, exist_ok=True)
    atalho.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=GS PDV Print Agent\n"
        "Comment=Ponte entre o PDV web e a impressora térmica da loja\n"
        f"Exec={linha}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


# ── API pública ──────────────────────────────────────────────────────────────

def caminho_do_atalho() -> Path:
    return _atalho_windows() if sys.platform == "win32" else _atalho_linux()


def esta_ativo() -> bool:
    """Se o agente já está configurado para subir com o computador."""
    try:
        return caminho_do_atalho().exists()
    except (OSError, KeyError) as exc:  # KeyError: APPDATA ausente
        logger.debug("Não foi possível checar o autostart: %s", exc)
        return False


def ativar() -> bool:
    """Cria o atalho de inicialização. Devolve se deu certo."""
    try:
        if sys.platform == "win32":
            _instalar_windows()
        else:
            _instalar_linux()
        logger.info("Autostart ativado: %s", caminho_do_atalho())
        return True
    except (OSError, KeyError) as exc:
        logger.warning("Não foi possível ativar o autostart: %s", exc)
        return False


def desativar() -> bool:
    """Remove o atalho. Devolve se deu certo (ausente já conta como sucesso)."""
    try:
        caminho_do_atalho().unlink(missing_ok=True)
        logger.info("Autostart desativado.")
        return True
    except (OSError, KeyError) as exc:
        logger.warning("Não foi possível desativar o autostart: %s", exc)
        return False
