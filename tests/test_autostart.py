"""Testes do "iniciar com o computador".

O que importa aqui não é o formato do atalho e sim a promessa: ligar cria,
desligar remove, e **nenhuma falha derruba o agente** — se a pasta não existe
ou o sistema recusa a escrita, o agente segue imprimindo agora, que é o que o
lojista precisa neste minuto.
"""

from __future__ import annotations

import sys
import types

import pytest

from app import autostart


class _FakeWinreg:
    """Registro do Windows de mentira, para o caminho do Windows ser testável.

    Sem isto, tudo que o Windows faz ficaria sem teste em CI Linux — e o
    autostart do Windows é justamente o que quebrou em uso real. Guarda
    ``{caminho_da_chave: {nome: valor}}`` e imita só o que o código usa.
    """

    HKEY_CURRENT_USER = "HKCU"
    REG_SZ = 1
    KEY_SET_VALUE = 2

    def __init__(self) -> None:
        self.dados: dict[str, dict[str, object]] = {}

    # `with winreg.OpenKey(...) as chave:` — a "chave" é só o caminho.
    class _Chave:
        def __init__(self, caminho: str) -> None:
            self.caminho = caminho

        def __enter__(self):
            return self.caminho

        def __exit__(self, *_):
            return False

    def OpenKey(self, _raiz, caminho, _reservado=0, _acesso=0):  # noqa: N802
        if caminho not in self.dados:
            raise FileNotFoundError(caminho)
        return self._Chave(caminho)

    def CreateKey(self, _raiz, caminho):  # noqa: N802
        self.dados.setdefault(caminho, {})
        return self._Chave(caminho)

    def SetValueEx(self, caminho, nome, _reservado, _tipo, valor):  # noqa: N802
        self.dados.setdefault(caminho, {})[nome] = valor

    def QueryValueEx(self, caminho, nome):  # noqa: N802
        valores = self.dados.get(caminho, {})
        if nome not in valores:
            raise FileNotFoundError(nome)
        return valores[nome], 1

    def DeleteValue(self, caminho, nome):  # noqa: N802
        if nome not in self.dados.get(caminho, {}):
            raise FileNotFoundError(nome)
        del self.dados[caminho][nome]


@pytest.fixture
def windows(monkeypatch, tmp_path):
    """Coloca o teste no Windows, com registro falso e APPDATA temporário."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    falso = _FakeWinreg()
    modulo = types.ModuleType("winreg")
    for nome in dir(falso):
        if not nome.startswith("_") or nome.isupper():
            setattr(modulo, nome, getattr(falso, nome))
    modulo.HKEY_CURRENT_USER = falso.HKEY_CURRENT_USER
    modulo.REG_SZ = falso.REG_SZ
    modulo.KEY_SET_VALUE = falso.KEY_SET_VALUE
    monkeypatch.setitem(sys.modules, "winreg", modulo)
    return falso


def test_ciclo_completo_no_linux(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert autostart.esta_ativo() is False
    assert autostart.ativar() is True
    assert autostart.esta_ativo() is True

    conteudo = autostart.caminho_do_atalho().read_text(encoding="utf-8")
    assert "[Desktop Entry]" in conteudo
    assert "Exec=" in conteudo
    # `Terminal=false`: o autostart não pode abrir uma janela preta na cara de
    # quem só ligou o computador da loja.
    assert "Terminal=false" in conteudo

    assert autostart.desativar() is True
    assert autostart.esta_ativo() is False


def test_desativar_duas_vezes_nao_quebra(monkeypatch, tmp_path):
    """Idempotência: o menu da bandeja pode ser clicado duas vezes rápido."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert autostart.desativar() is True
    assert autostart.desativar() is True


def test_ciclo_completo_no_windows(windows):
    """Registra na chave `Run`, não mais um `.cmd` na pasta Startup.

    O usuário reportou o que a pasta Startup permite: *"ele inicializa normal,
    mas não inicializa junto com o windows"*. Quem executa a chave `Run` é o
    logon do Windows, não o Explorer.
    """
    assert autostart.esta_ativo() is False
    assert autostart.ativar() is True
    assert autostart.esta_ativo() is True
    assert "CurrentVersion\\Run" in autostart.onde_esta_registrado()
    assert autostart.alvo_registrado() == autostart.alvo_atual()

    assert autostart.desativar() is True
    assert autostart.esta_ativo() is False


