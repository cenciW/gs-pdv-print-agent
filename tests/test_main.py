"""Testes dos endpoints do agente via TestClient — auth (token + Origin) e
o caminho feliz de impressão (contra um servidor TCP fake, sem impressora
real).
"""

from __future__ import annotations

import importlib
import socket
import threading

import pytest
from fastapi.testclient import TestClient


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class _FakePrinterServer:
    def __init__(self, port: int) -> None:
        self.received = b""
        self._srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._srv.bind(("127.0.0.1", port))
        self._srv.settimeout(3)
        self._srv.listen(1)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        try:
            conn, _ = self._srv.accept()
            with conn:
                conn.settimeout(3)
                chunks = []
                while True:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    chunks.append(chunk)
                self.received = b"".join(chunks)
        except OSError:
            pass


@pytest.fixture()
def app_with_config(monkeypatch):
    """Recarrega ``main`` com env vars de teste — token, origem e impressora
    configurados por teste, sem depender de estado global entre testes."""
    port = _free_port()

    def _build(
        printer_dest: str = "", token: str = "segredo-teste", origins: str = "http://localhost:3001",
        config_path: str = "/tmp/does-not-exist.json",
    ):
        monkeypatch.setenv("AGENT_TOKEN", token)
        monkeypatch.setenv("ALLOWED_ORIGINS", origins)
        monkeypatch.setenv("PRINTER_DEST", printer_dest)
        monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", config_path)
        import main as main_module
        importlib.reload(main_module)
        return main_module.app

    return _build, port


def test_health_has_no_auth_and_reports_printer_status(app_with_config):
    build, _ = app_with_config
    app = build(printer_dest="")
    client = TestClient(app)
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "printer_configured": False, "printer_dest": "", "chars_per_line": 48}


def test_set_printer_without_token_is_rejected(app_with_config):
    build, _ = app_with_config
    app = build(printer_dest="")
    client = TestClient(app)
    res = client.put("/config/printer", json={"printer_dest": "192.168.1.99:9100"})
    assert res.status_code == 401


def test_set_printer_updates_health_immediately(app_with_config, tmp_path):
    build, _ = app_with_config
    app = build(printer_dest="", config_path=str(tmp_path / "config.json"))
    client = TestClient(app)

    res = client.put(
        "/config/printer", json={"printer_dest": "192.168.1.99:9100"},
        headers={"Authorization": "Bearer segredo-teste", "Origin": "http://localhost:3001"},
    )
    assert res.status_code == 200
    assert res.json()["printer_dest"] == "192.168.1.99:9100"

    health = client.get("/health").json()
    assert health["printer_configured"] is True
    assert health["printer_dest"] == "192.168.1.99:9100"


def test_set_printer_persists_to_config_file(app_with_config, tmp_path):
    config_path = tmp_path / "config.json"
    build, _ = app_with_config
    app = build(printer_dest="", config_path=str(config_path))
    client = TestClient(app)

    client.put(
        "/config/printer", json={"printer_dest": "10.0.0.5"},
        headers={"Authorization": "Bearer segredo-teste", "Origin": "http://localhost:3001"},
    )

    import json
    saved = json.loads(config_path.read_text())
    assert saved["printer_dest"] == "10.0.0.5"


def test_set_printer_updates_chars_per_line(app_with_config, tmp_path):
    build, _ = app_with_config
    app = build(printer_dest="", config_path=str(tmp_path / "config.json"))
    client = TestClient(app)

    res = client.put(
        "/config/printer", json={"printer_dest": "192.168.1.5", "chars_per_line": 32},
        headers={"Authorization": "Bearer segredo-teste", "Origin": "http://localhost:3001"},
    )
    assert res.status_code == 200
    assert res.json()["chars_per_line"] == 32
    assert client.get("/health").json()["chars_per_line"] == 32


