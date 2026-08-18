"""Núcleo de ações — a fonte única que janela, bandeja e rotas HTTP usam.

Testável sem display e sem subir servidor justamente porque não importa
tkinter, pystray nem FastAPI. Era esse o ponto de extrair a camada.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent_actions import (
    AgentActions,
    ConfiguracaoInvalida,
    montar_cupom_de_teste,
)
from app.config import AgentConfig
from app.printer_client import PrinterSendError
from app.printers import PrinterInfo


@pytest.fixture()
def arquivo(tmp_path, monkeypatch) -> Path:
    caminho = tmp_path / "config.json"
    monkeypatch.setenv("GS_PRINT_AGENT_CONFIG", str(caminho))
    return caminho


@pytest.fixture()
def actions(arquivo) -> AgentActions:
    return AgentActions(AgentConfig(token="tok", printer_dest="Cozinha", chars_per_line=48))


# ── Status ──────────────────────────────────────────────────────────────────


def test_status_pronto_quando_tem_token_e_impressora(actions):
    status = actions.status()
    assert status.pronto is True
    assert status.motivo == ""
    assert "Cozinha" in status.resumo()


def test_status_sem_token_nao_esta_pronto(arquivo):
    """Sem token, ``/print`` recusa tudo — a tela precisa dizer isso."""
    actions = AgentActions(AgentConfig(token="", printer_dest="Cozinha"))
    status = actions.status()
    assert status.pronto is False
    assert "token" in status.motivo.lower()


def test_status_sem_impressora_nao_esta_pronto(arquivo):
    actions = AgentActions(AgentConfig(token="tok", printer_dest=""))
    assert actions.status().pronto is False
    assert "impressora" in actions.status().motivo.lower()


def test_status_reporta_servidor_fora_do_ar(arquivo):
    actions = AgentActions(AgentConfig(token="t", printer_dest="X"), servidor_no_ar=lambda: False)
    assert actions.status().servidor_no_ar is False


# ── Gravação ────────────────────────────────────────────────────────────────


def test_salvar_impressora_persiste_no_arquivo(actions, arquivo):
    actions.salvar_impressora("192.168.1.50:9100", 32)

    assert actions.config.printer_dest == "192.168.1.50:9100"
    assert json.loads(arquivo.read_text())["chars_per_line"] == 32


def test_salvar_impressora_remove_espacos_em_volta(actions):
    """Endereço colado de um bilhete costuma vir com espaço — e um espaço no
    nome da impressora vira erro de impressão que não explica nada."""
    actions.salvar_impressora("  192.168.1.50  ", 48)
    assert actions.config.printer_dest == "192.168.1.50"


@pytest.mark.parametrize("largura", [19, 65, 0, -1])
def test_salvar_impressora_recusa_largura_fora_da_faixa(actions, largura):
    with pytest.raises(ConfiguracaoInvalida):
        actions.salvar_impressora("Cozinha", largura)


def test_salvar_token_persiste(actions, arquivo):
    actions.salvar_token("  novo-token  ")
    assert actions.config.token == "novo-token"
    assert json.loads(arquivo.read_text())["token"] == "novo-token"


def test_salvar_token_vazio_e_permitido(actions):
    """É como se apaga um token errado. O estado "sem token" já é tratado em
    todo lugar (falha fechada)."""
    actions.salvar_token("")
    assert actions.config.token == ""
    assert actions.status().pronto is False


# ── Observador ──────────────────────────────────────────────────────────────


def test_observador_e_avisado_ao_salvar(actions):
    """É o que faz a janela aberta refletir uma mudança feita pelo painel web,
    em vez de continuar mostrando o valor antigo."""
    avisos = []
    actions.observar(lambda: avisos.append(1))

    actions.salvar_impressora("Outra", 48)
    actions.salvar_token("t2")

    assert len(avisos) == 2


def test_observador_pode_cancelar_a_inscricao(actions):
    avisos = []
    cancelar = actions.observar(lambda: avisos.append(1))
    cancelar()
    actions.salvar_token("t")
    assert avisos == []


def test_observador_que_falha_nao_desfaz_o_save(actions):
    """Tela quebrada não pode fazer um save parecer que não aconteceu."""
    def explode():
        raise RuntimeError("tela morreu")

    actions.observar(explode)
    actions.salvar_impressora("Nova", 48)

    assert actions.config.printer_dest == "Nova"


# ── Teste de impressão ──────────────────────────────────────────────────────


def test_testar_impressao_usa_a_largura_pedida_sem_salvar(actions, monkeypatch):
    """Calibrar é imprimir, olhar o papel e ajustar. Obrigar a salvar antes de
    testar transformaria a calibração num vaivém."""
    enviados = []
    monkeypatch.setattr(
        "app.agent_actions.send_raw_bytes",
        lambda raw, dest: enviados.append((raw, dest)),
    )

    actions.testar_impressao(32)

    assert actions.config.chars_per_line == 48, "testar não pode salvar a largura"
    assert b"32 colunas" in enviados[0][0]
    assert enviados[0][1] == "Cozinha"


def test_testar_impressao_sem_impressora_recusa_com_mensagem(arquivo):
    actions = AgentActions(AgentConfig(token="t", printer_dest=""))
    with pytest.raises(ConfiguracaoInvalida):
        actions.testar_impressao()


def test_testar_impressao_propaga_falha_da_impressora(actions, monkeypatch):
    """A mensagem do erro é o resultado do teste — precisa chegar à tela."""
    def falhar(raw, dest):
        raise PrinterSendError("Não foi possível imprimir em 'Cozinha': timeout")

    monkeypatch.setattr("app.agent_actions.send_raw_bytes", falhar)
    with pytest.raises(PrinterSendError, match="timeout"):
        actions.testar_impressao()


# ── Cupom de teste ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("largura", [48, 32, 20, 64])
def test_cupom_de_teste_nunca_estoura_a_largura(largura):
    """Um cupom de teste que estoura o papel mente sobre a calibração."""
    for linha in montar_cupom_de_teste(largura).split("\n"):
        assert len(linha) <= largura, f"linha de {len(linha)} num papel de {largura}"


def test_cupom_de_teste_tem_regua_numerada():
    """A régua é o que transforma "muito papel em branco" em diagnóstico: se os
    números quebram para a linha de baixo, a largura está maior que o papel."""
    cupom = montar_cupom_de_teste(48)
    assert "45" in cupom
    assert "Largura configurada: 48 colunas" in cupom


def test_cupom_de_teste_bate_com_a_regua_do_painel():
    """Mesma régua do ``_regua_numerada`` do painel (``lib/pos/print-test.ts``).

    Se divergirem, "o teste do painel sai diferente do teste do agente" vira um
    diagnóstico falso sobre a impressora.
    """
    from app.agent_actions import _regua_numerada

    assert _regua_numerada(20) == "....5...10...15...20"


# ── Impressoras ─────────────────────────────────────────────────────────────


def test_listar_impressoras_delega(actions, monkeypatch):
    monkeypatch.setattr(
        "app.agent_actions.list_printers", lambda: [PrinterInfo("HPRT", True)],
    )
    assert actions.listar_impressoras() == [PrinterInfo("HPRT", True)]


# ── Autostart ───────────────────────────────────────────────────────────────


def test_alternar_autostart_devolve_o_estado_real(actions, monkeypatch):
    """Best-effort: uma caixa marcada por engano faria o lojista crer que o
    agente sobe sozinho quando não sobe."""
    estado = {"ativo": False}
    monkeypatch.setattr("app.autostart.esta_ativo", lambda: estado["ativo"])
    monkeypatch.setattr("app.autostart.ativar", lambda: estado.update(ativo=True))
    monkeypatch.setattr("app.autostart.desativar", lambda: estado.update(ativo=False))

    assert actions.alternar_autostart() is True
    assert actions.alternar_autostart() is False


def test_alternar_autostart_que_falha_nao_marca_a_caixa(actions, monkeypatch):
    monkeypatch.setattr("app.autostart.esta_ativo", lambda: False)
    monkeypatch.setattr("app.autostart.ativar", lambda: False)

    assert actions.alternar_autostart() is False


# ── Origens autorizadas (2026-08-17, achado no 1º teste real no Windows) ────
# O agente só aceitava `http://localhost:3001`. Abrindo o painel pelo IP do
# servidor da loja, o navegador manda outra origem, o agente recusa e a tela
# diz "agente não encontrado" — sem lugar nenhum para corrigir.


def test_salvar_origens_persiste_e_normaliza(actions, arquivo):
    actions.salvar_origens(["  http://192.168.1.135:3001/  ", "", "http://localhost:3001"])

    assert actions.config.allowed_origins == [
        "http://192.168.1.135:3001", "http://localhost:3001",
    ]
    assert json.loads(arquivo.read_text())["allowed_origins"][0] == "http://192.168.1.135:3001"


def test_salvar_origens_descarta_duplicata(actions):
    actions.salvar_origens(["http://a:3001", "http://a:3001/", "http://b:3001"])
    assert actions.config.allowed_origins == ["http://a:3001", "http://b:3001"]


@pytest.mark.parametrize("ruim", ["192.168.1.135:3001", "localhost:3001", "ftp://x"])
def test_salvar_origens_recusa_endereco_sem_esquema(actions, ruim):
    """O navegador manda a origem COM http://; gravar sem seria bloqueio mudo."""
    with pytest.raises(ConfiguracaoInvalida, match="http"):
        actions.salvar_origens([ruim])


