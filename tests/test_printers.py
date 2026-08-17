"""Testes da descoberta de impressoras do sistema.

A regra central: **lista vazia nunca pode virar exceção**. Este código roda no
computador da loja, em máquinas que podem não ter CUPS, não ter spooler, ou ter
um servidor de impressão fora do ar — e nenhum desses casos pode derrubar o
agente nem impedir a impressão pelo caminho de rede (IP:9100), que não aparece
em spooler nenhum.
"""

from __future__ import annotations

import subprocess
import sys

from app import printers
from app.printers import PrinterInfo, list_printers


def _fake_run(saidas: dict[str, str]):
    """Substitui ``subprocess.run`` devolvendo saída por subcomando do lpstat."""
    def run(comando, **_kwargs):
        chave = comando[1] if len(comando) > 1 else ""
        return subprocess.CompletedProcess(comando, 0, stdout=saidas.get(chave, ""), stderr="")
    return run


# ── CUPS ─────────────────────────────────────────────────────────────────────

def test_lista_impressoras_do_cups(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", _fake_run({
        "-p": (
            "printer HPRT-TP80K is idle.  enabled since ...\n"
            "printer Cozinha_58mm is idle.  enabled since ...\n"
        ),
        "-d": "system default destination: Cozinha_58mm\n",
    }))

    resultado = list_printers()
    assert [p.name for p in resultado] == ["Cozinha_58mm", "HPRT-TP80K"]


def test_impressora_padrao_vem_primeiro(monkeypatch):
    """A tela pré-seleciona a primeira — precisa ser a escolha mais provável."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", _fake_run({
        "-p": "printer AAA is idle.\nprinter ZZZ is idle.\n",
        "-d": "system default destination: ZZZ\n",
    }))

    resultado = list_printers()
    assert resultado[0].name == "ZZZ"
    assert resultado[0].is_default is True
    assert resultado[1].is_default is False


def test_reconhece_saida_do_lpstat_em_portugues(monkeypatch):
    """`lpstat` traduz a saída conforme o idioma do sistema; o nome segue sendo
    o segundo campo, e é só disso que o parsing depende."""
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", _fake_run({
        "-p": "impressora Balcao está ociosa.  ativada desde ...\n",
        "-d": "",
    }))

    assert [p.name for p in list_printers()] == ["Balcao"]


def test_sem_impressora_padrao_definida(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", _fake_run({
        "-p": "printer Balcao is idle.\n",
        "-d": "no system default destination\n",
    }))

    resultado = list_printers()
    assert len(resultado) == 1
    assert resultado[0].is_default is False


def test_maquina_sem_cups_devolve_vazio(monkeypatch):
    """Binário `lpstat` inexistente — comum em Windows e em servidor enxuto."""
    def run(*_args, **_kwargs):
        raise FileNotFoundError("lpstat")

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", run)
    assert list_printers() == []


def test_lpstat_travado_nao_segura_a_tela(monkeypatch):
    """Servidor de impressão fora do ar faz o `lpstat` estourar o timeout."""
    def run(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="lpstat", timeout=4)

    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", run)
    assert list_printers() == []


def test_linha_inesperada_e_ignorada_sem_quebrar(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(printers.subprocess, "run", _fake_run({
        "-p": "\n???\nprinter Balcao is idle.\nlixo\n",
        "-d": "",
    }))
    assert [p.name for p in list_printers()] == ["Balcao"]


# ── Windows ──────────────────────────────────────────────────────────────────

def test_lista_impressoras_do_windows(monkeypatch):
    """Inclui conexões de rede mapeadas, não só locais — impressora
    compartilhada de outro caixa é caso comum em loja."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(printers, "_listar_windows", lambda: [
        PrinterInfo(name="Microsoft Print to PDF"),
        PrinterInfo(name="HPRT TP80K", is_default=True),
    ])

    resultado = list_printers()
    assert resultado[0].name == "HPRT TP80K"
    assert [p.name for p in resultado] == ["HPRT TP80K", "Microsoft Print to PDF"]


def test_falha_do_spooler_devolve_vazio(monkeypatch):
    """Qualquer erro vira lista vazia: a tela cai no campo de texto livre em
    vez de mostrar um erro que o operador não sabe resolver."""
    def explode():
        raise OSError("spooler indisponível")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(printers, "_listar_windows", explode)
    assert list_printers() == []


def test_to_dict_expoe_o_contrato_da_rota():
    assert PrinterInfo(name="Balcao", is_default=True).to_dict() == {
        "name": "Balcao", "is_default": True,
    }
