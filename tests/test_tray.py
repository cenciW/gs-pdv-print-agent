"""Bandeja — e a regressão do congelamento que reprovou a v0.2.0.

O teste central deste arquivo é ``test_item_de_menu_nao_executa_na_thread_da_
bandeja``. Ele existe porque o defeito da v0.2.0 não era um erro de digitação
que se corrige e some: era uma armadilha estrutural. O ``pystray`` despacha o
callback do menu de dentro da bomba de mensagens do Windows
(``_win32.py:224`` → ``_on_notify`` → ``DispatchMessage``), então qualquer
callback que demore prende a bandeja inteira — e abrir uma janela ``tkinter``
com ``mainloop()`` é o caso extremo: prende enquanto a janela viver.

Nenhum teste de "a janela abre?" pegaria isso. O que precisa ficar travado é a
regra: **item de menu enfileira, nunca executa**. É o que este arquivo fixa, e
sem depender do sistema operacional — roda igual no Linux do CI e diria a mesma
coisa no Windows onde o defeito apareceu.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent_actions import AgentActions
from app.config import AgentConfig
from app.ui.tray import TrayAccessory, _desenhar_icone, _titulo_seguro, suporta_menu


@pytest.fixture()
def actions(tmp_path, monkeypatch) -> AgentActions:
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(tmp_path / "config.json"))
    config = AgentConfig(token="tok", printer_dest="192.168.1.50", chars_per_line=48)
    return AgentActions(config)


def _bandeja(actions: AgentActions, fila: list) -> TrayAccessory:
    return TrayAccessory(actions, agendar=fila.append, ao_mostrar_janela=lambda: None)


# ── A regressão ─────────────────────────────────────────────────────────────


def test_item_de_menu_nao_executa_na_thread_da_bandeja(actions):
    """O callback só enfileira; quem executa é o laço da janela.

    Se alguém voltar a chamar trabalho direto no callback, este teste falha —
    é a única barreira contra o congelamento voltar.
    """
    fila: list = []
    bandeja = _bandeja(actions, fila)
    executou = []

    callback = bandeja._item(lambda: executou.append(True))  # noqa: SLF001
    callback()

    assert executou == [], "a ação rodou na thread da bandeja — é o defeito da v0.2.0"
    assert len(fila) == 1, "a ação precisava ter ido para a fila da janela"

    fila[0]()
    assert executou == [True], "a fila da janela precisa executar a ação de verdade"


def test_callback_de_menu_retorna_na_hora_mesmo_com_acao_lenta(actions):
    """Uma ação que bloqueia por 2s não pode segurar o callback do menu.

    Reproduz a forma do defeito sem precisar de Tk: no Windows, o tempo que o
    callback demora é tempo com a bomba de mensagens parada.
    """
    fila: list = []
    bandeja = _bandeja(actions, fila)

    callback = bandeja._item(lambda: time.sleep(2))  # noqa: SLF001
    comeco = time.monotonic()
    callback()
    decorrido = time.monotonic() - comeco

    assert decorrido < 0.1, f"o callback segurou a bandeja por {decorrido:.2f}s"


def test_agendar_pode_ser_chamado_de_outra_thread(actions):
    """A fila é a única porta de entrada vinda de fora — precisa aguentar."""
    fila: list = []
    bandeja = _bandeja(actions, fila)
    callback = bandeja._item(lambda: None)  # noqa: SLF001

    threads = [threading.Thread(target=callback) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    assert all(not t.is_alive() for t in threads)
    assert len(fila) == 8


# ── Honestidade sobre o que o sistema suporta ───────────────────────────────


def test_suporta_menu_reflete_a_capacidade_real_do_backend(monkeypatch):
    """No X11 o pystray aceita o menu e o descarta — não podemos acreditar nele.

    ``_xorg.py`` declara ``HAS_MENU = False`` e ``_update_menu`` é ``pass``.
    Era por isso que, no Linux, o ícone da v0.2.0 aparecia e não fazia nada.
    """
    import pystray

    class SemMenu:
        HAS_MENU = False

    monkeypatch.setattr(pystray, "Icon", SemMenu)
    assert suporta_menu() is False

    class ComMenu:
        HAS_MENU = True

    monkeypatch.setattr(pystray, "Icon", ComMenu)
    assert suporta_menu() is True


def test_suporta_menu_e_falso_sem_pystray(monkeypatch):
    monkeypatch.setitem(sys.modules, "pystray", None)
    assert suporta_menu() is False


# ── Título e ícone ──────────────────────────────────────────────────────────


def test_titulo_seguro_troca_travessao():
    """Regressão: um travessão no título matou o agente inteiro (2026-08-17).

    O backend X11 codifica o título em latin-1 e levanta fora dessa faixa.
    """
    assert _titulo_seguro("Agente — pronto") == "Agente - pronto"
    _titulo_seguro("emoji 🖨 fora de latin-1").encode("latin-1")


def test_titulo_seguro_preserva_acento_portugues():
    assert _titulo_seguro("Impressão não configurada") == "Impressão não configurada"


def test_desenhar_icone_muda_de_cor_conforme_o_estado():
    pronto = _desenhar_icone(True)
    parado = _desenhar_icone(False)
    assert pronto.size == parado.size
    assert list(pronto.getdata()) != list(parado.getdata())


def test_montar_menu_expoe_as_acoes_esperadas(actions):
    fila: list = []
    bandeja = _bandeja(actions, fila)
    rotulos = [str(item.text) for item in bandeja._montar_menu().items]  # noqa: SLF001

    assert "Abrir configuracao" in rotulos
    assert "Testar impressao" in rotulos
    assert "Sair" in rotulos
    # "Abrir painel no navegador" saiu na v0.3.0: o usuário pediu tudo desktop,
    # e o painel web dele nem abria por causa do congelamento.
    assert not any("painel" in r.lower() for r in rotulos)


def test_primeira_linha_do_menu_mostra_o_estado(actions):
    fila: list = []
    bandeja = _bandeja(actions, fila)
    primeiro = bandeja._montar_menu().items[0]  # noqa: SLF001

    assert primeiro.enabled is False, "a linha de status não é clicável"
    assert "192.168.1.50" in str(primeiro.text)


def test_parar_sem_ter_iniciado_nao_levanta(actions):
    """A bandeja é conforto: nada nela pode derrubar o agente."""
    _bandeja(actions, []).parar()
