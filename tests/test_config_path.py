"""Testes de resolução do caminho do ``config.json`` — bug real corrigido ao
empacotar (item 4 do planejamento, 2026-08-12): rodando via ``python
main.py``, o CWD é a pasta do projeto (comportamento de sempre); empacotado
com PyInstaller, o CWD é imprevisível (depende de como o SO/atalho/serviço
invoca o processo), então o agente precisa resolver relativo ao
**executável**, não ao CWD.
"""

from __future__ import annotations

import sys

from app.config import _config_path


def test_config_path_uses_cwd_when_not_frozen(monkeypatch):
    monkeypatch.delenv("GS_PRINT_AGENT_CONFIG", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert _config_path() == __import__("pathlib").Path(".") / "config.json"


def test_config_path_uses_executable_dir_when_frozen(monkeypatch, tmp_path):
    monkeypatch.delenv("GS_PRINT_AGENT_CONFIG", raising=False)
    fake_exe = tmp_path / "gs-pdv-print-agent.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(fake_exe), raising=False)
    assert _config_path() == tmp_path / "config.json"


def test_config_path_env_override_always_wins(monkeypatch, tmp_path):
    override = tmp_path / "custom.json"
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(override))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "agent.exe"), raising=False)
    assert _config_path() == override