def test_lista_de_origens_e_alterada_no_lugar(actions):
    """O CORSMiddleware guarda a REFERÊNCIA da lista (starlette cors.py:66) e a
    consulta a cada requisição. Rebindar faria o botão "Autorizar" parecer
    funcionar sem funcionar até o próximo restart."""
    original = actions.config.allowed_origins
    actions.salvar_origens(["http://novo:3001"])

    assert actions.config.allowed_origins is original
    assert original == ["http://novo:3001"]


def test_origem_recusada_fica_registrada_para_a_tela_oferecer(actions):
    actions.registrar_origem_recusada("http://192.168.1.135:3001")
    assert actions.origens_recusadas() == ["http://192.168.1.135:3001"]


def test_origem_ja_autorizada_nao_vira_pedido(actions):
    actions.salvar_origens(["http://ok:3001"])
    actions.registrar_origem_recusada("http://ok:3001")
    assert actions.origens_recusadas() == []


def test_autorizar_tira_da_lista_de_pedidos(actions):
    """Senão a tela seguiria oferecendo autorizar algo que já está autorizado."""
    actions.registrar_origem_recusada("http://192.168.1.135:3001")
    actions.salvar_origens(["http://192.168.1.135:3001"])
    assert actions.origens_recusadas() == []


def test_pedidos_de_acesso_nao_crescem_sem_limite(actions):
    for n in range(20):
        actions.registrar_origem_recusada(f"http://host{n}:3001")
    assert len(actions.origens_recusadas()) == 5


