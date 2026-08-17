"""Testes do "iniciar com o computador".

O que importa aqui não é o formato do atalho e sim a promessa: ligar cria,
desligar remove, e **nenhuma falha derruba o agente** — se a pasta não existe
ou o sistema recusa a escrita, o agente segue imprimindo agora, que é o que o
lojista precisa neste minuto.
"""

from __future__ import annotations

import sys

from app import autostart


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


def test_ciclo_completo_no_windows(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))

    assert autostart.ativar() is True
    atalho = autostart.caminho_do_atalho()
    assert atalho.name == "gs-pdv-print-agent.cmd"
    assert atalho.parent.name == "Startup"

    conteudo = atalho.read_text(encoding="utf-8")
    # `start ""` faz o console fechar em vez de ficar aberto atrás do ícone.
    assert conteudo.startswith("@echo off")
    assert 'start ""' in conteudo


def test_caminho_com_espaco_fica_entre_aspas(monkeypatch, tmp_path):
    """"C:\\Program Files\\..." sem aspas vira dois argumentos e o atalho falha
    em silêncio — o computador reinicia e a impressora "para de funcionar"."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Program Files\GS\gs-pdv-print-agent.exe")

    autostart.ativar()
    conteudo = autostart.caminho_do_atalho().read_text(encoding="utf-8")
    assert '"C:\\Program Files\\GS\\gs-pdv-print-agent.exe"' in conteudo


def test_falha_de_escrita_nao_levanta(monkeypatch):
    """Pasta inexistente/sem permissão devolve False, não exceção."""
    monkeypatch.setattr(sys, "platform", "linux")

    def explode(*_args, **_kwargs):
        raise OSError("permissão negada")

    monkeypatch.setattr(autostart.Path, "mkdir", explode)
    assert autostart.ativar() is False


def test_appdata_ausente_nao_levanta(monkeypatch):
    """`APPDATA` sempre existe no Windows real, mas o código não pode explodir
    se alguém rodar num ambiente estranho."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.delenv("APPDATA", raising=False)
    assert autostart.esta_ativo() is False
    assert autostart.ativar() is False