def test_cmd_antigo_e_removido_ao_ligar(windows, tmp_path):
    """Senão o agente subiria DUAS vezes e a segunda morreria com a porta ocupada."""
    legado = autostart._atalho_windows()
    legado.parent.mkdir(parents=True, exist_ok=True)
    legado.write_text("@echo off\r\n", encoding="utf-8")

    autostart.ativar()
    assert not legado.exists()


def test_cmd_antigo_ainda_conta_como_ativo(windows):
    """Quem atualiza de uma versão antiga não pode ver a opção se desmarcar sozinha."""
    legado = autostart._atalho_windows()
    legado.parent.mkdir(parents=True, exist_ok=True)
    legado.write_text("@echo off\r\n", encoding="utf-8")
    assert autostart.esta_ativo() is True


def test_caminho_com_espaco_fica_entre_aspas(windows, monkeypatch):
    """`C:\\Program Files\\...` sem aspas vira dois argumentos e falha em
    silêncio — o computador reinicia e a impressora "para de funcionar"."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\GS\gs-pdv-print-agent.exe")

    autostart.ativar()
    assert '"C:\\Program Files\\GS\\gs-pdv-print-agent.exe"' in autostart.alvo_registrado()


def test_agente_movido_de_pasta_se_conserta_no_arranque(windows, monkeypatch):
    """O caso mais comum de "não inicializou junto".

    O comando gravado é o caminho de ONDE O AGENTE ESTAVA quando a opção foi
    ligada. Ligar na pasta de Downloads e depois mover para Arquivos de
    Programas deixava o registro apontando para o vazio, falhando em silêncio
    com a opção ainda marcada.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Users\ze\Downloads\gs-pdv-print-agent.exe")
    autostart.ativar()
    antigo = autostart.alvo_registrado()

    monkeypatch.setattr(sys, "executable", r"C:\Program Files\GS\gs-pdv-print-agent.exe")
    assert autostart.diagnostico().startswith("A inicialização aponta para outro lugar")

    autostart.sincronizar()
    assert autostart.alvo_registrado() != antigo
    assert autostart.alvo_registrado() == autostart.alvo_atual()
    assert autostart.diagnostico() == ""


def test_sincronizar_nao_liga_o_que_estava_desligado(windows):
    """Quem desmarcou a opção não pode vê-la voltar sozinha no próximo arranque."""
    autostart.sincronizar()
    assert autostart.esta_ativo() is False


def test_desativado_pelo_windows_e_explicado(windows):
    """Estado em que o agente está certo e o Windows o ignora.

    Sem ler isto, "a opção está marcada e mesmo assim não sobe" não tem
    explicação nenhuma em lugar nenhum — que é exatamente o relato.
    """
    autostart.ativar()
    assert autostart.diagnostico() == ""

    windows.dados.setdefault(autostart._CHAVE_APROVACAO, {})[
        "gs-pdv-print-agent"
    ] = bytes([3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])

    assert autostart.desativado_pelo_windows() is True
    assert "Gerenciador de Tarefas" in autostart.diagnostico()


def test_habilitado_no_windows_nao_vira_aviso(windows):
    autostart.ativar()
    windows.dados.setdefault(autostart._CHAVE_APROVACAO, {})[
        "gs-pdv-print-agent"
    ] = bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    assert autostart.desativado_pelo_windows() is False
    assert autostart.diagnostico() == ""


def test_falha_de_escrita_nao_levanta(monkeypatch):
    """Pasta inexistente/sem permissão devolve False, não exceção."""
    monkeypatch.setattr(sys, "platform", "linux")

    def explode(*_args, **_kwargs):
        raise OSError("permissão negada")

    monkeypatch.setattr(autostart.Path, "mkdir", explode)
    assert autostart.ativar() is False


def test_appdata_ausente_nao_levanta(windows, monkeypatch):
    """`APPDATA` sempre existe no Windows real, mas o código não pode explodir
    se alguém rodar num ambiente estranho — a limpeza do `.cmd` legado usa ele."""
    monkeypatch.delenv("APPDATA", raising=False)
    assert autostart.esta_ativo() is False
    assert autostart.ativar() is False
