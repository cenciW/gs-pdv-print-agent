"""``load_config()`` — env var vazia não pode se sobrepor ao config.json.

Bug real achado em 2026-08-14 testando o prompt de token de primeira
execução: ``os.getenv(key, default)`` só cai no ``default`` quando a env var
está AUSENTE. Se ela existir só vazia (``AGENT_TOKEN=`` num atalho/serviço mal
preenchido), ``getenv`` devolve essa string vazia e ignora o que está salvo
no ``config.json`` — o token gravado pelo prompt nunca era lido de volta, e
para os campos inteiros (``CHARS_PER_LINE``/``AGENT_PORT``) o mesmo padrão
quebrava com ``ValueError`` (``int("")``) em vez de só cair pro arquivo.
"""

from __future__ import annotations

import json

import pytest

from app.config import load_config


@pytest.fixture()
def config_file(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(path))

    def _write(data: dict) -> None:
        path.write_text(json.dumps(data), encoding="utf-8")

    return _write


def _clear_env(monkeypatch):
    for key in ("PRINTER_DEST", "CHARS_PER_LINE", "AGENT_TOKEN", "AGENT_PORT", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(key, raising=False)


def test_empty_env_token_falls_back_to_file(monkeypatch, config_file):
    _clear_env(monkeypatch)
    config_file({"token": "gspdv_salvo_no_arquivo"})
    monkeypatch.setenv("AGENT_TOKEN", "")  # presente, mas vazia — não deve vencer
    assert load_config().token == "gspdv_salvo_no_arquivo"


def test_empty_env_printer_dest_falls_back_to_file(monkeypatch, config_file):
    _clear_env(monkeypatch)
    config_file({"printer_dest": "192.168.1.50:9100"})
    monkeypatch.setenv("PRINTER_DEST", "")
    assert load_config().printer_dest == "192.168.1.50:9100"


def test_empty_env_chars_per_line_falls_back_to_file_without_crashing(monkeypatch, config_file):
    _clear_env(monkeypatch)
    config_file({"chars_per_line": 32})
    monkeypatch.setenv("CHARS_PER_LINE", "")  # antes: ValueError (int(""))
    assert load_config().chars_per_line == 32


def test_empty_env_port_falls_back_to_file_without_crashing(monkeypatch, config_file):
    _clear_env(monkeypatch)
    config_file({"port": 9200})
    monkeypatch.setenv("AGENT_PORT", "")
    assert load_config().port == 9200


def test_non_empty_env_still_wins_over_file(monkeypatch, config_file):
    _clear_env(monkeypatch)
    config_file({"token": "gspdv_do_arquivo"})
    monkeypatch.setenv("AGENT_TOKEN", "gspdv_da_env_var")
    assert load_config().token == "gspdv_da_env_var"


def test_absent_env_and_absent_file_uses_default(monkeypatch, tmp_path):
    _clear_env(monkeypatch)
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(tmp_path / "nao-existe.json"))
    cfg = load_config()
    assert cfg.token == ""
    assert cfg.chars_per_line == 48
    assert cfg.port == 9123