def test_set_printer_rejects_absurd_chars_per_line(app_with_config, tmp_path):
    build, _ = app_with_config
    app = build(printer_dest="", config_path=str(tmp_path / "config.json"))
    client = TestClient(app)

    res = client.put(
        "/config/printer", json={"printer_dest": "192.168.1.5", "chars_per_line": 5},
        headers={"Authorization": "Bearer segredo-teste", "Origin": "http://localhost:3001"},
    )
    assert res.status_code == 400


def test_print_without_token_is_rejected(app_with_config):
    build, port = app_with_config
    app = build(printer_dest=f"127.0.0.1:{port}")
    client = TestClient(app)
    res = client.post("/print", json={"text": "abc"})
    assert res.status_code == 401


def test_print_with_wrong_token_is_rejected(app_with_config):
    build, port = app_with_config
    app = build(printer_dest=f"127.0.0.1:{port}")
    client = TestClient(app)
    res = client.post("/print", json={"text": "abc"}, headers={"Authorization": "Bearer errado"})
    assert res.status_code == 401


def test_print_with_disallowed_origin_is_rejected_even_with_right_token(app_with_config):
    build, port = app_with_config
    app = build(printer_dest=f"127.0.0.1:{port}")
    client = TestClient(app)
    res = client.post(
        "/print", json={"text": "abc"},
        headers={"Authorization": "Bearer segredo-teste", "Origin": "http://evil.example.com"},
    )
    assert res.status_code == 403


def test_print_without_printer_configured_returns_503(app_with_config):
    build, _ = app_with_config
    app = build(printer_dest="")
    client = TestClient(app)
    res = client.post("/print", json={"text": "abc"}, headers={"Authorization": "Bearer segredo-teste"})
    assert res.status_code == 503


def test_print_happy_path_sends_escpos_bytes_to_printer(app_with_config):
    build, port = app_with_config
    server = _FakePrinterServer(port)
    app = build(printer_dest=f"127.0.0.1:{port}")
    client = TestClient(app)
    res = client.post(
        "/print", json={"text": "CUPOM"},
        headers={"Authorization": "Bearer segredo-teste", "Origin": "http://localhost:3001"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    assert b"CUPOM" in server.received
    assert server.received.startswith(b"\x1B\x40")  # ESC @ no início do payload


# ── /printers (2026-08-17) ───────────────────────────────────────────────────
# A lista alimenta o seletor de impressora do painel. Exige token, ao contrário
# de /health: nome de impressora é informação da máquina da loja, e o probe de
# liveness não precisa disso.

def test_printers_requires_token(app_with_config):
    build, _ = app_with_config
    app = build()
    res = TestClient(app).get("/printers")
    assert res.status_code == 401


def test_printers_lists_system_printers(app_with_config, monkeypatch):
    from app import agent_actions
    from app.printers import PrinterInfo

    build, _ = app_with_config
    app = build()
    monkeypatch.setattr(agent_actions, "list_printers", lambda: [
        PrinterInfo(name="HPRT TP80K", is_default=True),
        PrinterInfo(name="Cozinha"),
    ])

    res = TestClient(app).get("/printers", headers={"Authorization": "Bearer segredo-teste"})
    assert res.status_code == 200
    assert res.json() == {"printers": [
        {"name": "HPRT TP80K", "is_default": True},
        {"name": "Cozinha", "is_default": False},
    ]}


def test_printers_empty_is_a_valid_answer(app_with_config, monkeypatch):
    """Máquina sem spooler/CUPS: 200 com lista vazia, nunca erro. O painel cai
    no campo de texto livre — que é também o caminho da impressora de rede."""
    from app import agent_actions

    build, _ = app_with_config
    app = build()
    monkeypatch.setattr(agent_actions, "list_printers", list)

    res = TestClient(app).get("/printers", headers={"Authorization": "Bearer segredo-teste"})
    assert res.status_code == 200
    assert res.json() == {"printers": []}
