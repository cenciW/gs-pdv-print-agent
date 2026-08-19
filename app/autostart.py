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


# ── Windows: chave Run do registro ───────────────────────────────────────────
# Até 2026-08-19 isto era um `.cmd` na pasta Startup, e o usuário reportou
# exatamente o que essa escolha permite: *"ele inicializa normal, mas não
# inicializa junto com o windows"*. Um arquivo na pasta Startup depende de o
# Explorer executá-lo, aparece como item desativável em
# Gerenciador de Tarefas > Inicializar, e pisca um console ao subir.
#
# A chave `Run` do registro é o mecanismo padrão do Windows: quem executa é o
# próprio logon, não o Explorer. O `.cmd` legado continua sendo REMOVIDO ao
# ligar/desligar, para ninguém acabar com o agente subindo duas vezes.

_CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Onde o Windows guarda "o usuário desativou este item de inicialização".
# Primeiro byte par = habilitado; ímpar (2, 3, 6…) = desativado pela pessoa em
# Gerenciador de Tarefas ou Configurações. Sem ler isto, o agente juraria estar
# configurado enquanto o Windows o ignora em silêncio — que é o sintoma.
_CHAVE_APROVACAO = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def _pasta_startup_windows() -> Path:
    return Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _atalho_windows() -> Path:
    """Atalho LEGADO. Mantido só para ser apagado — ver comentário acima."""
    return _pasta_startup_windows() / f"{_NOME}.cmd"


def _comando_windows() -> str:
    comando, argumentos = _executavel()
    return " ".join(f'"{parte}"' for parte in [comando, *argumentos])


def _valor_no_registro() -> str:
    """Comando registrado hoje, ou string vazia."""
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN) as chave:
            valor, _ = winreg.QueryValueEx(chave, _NOME)
            return str(valor)
    except (OSError, FileNotFoundError):
        return ""


def desativado_pelo_windows() -> bool:
    """Se a pessoa desativou este item em Gerenciador de Tarefas > Inicializar.

    Vale ouro no diagnóstico: neste estado o agente está corretamente
    registrado e o Windows simplesmente não o executa — sem isto, "a opção está
    marcada e não sobe" não tem explicação nenhuma na tela.
    """
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_APROVACAO) as chave:
            valor, _ = winreg.QueryValueEx(chave, _NOME)
            return bool(valor) and bool(valor[0] % 2)
    except (OSError, FileNotFoundError, IndexError, TypeError):
        return False


def _instalar_windows() -> None:
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN) as chave:
        winreg.SetValueEx(chave, _NOME, 0, winreg.REG_SZ, _comando_windows())
    # Se um .cmd antigo continuar na pasta Startup, o agente subiria duas vezes
    # e a segunda instância morreria com a porta ocupada — parecendo defeito.
    _atalho_windows().unlink(missing_ok=True)


def _desinstalar_windows() -> None:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as chave:
            winreg.DeleteValue(chave, _NOME)
    except (OSError, FileNotFoundError):
        pass
    _atalho_windows().unlink(missing_ok=True)


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
    """Onde a inicialização está registrada — mostrado na tela e no log.

    No Windows não é mais um arquivo, e sim a chave ``Run`` do registro; o
    caminho legado continua sendo devolvido para quem quiser conferir se
    sobrou algum ``.cmd`` de versão antiga.
    """
    return _atalho_windows() if sys.platform == "win32" else _atalho_linux()


def onde_esta_registrado() -> str:
    """Descrição legível de onde a inicialização vive, para a tela e o log."""
    if sys.platform == "win32":
        return f"HKEY_CURRENT_USER\\{_CHAVE_RUN}\\{_NOME}"
    return str(_atalho_linux())


def alvo_registrado() -> str:
    """Qual comando está registrado para subir no logon (vazio = nenhum)."""
    try:
        if sys.platform == "win32":
            return _valor_no_registro()
        atalho = _atalho_linux()
        if not atalho.exists():
            return ""
        for linha in atalho.read_text(encoding="utf-8").splitlines():
            if linha.startswith("Exec="):
                return linha[len("Exec="):].strip()
        return ""
    except (OSError, KeyError) as exc:
        logger.debug("Não foi possível ler o autostart: %s", exc)
        return ""


def alvo_atual() -> str:
    """O comando que ESTE processo usaria para se reinvocar."""
    if sys.platform == "win32":
        return _comando_windows()
    comando, argumentos = _executavel()
    return " ".join([comando, *argumentos])


def esta_ativo() -> bool:
    """Se o agente já está configurado para subir com o computador."""
    try:
        if sys.platform == "win32":
            # `.cmd` legado também conta: quem atualizou de uma versão antiga
            # não deve ver a opção "desmarcar" sozinha.
            return bool(_valor_no_registro()) or _atalho_windows().exists()
        return _atalho_linux().exists()
    except (OSError, KeyError) as exc:  # KeyError: APPDATA ausente
        logger.debug("Não foi possível checar o autostart: %s", exc)
        return False


def ativar() -> bool:
    """Registra a inicialização automática. Devolve se deu certo."""
    try:
        if sys.platform == "win32":
            _instalar_windows()
        else:
            _instalar_linux()
        logger.info("Autostart ativado em %s → %s", onde_esta_registrado(), alvo_atual())
        return True
    except (OSError, KeyError) as exc:
        logger.warning("Não foi possível ativar o autostart: %s", exc)
        return False


def desativar() -> bool:
    """Remove o registro. Devolve se deu certo (ausente já conta como sucesso)."""
    try:
        if sys.platform == "win32":
            _desinstalar_windows()
        else:
            _atalho_linux().unlink(missing_ok=True)
        logger.info("Autostart desativado.")
        return True
    except (OSError, KeyError) as exc:
        logger.warning("Não foi possível desativar o autostart: %s", exc)
        return False


def sincronizar() -> None:
    """Conserta sozinho, no arranque, um registro que aponta para lugar errado.

    O comando gravado é o caminho absoluto de onde o agente estava **quando a
    opção foi ligada**. Se depois disso alguém moveu o programa — o caso comum
    é ligar a opção com ele ainda na pasta de Downloads e só então movê-lo para
    a pasta definitiva — o registro passa a apontar para o vazio e falha em
    silêncio: nada sobe, e a opção continua marcada, dizendo que está tudo bem.

    Chamado a cada arranque: se o agente está rodando de um caminho diferente
    do registrado, ele reescreve. Barato, e transforma uma classe inteira de
    "não inicializou junto" em não-problema.
    """
    if not esta_ativo():
        return
    registrado, atual = alvo_registrado(), alvo_atual()
    if registrado and registrado == atual:
        return
    logger.info(
        "Autostart apontava para %s e este agente é %s — reescrevendo.",
        registrado or "(nada)", atual,
    )
    ativar()


def diagnostico() -> str:
    """Uma linha explicando o estado real, para a tela e o log.

    Vazio quando não há nada a dizer. Existe porque "a opção está marcada e
    mesmo assim não sobe" não tinha explicação nenhuma em lugar nenhum — o
    usuário reportou exatamente isso no Windows.
    """
    if not esta_ativo():
        return ""
    if desativado_pelo_windows():
        return (
            "O Windows está com esta inicialização DESATIVADA. Reative em "
            "Gerenciador de Tarefas > Inicializar (ou Configurações > Aplicativos "
            "> Inicialização) — desmarcar e marcar aqui não resolve."
        )
    registrado, atual = alvo_registrado(), alvo_atual()
    if registrado and registrado != atual:
        return f"A inicialização aponta para outro lugar: {registrado}"
    return ""
