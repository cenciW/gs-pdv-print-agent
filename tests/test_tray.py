"""Testes da bandeja — sem abrir janela nenhuma.

A bandeja é conforto; o serviço de impressão é o produto. Os testes aqui
protegem exatamente essa hierarquia: nada relacionado ao ícone pode derrubar o
agente, e o rótulo precisa dizer a verdade sobre o estado.
"""

from __future__ import annotations

from app.config import AgentConfig
from app.tray import TrayIcon, _desenhar_icone, _titulo_seguro


def _icone(**kwargs) -> TrayIcon:
    config = AgentConfig(**kwargs)
    return TrayIcon(
        config=config,
        ao_abrir_configuracao=lambda: None,
        ao_testar_impressao=lambda: None,
        ao_reiniciar=lambda: None,
        ao_sair=lambda: None,
    )


# ── Título compatível com o backend X11 ──────────────────────────────────────
# Regressão de um bug REAL (2026-08-17): o backend X11 do pystray codifica o
# título em latin-1 e levanta UnicodeEncodeError em qualquer caractere fora
# dessa faixa. Um travessão no título derrubou o agente inteiro — com o
# servidor HTTP já no ar.

def test_titulo_sem_travessao_sobrevive_ao_backend_x11():
    titulo = _titulo_seguro("GS PDV — pronto")
    titulo.encode("latin-1")  # não pode levantar
    assert "—" not in titulo
    assert "GS PDV - pronto" == titulo


def test_titulo_higieniza_aspas_e_reticencias_tipograficas():
    titulo = _titulo_seguro("Configurar… “impressora”")
    titulo.encode("latin-1")
    assert titulo == 'Configurar... "impressora"'


def test_titulo_com_caractere_imprevisto_nao_levanta():
    """Rede de segurança: emoji ou qualquer coisa fora do mapa de substituições
    vira "?" em vez de derrubar o agente."""
    titulo = _titulo_seguro("Pronto 🖨 agora")
    titulo.encode("latin-1")


def test_acentos_do_portugues_sobrevivem():
    """latin-1 cobre acento — não faz sentido descaracterizar "impressão"."""
    assert _titulo_seguro("impressão") == "impressão"


# ── Rótulo de status ─────────────────────────────────────────────────────────
# É a resposta para "está funcionando?" sem abrir nada. Precisa apontar o que
# falta, não só dizer que algo está errado.

def test_status_aponta_token_ausente_como_o_problema_principal():
    """Sem token, /print recusa tudo — é o bloqueio mais grave, vem primeiro."""
    assert "Sem token" in _icone(token="", printer_dest="192.168.1.50")._texto_status()


def test_status_aponta_impressora_ausente():
    assert "Sem impressora" in _icone(token="abc", printer_dest="")._texto_status()


def test_status_pronto_mostra_impressora_e_largura():
    """A largura aparece porque errá-la é a causa clássica de papel em branco
    sobrando — vê-la no menu evita abrir o painel para conferir."""
    texto = _icone(token="abc", printer_dest="HPRT TP80K", chars_per_line=32)._texto_status()
    assert "HPRT TP80K" in texto
    assert "32 col" in texto


def test_pronto_exige_token_e_impressora():
    assert _icone(token="abc", printer_dest="X")._pronto() is True
    assert _icone(token="", printer_dest="X")._pronto() is False
    assert _icone(token="abc", printer_dest="")._pronto() is False


# ── Ícone ────────────────────────────────────────────────────────────────────

def test_icone_muda_de_cor_conforme_o_estado():
    """Verde quando pronto, cinza quando falta configurar — a cor é a resposta
    de relance, antes de abrir o menu."""
    pronto = _desenhar_icone(True)
    pendente = _desenhar_icone(False)
    assert pronto.size == pendente.size == (64, 64)
    assert list(pronto.getdata()) != list(pendente.getdata())


def test_atualizar_sem_icone_criado_nao_levanta():
    """`atualizar()` pode ser chamado pela janela antes de `run()` — e no modo
    headless o ícone nunca existe."""
    _icone(token="abc", printer_dest="X").atualizar()
