"""Testes do prompt interativo de primeira execução (main.py::
_prompt_for_token_if_missing) — pede o token no console quando ele falta e
tem alguém sentado ali (`isatty()`); nunca trava esperando input quando
rodando sem terminal (serviço/systemd), pra não travar o boot pra sempre.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def main_module(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENT_TOKEN", "")
    monkeypatch.setenv("PRINTER_DEST", "")
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(tmp_path / "config.json"))
    import main as main_module
    importlib.reload(main_module)
    return main_module


def test_does_not_prompt_when_token_already_set(main_module, monkeypatch):
    called = []
    monkeypatch.setattr("builtins.input", lambda *a: called.append(1) or "nunca-deveria-chamar")
    cfg = main_module.app.state.config
    cfg.token = "ja-configurado"
    main_module._prompt_for_token_if_missing(cfg)
    assert called == []
    assert cfg.token == "ja-configurado"


def test_does_not_prompt_when_not_a_tty(main_module, monkeypatch):
    called = []
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda *a: called.append(1) or "nunca-deveria-chamar")
    cfg = main_module.app.state.config
    assert cfg.token == ""
    main_module._prompt_for_token_if_missing(cfg)
    assert called == []
    assert cfg.token == ""


def test_prompts_and_saves_token_when_tty_and_missing(main_module, monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "  gspdv_colado-no-console  ")
    cfg = main_module.app.state.config
    assert cfg.token == ""
    main_module._prompt_for_token_if_missing(cfg)
    assert cfg.token == "gspdv_colado-no-console"

    import json
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["token"] == "gspdv_colado-no-console"


def test_empty_input_does_not_save_anything(main_module, monkeypatch, tmp_path):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda *a: "   ")
    cfg = main_module.app.state.config
    main_module._prompt_for_token_if_missing(cfg)
    assert cfg.token == ""
    assert not (tmp_path / "config.json").exists()


def test_eof_or_interrupt_does_not_crash(main_module, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _raise(*a):
        raise EOFError

    monkeypatch.setattr("builtins.input", _raise)
    cfg = main_module.app.state.config
    main_module._prompt_for_token_if_missing(cfg)  # não deve levantar
    assert cfg.token == ""
