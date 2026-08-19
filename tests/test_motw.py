"""A "marca da web" que faz o Windows pedir confirmação a cada início.

Relato do usuário (2026-08-19): *"agora inicializou sozinho, mas ele pede uma
permissão para executar"*. Num computador de loja isso anula o autostart — o
agente fica esperando alguém clicar, e o primeiro cupom do dia não sai.
"""

from __future__ import annotations

import sys

from app import motw


def _fingir_windows(monkeypatch, exe):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))


def test_fora_do_windows_nunca_ha_marca(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    assert motw.esta_bloqueado() is False
    assert motw.desbloquear() is True


def test_rodando_pelo_python_nao_se_aplica(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert motw.esta_bloqueado() is False


def test_executavel_sem_marca_nao_pede_nada(monkeypatch, tmp_path):
    exe = tmp_path / "gs-pdv-print-agent.exe"
    exe.write_bytes(b"MZ")
    _fingir_windows(monkeypatch, exe)
    assert motw.esta_bloqueado() is False


def test_marca_detectada_e_removida(monkeypatch, tmp_path):
    """Fluxo alternativo é coisa do NTFS; aqui ele é simulado por um arquivo
    com o mesmo nome que o código abre — o que importa é a decisão, não o
    sistema de arquivos."""
    exe = tmp_path / "gs-pdv-print-agent.exe"
    exe.write_bytes(b"MZ")
    marca = tmp_path / "gs-pdv-print-agent.exe:Zone.Identifier"
    marca.write_text("[ZoneTransfer]\nZoneId=3\n", encoding="utf-8")
    _fingir_windows(monkeypatch, exe)

    assert motw.esta_bloqueado() is True
    assert motw.desbloquear() is True
    assert motw.esta_bloqueado() is False


def test_desbloquear_duas_vezes_nao_quebra(monkeypatch, tmp_path):
    exe = tmp_path / "gs-pdv-print-agent.exe"
    exe.write_bytes(b"MZ")
    _fingir_windows(monkeypatch, exe)
    assert motw.desbloquear() is True
    assert motw.desbloquear() is True


def test_sem_permissao_devolve_falso_sem_estourar(monkeypatch, tmp_path):
    """Instalado numa pasta onde o usuário não escreve: não é falha do agente,
    e não pode derrubar nada — só volta False para a tela poder explicar."""
    exe = tmp_path / "gs-pdv-print-agent.exe"
    exe.write_bytes(b"MZ")
    (tmp_path / "gs-pdv-print-agent.exe:Zone.Identifier").write_text("x", encoding="utf-8")
    _fingir_windows(monkeypatch, exe)

    def recusa(*_a, **_k):
        raise PermissionError("acesso negado")

    monkeypatch.setattr(motw.os, "remove", recusa)
    assert motw.desbloquear() is False
