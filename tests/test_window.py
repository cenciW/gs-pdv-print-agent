"""Janela do agente — construída de verdade, com Tk de verdade.

Pula sozinho onde não há display (o CI roda headless). O que estes testes
protegem é o que a verificação da Fase D não olhou: o caminho que o operador
percorre — achar a impressora, escolher o IP manual, salvar.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent_actions import AgentActions
from app.config import AgentConfig
from app.printers import PrinterInfo
from app.ui import window as window_module
from app.ui.window import _MODO_INSTALADA, _MODO_REDE, AgentWindow

pytestmark = pytest.mark.skipif(
    not window_module.disponivel(), reason="sem Tk/display nesta máquina",
)

_IMPRESSORAS = [
    PrinterInfo("HPRT-TP80K", True),
    PrinterInfo("POS-80"),
    PrinterInfo("Cozinha-Fundos"),
    PrinterInfo("HP-LaserJet-Recepcao"),
]


@pytest.fixture()
def janela(tmp_path, monkeypatch):
    """Janela montada sem entrar no ``mainloop`` — o laço é de quem executa."""
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(tmp_path / "config.json"))
    monkeypatch.setattr("app.agent_actions.list_printers", lambda: list(_IMPRESSORAS))

    import tkinter as tk

    actions = AgentActions(AgentConfig(token="tok", printer_dest="", chars_per_line=48))
    janela = AgentWindow(actions)
    janela._raiz = tk.Tk()  # noqa: SLF001
    janela._raiz.withdraw()  # noqa: SLF001
    janela._montar()  # noqa: SLF001
    try:
        yield janela
    finally:
        janela._raiz.destroy()  # noqa: SLF001


# ── A fila: única porta vinda de outra thread ───────────────────────────────


def test_agendar_nao_executa_na_hora(janela):
    """Quem agenda (a bandeja) nunca executa — é o que impede o congelamento."""
    feito = []
    janela.agendar(lambda: feito.append(1))
    assert feito == []

    janela._drenar()  # noqa: SLF001
    assert feito == [1]


def test_acao_agendada_que_falha_nao_derruba_a_janela(janela):
    def explode():
        raise RuntimeError("menu quebrado")

    janela.agendar(explode)
    janela.agendar(lambda: None)
    janela._drenar()  # noqa: SLF001

    assert janela._raiz.winfo_exists()  # noqa: SLF001


# ── Lista de impressoras com busca ──────────────────────────────────────────


def test_lista_comeca_com_todas_as_impressoras(janela):
    assert janela._lista.size() == len(_IMPRESSORAS)  # noqa: SLF001


def test_impressora_padrao_aparece_marcada(janela):
    """Sem isso o operador não sabe qual o sistema já usa."""
    assert "padrao do sistema" in janela._lista.get(0)  # noqa: SLF001


def test_busca_filtra_enquanto_digita(janela):
    """O Combobox `readonly` da v0.2.0 não deixava digitar para filtrar, e com
    23 impressoras "buscar" virava rolar."""
    janela._busca.set("hp")  # noqa: SLF001
    janela._raiz.update_idletasks()  # noqa: SLF001

    mostrados = [janela._lista.get(i) for i in range(janela._lista.size())]  # noqa: SLF001
    assert len(mostrados) == 2
    assert all("hp" in m.lower() for m in mostrados)


def test_busca_ignora_maiusculas(janela):
    janela._busca.set("COZINHA")  # noqa: SLF001
    janela._raiz.update_idletasks()  # noqa: SLF001
    assert janela._lista.size() == 1  # noqa: SLF001


def test_busca_sem_resultado_esvazia_a_lista(janela):
    janela._busca.set("zzz")  # noqa: SLF001
    janela._raiz.update_idletasks()  # noqa: SLF001
    assert janela._lista.size() == 0  # noqa: SLF001


def test_selecao_sobrevive_ao_filtro(janela):
    """Escolher, refinar a busca e ver a escolha ainda de pé."""
    janela._selecionar_na_lista("POS-80")  # noqa: SLF001
    assert janela._destino_escolhido() == "POS-80"  # noqa: SLF001

    janela._busca.set("pos")  # noqa: SLF001
    janela._raiz.update_idletasks()  # noqa: SLF001
    assert janela._destino_escolhido() == "POS-80"  # noqa: SLF001


# ── Impressora de rede: o caminho que o usuário não achou ───────────────────


def test_modo_rede_aceita_ip_digitado(janela):
    """Sintoma 3 da v0.2.0: "não consigo inserir um IP manual"."""
    janela._modo.set(_MODO_REDE)  # noqa: SLF001
    janela._sincronizar_modo()  # noqa: SLF001
    janela._endereco.set("192.168.1.50:9100")  # noqa: SLF001

    assert janela._destino_escolhido() == "192.168.1.50:9100"  # noqa: SLF001


def test_salvar_com_ip_persiste(janela):
    janela._modo.set(_MODO_REDE)  # noqa: SLF001
    janela._sincronizar_modo()  # noqa: SLF001
    janela._endereco.set("10.0.0.7")  # noqa: SLF001
    janela._largura.set(32)  # noqa: SLF001

    janela._actions.salvar_impressora(  # noqa: SLF001
        janela._destino_escolhido(), janela._largura.get(),  # noqa: SLF001
    )

    assert janela._actions.config.printer_dest == "10.0.0.7"  # noqa: SLF001
    assert janela._actions.config.chars_per_line == 32  # noqa: SLF001


def test_trocar_de_modo_alterna_os_paineis(janela):
    janela._modo.set(_MODO_REDE)  # noqa: SLF001
    janela._sincronizar_modo()  # noqa: SLF001
    assert janela._painel_rede.winfo_manager()  # noqa: SLF001
    assert not janela._painel_instalada.winfo_manager()  # noqa: SLF001

    janela._modo.set(_MODO_INSTALADA)  # noqa: SLF001
    janela._sincronizar_modo()  # noqa: SLF001
    assert janela._painel_instalada.winfo_manager()  # noqa: SLF001


# ── Reflexo do que está salvo ───────────────────────────────────────────────


def test_config_com_ip_abre_no_modo_rede(janela):
    """Impressora de rede não aparece em spooler nenhum — reabrir a janela não
    pode "esquecer" que a loja usa uma."""
    janela._actions.salvar_impressora("192.168.1.99:9100", 48)  # noqa: SLF001
    janela._recarregar_da_config()  # noqa: SLF001

    assert janela._modo.get() == _MODO_REDE  # noqa: SLF001
    assert janela._endereco.get() == "192.168.1.99:9100"  # noqa: SLF001


def test_config_com_impressora_instalada_abre_selecionada(janela):
    janela._actions.salvar_impressora("POS-80", 48)  # noqa: SLF001
    janela._recarregar_da_config()  # noqa: SLF001

    assert janela._modo.get() == _MODO_INSTALADA  # noqa: SLF001
    assert janela._destino_escolhido() == "POS-80"  # noqa: SLF001


def test_mudanca_vinda_do_painel_web_chega_na_janela(janela):
    """A configuração tem duas portas; sem o observador elas viram duas verdades.

    Simula o `PUT /config/printer` do painel enquanto a janela está aberta.
    """
    janela._cancelar_observador = janela._actions.observar(  # noqa: SLF001
        lambda: janela.agendar(janela._recarregar_da_config),
    )

    janela._actions.salvar_impressora("Cozinha-Fundos", 32)  # noqa: SLF001
    janela._drenar()  # noqa: SLF001

    assert janela._destino_escolhido() == "Cozinha-Fundos"  # noqa: SLF001
    assert janela._largura.get() == 32  # noqa: SLF001


# ── Barra de status ─────────────────────────────────────────────────────────


def test_status_avisa_quando_ha_mudanca_nao_salva(janela):
    janela._selecionar_na_lista("POS-80")  # noqa: SLF001
    janela._pintar_status()  # noqa: SLF001
    assert "não salvo" in janela._lbl_status.cget("text")  # noqa: SLF001


def test_status_limpa_o_aviso_depois_de_salvar(janela):
    janela._selecionar_na_lista("POS-80")  # noqa: SLF001
    janela._actions.salvar_impressora("POS-80", 48)  # noqa: SLF001
    janela._pintar_status()  # noqa: SLF001
    assert "não salvo" not in janela._lbl_status.cget("text")  # noqa: SLF001


def test_status_mostra_a_porta_do_servico(janela):
    janela._pintar_status()  # noqa: SLF001
    assert "9123" in janela._lbl_status.cget("text")  # noqa: SLF001


# ── Fechar a janela ─────────────────────────────────────────────────────────


def test_sem_bandeja_com_menu_a_janela_nao_esconde(janela):
    """No Linux/X11 o pystray não desenha menu: esconder deixaria a
    configuração inalcançável para sempre."""
    assert janela._ao_fechar_para_bandeja is None  # noqa: SLF001


def test_permitir_esconder_registra_o_caminho_de_volta(janela):
    janela.permitir_esconder_na_bandeja(lambda: None)
    assert janela._ao_fechar_para_bandeja is not None  # noqa: SLF001


def test_recarregar_limpa_a_busca_que_esconde_a_impressora_salva(janela):
    """Defeito real, achado pela verificação em ambiente gráfico.

    Com um filtro ativo, ``_recarregar_da_config`` selecionava uma impressora
    fora da lista visível e a seleção sumia em silêncio: a tela dizia "nenhuma
    escolhida" enquanto o ``config.json`` dizia outra coisa. O teste unitário
    não pegava porque não tinha busca preenchida.
    """
    janela._busca.set("cozinha")  # noqa: SLF001
    janela._raiz.update_idletasks()  # noqa: SLF001
    assert janela._lista.size() == 1  # noqa: SLF001

    janela._actions.salvar_impressora("POS-80", 48)  # noqa: SLF001
    janela._recarregar_da_config()  # noqa: SLF001

    assert janela._destino_escolhido() == "POS-80"  # noqa: SLF001
    assert janela._busca.get() == "", "a busca precisava ceder a vez"


def test_recarregar_preserva_a_busca_quando_ela_nao_atrapalha(janela):
    """O filtro do operador só cede quando esconde a resposta."""
    janela._busca.set("pos")  # noqa: SLF001
    janela._raiz.update_idletasks()  # noqa: SLF001

    janela._actions.salvar_impressora("POS-80", 48)  # noqa: SLF001
    janela._recarregar_da_config()  # noqa: SLF001

    assert janela._destino_escolhido() == "POS-80"  # noqa: SLF001
    assert janela._busca.get() == "pos"