# ── Testar conexão com impressora de rede (pedido do usuário) ───────────────


def test_testar_conexao_mede_impressora_que_responde(actions):
    """Servidor TCP real, como o resto dos testes de impressora já faz."""
    import socket as sock
    import threading

    servidor = sock.socket(sock.AF_INET, sock.SOCK_STREAM)
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    porta = servidor.getsockname()[1]
    threading.Thread(target=lambda: servidor.accept(), daemon=True).start()
    try:
        latencia = actions.testar_conexao(f"127.0.0.1:{porta}")
        assert latencia >= 0
    finally:
        servidor.close()


def test_testar_conexao_explica_porta_fechada(actions):
    """Mensagem precisa dizer o que fazer, não só "falhou"."""
    with pytest.raises(PrinterSendError, match="porta"):
        actions.testar_conexao("127.0.0.1:9")


def test_testar_conexao_recusa_impressora_do_spooler(actions):
    """Impressora instalada não tem IP — mandar o operador para o teste certo."""
    with pytest.raises(PrinterSendError, match="Testar impressão"):
        actions.testar_conexao("HPRT-TP80K")


def test_testar_conexao_sem_endereco(actions):
    with pytest.raises(ConfiguracaoInvalida):
        actions.testar_conexao("   ")


def test_testar_conexao_nao_imprime_nada(actions, monkeypatch):
    """Testar a rede não pode gastar papel — o operador testa quantas vezes precisar."""
    enviados = []
    monkeypatch.setattr("app.agent_actions.send_raw_bytes", lambda *a: enviados.append(a))
    with pytest.raises(PrinterSendError):
        actions.testar_conexao("127.0.0.1:9")
    assert enviados == []
