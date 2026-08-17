"""Testes de /agent/stop e /agent/restart — controle do processo pedido pela
nova página "Impressão" do dashboard (2026-08-13). A ação real (os._exit/
os.execv) roda numa thread separada após um sleep curto; os testes mockam
essas três chamadas (time.sleep, os._exit, os.execv) pra verificar que a
rota aciona a função certa sem matar o processo de teste.

Desde a v0.3.0 essas duas ações vivem em ``app/agent_actions.py``, e não mais
soltas no ``main``: o menu da bandeja precisa exatamente do mesmo
comportamento (responder/atualizar a tela antes de o processo morrer), e ter
duas cópias seria ter duas regras. Por isso os mocks apontam para lá.
"""

from __future__ import annotations

import importlib
import time

import pytest
from fastapi.testclient import TestClient

from app import agent_actions


@pytest.fixture()
def app_module(monkeypatch):
    """Recarrega ``main`` com token/origem de teste — mesmo padrão de
    ``test_main.py::app_with_config``, mas devolve o módulo (não só o app)
    pra dar pra monkeypatchar os._exit/os.execv/time.sleep depois."""
    monkeypatch.setenv("AGENT_TOKEN", "segredo-teste")
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://localhost:3001")
    monkeypatch.setenv("PRINTER_DEST", "")
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", "/tmp/does-not-exist-agent-control.json")
    import main as main_module
    importlib.reload(main_module)
    return main_module


AUTH = {"Authorization": "Bearer segredo-teste", "Origin": "http://localhost:3001"}


def _wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_stop_without_token_is_rejected(app_module):
    client = TestClient(app_module.app)
    res = client.post("/agent/stop")
    assert res.status_code == 401


def test_restart_without_token_is_rejected(app_module):
    client = TestClient(app_module.app)
    res = client.post("/agent/restart")
    assert res.status_code == 401


def test_stop_responds_ok_before_exiting(app_module, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_actions.time, "sleep", lambda s: None)
    monkeypatch.setattr(agent_actions.os, "_exit", lambda code: calls.append(("_exit", code)))

    client = TestClient(app_module.app)
    res = client.post("/agent/stop", headers=AUTH)

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert _wait_for(lambda: calls == [("_exit", 0)])


def test_restart_responds_ok_before_reexecuting(app_module, monkeypatch):
    calls = []
    monkeypatch.setattr(agent_actions.time, "sleep", lambda s: None)
    monkeypatch.setattr(agent_actions.os, "execv", lambda path, args: calls.append((path, args)))

    client = TestClient(app_module.app)
    res = client.post("/agent/restart", headers=AUTH)

    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert _wait_for(lambda: len(calls) == 1)
    path, args = calls[0]
    assert path == agent_actions.sys.executable
    assert args == [agent_actions.sys.executable] + agent_actions.sys.argv
