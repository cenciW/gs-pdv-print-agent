"""gs-pdv-print-agent — serviço local que fala ESC/POS com a impressora
térmica da loja (rede porta 9100, Windows ``win32print`` ou Linux/CUPS).

Existe porque impressoras térmicas de rede não falam com ``window.print()``/
driver de SO — só bytes ESC/POS crus por socket. O dashboard (``gs-menu-
dashboard``, rodando no browser do operador) fala HTTP com este agente em
``127.0.0.1``/IP da LAN; se o agente não responder a tempo, o dashboard cai
pro fallback de ``window.print()`` (ver Fase 3 do PDV web, `linked-bubbling-
canyon.md` § 3).

Rodar localmente:
    AGENT_TOKEN=segredo-da-loja PRINTER_DEST=192.168.1.50 python main.py

Ou empacotado como executável único (PyInstaller — ver README.md), do jeito
que o próprio GS-PDV desktop já é distribuído hoje.
"""

from __future__ import annotations

import logging
import os
import sys
import threading

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.agent_actions import AgentActions, ConfiguracaoInvalida
from app.auth import require_auth
from app.config import load_config, save_token
from app.escpos import wrap_escpos
from app.logging_setup import setup_logging
from app.printer_client import PrinterSendError, send_raw_bytes

_arquivo_de_log = setup_logging()
logger = logging.getLogger("gs-pdv-print-agent")

app = FastAPI(title="GS-PDV Print Agent")
app.state.config = load_config()

# Uma única implementação de cada ação, compartilhada pelas rotas HTTP, pela
# janela e pela bandeja (`app/agent_actions.py`). Antes disso a mesma operação
# estava escrita em três lugares, e "duas portas para a mesma configuração"
# virava "duas verdades": salvar pelo painel não chegava na janela aberta.
app.state.actions = AgentActions(app.state.config, servidor_no_ar=lambda: True)

# Registra quem tentou usar o agente sem estar autorizado, para a janela poder
# oferecer "autorizar" em vez de exigir que alguém saiba o IP do servidor.
#
# Fica DENTRO do CORS (adicionado antes, portanto mais interno) de propósito: o
# CORSMiddleware precisa ser o mais externo para que erro não tratado saia com
# cabeçalho de CORS — regra já registrada no CLAUDE.md. Isso basta porque a
# sonda que o painel faz primeiro é `GET /health`, sem cabeçalho custom e
# portanto **sem preflight**: a requisição chega aqui normalmente, e é só a
# resposta que o navegador descarta por falta do cabeçalho.
@app.middleware("http")
async def _registrar_origem(request, call_next):
    origem = request.headers.get("origin")
    if origem:
        app.state.actions.registrar_origem_recusada(origem)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=app.state.config.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    max_age=600,
)


class PrintIn(BaseModel):
    text: str


class PrintOut(BaseModel):
    ok: bool


class HealthOut(BaseModel):
    status: str
    printer_configured: bool
    printer_dest: str = ""
    chars_per_line: int = 48


class PrinterConfigIn(BaseModel):
    printer_dest: str
    chars_per_line: int = 48


class AgentActionOut(BaseModel):
    ok: bool


class PrintersOut(BaseModel):
    printers: list[dict]


def _health_out() -> HealthOut:
    config = app.state.config
    return HealthOut(
        status="ok", printer_configured=bool(config.printer_dest),
        printer_dest=config.printer_dest, chars_per_line=config.chars_per_line,
    )


@app.get("/health", response_model=HealthOut)
def health():
    """Sem auth de propósito — é só o probe de liveness (~1.5s) que o
    dashboard usa pra decidir entre agente e fallback ``window.print()``.
    ``printer_dest``/``chars_per_line`` não são segredo — só o token e o
    corpo do cupom exigem auth; expor isso permite a tela de Configurações
    de Impressão do dashboard mostrar o valor atual sem precisar do token."""
    return _health_out()


@app.put("/config/printer", response_model=HealthOut, dependencies=[Depends(require_auth)])
def set_printer(body: PrinterConfigIn):
    """Configura destino e largura da impressora remotamente (dashboard → agente).

    ``chars_per_line`` precisa bater com o hardware real (48 = 80mm, 32 =
    58mm, no calibre já usado pelo GS-PDV desktop) — errar isso faz cada
    linha do cupom (preenchida com espaços até essa largura) estourar pra
    uma segunda linha física quase toda em branco. Só esses dois campos são
    editáveis por aqui — ver ``save_printer_config`` pro porquê de
    token/origens ficarem de fora.
    """
    try:
        # Passa pelo mesmo núcleo que a janela usa — inclusive o aviso aos
        # observadores, que é o que faz a janela aberta refletir na hora uma
        # mudança feita pelo painel, em vez de continuar mostrando o valor
        # antigo até alguém reabrir.
        app.state.actions.salvar_impressora(body.printer_dest, body.chars_per_line)
    except ConfiguracaoInvalida as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _health_out()


@app.get("/printers", response_model=PrintersOut, dependencies=[Depends(require_auth)])
def list_system_printers():
    """Impressoras instaladas neste computador, para o painel oferecer a escolha.

    **Com autenticação**, diferente de ``/health``: nome de impressora é
    informação da máquina da loja, e o probe de liveness não precisa disso.

    Lista vazia significa "não consegui descobrir" (máquina sem spooler/CUPS,
    consulta falhou) — nunca "não há impressora". O painel cai no campo de texto
    livre, que também é o caminho da impressora de rede, que não aparece em
    spooler nenhum.
    """
    return PrintersOut(printers=[p.to_dict() for p in app.state.actions.listar_impressoras()])


@app.post("/print", response_model=PrintOut, dependencies=[Depends(require_auth)])
def print_receipt(body: PrintIn):
    config = app.state.config
    if not config.printer_dest:
        raise HTTPException(status_code=503, detail="Nenhuma impressora configurada neste agente (PRINTER_DEST).")

    payload = wrap_escpos(body.text)
    try:
        send_raw_bytes(payload, config.printer_dest)
    except PrinterSendError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    logger.info("Cupom impresso em %s (%d bytes)", config.printer_dest, len(payload))
    return PrintOut(ok=True)


# ── Controle do processo (2026-08-13) ──────────────────────────────────────
# Chamado pela nova página "Impressão" do dashboard. O agente não se
# autogerencia hoje (Windows: só atalho na pasta Startup, sem serviço real;
# Linux: systemd com Restart=on-failure, mas só reage a crash) — "reiniciar"
# pelo dashboard só funciona de verdade se o próprio processo se re-executa.
# `os.execv` funciona tanto via `python main.py` quanto empacotado com
# PyInstaller (`sys.executable` vira o próprio binário quando `sys.frozen`,
# mesmo padrão já usado em `app/config.py::_default_config_dir`).
#
# Sempre responder ANTES de agir — a ação roda numa thread separada com um
# atraso curto, senão o cliente HTTP nunca recebe a confirmação (o processo
# já teria saído/re-executado antes do response terminar de ser escrito). Esse
# atraso vive em `AgentActions`, junto do resto: o menu da bandeja precisa
# exatamente do mesmo comportamento.


@app.post("/agent/stop", response_model=AgentActionOut, dependencies=[Depends(require_auth)])
def stop_agent():
    app.state.actions.encerrar()
    return AgentActionOut(ok=True)


@app.post("/agent/restart", response_model=AgentActionOut, dependencies=[Depends(require_auth)])
def restart_agent():
    app.state.actions.reiniciar()
    return AgentActionOut(ok=True)


# ── Primeira execução: pede o token no console (2026-08-14) ────────────────
# Antes disso a única forma de configurar o token era editar config.json ou
# variável de ambiente na mão — pedido do usuário: "a primeira tela deveria
# exigir a chave". Só pergunta quando dá pra perguntar de verdade
# (`isatty()`): alguém sentado no console, seja `python main.py` ou o `.exe`
# aberto por clique duplo (janela de console de verdade nos dois casos). Sem
# esse guard, rodando como serviço/systemd (stdout indo pro journal, sem
# terminal) o `input()` travaria o boot pra sempre esperando um humano que
# nunca aparece — mantém o comportamento de hoje (loga aviso, seguir sem
# travar) pra esse caso.
def _prompt_for_token_if_missing(config) -> None:
    if config.token or not sys.stdin.isatty():
        return
    print()  # noqa: T201 — é o prompt de console, não log
    print("=" * 60)
    print("Nenhum token configurado ainda.")
    print("Copie o token na tela Impressão do painel (Config. > Impressão)")
    print("e cole aqui.")
    print("=" * 60)
    try:
        pasted = input("Token: ").strip()
    except (EOFError, KeyboardInterrupt):
        pasted = ""
    if pasted:
        save_token(config, pasted)
        print("Token salvo — não vai ser pedido de novo neste computador.\n")
    else:
        print("Nenhum token informado — a impressão vai ser recusada até configurar.\n")



# ── Arranque ───────────────────────────────────────────────────────────────
# **A janela é dona da thread principal.** Foi o contrário até a v0.2.0, e foi
# a origem dos dois defeitos que reprovaram aquela release:
#
# * Windows — o pystray despacha o callback do menu de dentro da bomba de
#   mensagens; abrir a janela ali congelava a bandeja (relato do usuário: "a
#   busca achou algumas, mas ficou toda travada a aplicação").
# * Linux/X11 — o pystray nem suporta menu (`_xorg.py: HAS_MENU = False`), então
#   o menu inteiro era descartado em silêncio e o ícone não fazia nada.
#
# Agora o Tk fica com o laço principal, o uvicorn e a bandeja rodam em threads,
# e todo item de menu só ENFILEIRA trabalho para o laço da janela.
#
# Três modos:
#
# **Janela** (padrão) — duplo-clique no executável: janela de configuração e,
# quando o sistema suporta, ícone na área de notificação.
#
# **Headless** (`--headless` ou `GS_AGENT_GUI=0`) — o que systemd/serviço usa:
# só o uvicorn, sem janela e sem bandeja.
#
# **Queda automática para headless** — sem Tk ou sem display, o agente sobe
# como serviço e loga. O agente SEMPRE imprime, com ou sem interface: quem
# manda é o serviço.


def _servir(cfg) -> None:
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=cfg.port, log_config=None)


def _com_interface() -> bool:
    if "--headless" in sys.argv:
        return False
    return os.getenv("GS_AGENT_GUI", "1") != "0"


def _resolver_token_no_console(cfg) -> None:
    """Pede o token no console quando há console de verdade.

    Com janela, o token é só mais um campo dela — não há motivo para um prompt
    separado. Este caminho existe para `python main.py` num terminal e para o
    modo headless com alguém sentado no console.
    """
    if cfg.token or sys.stdin is None or not sys.stdin.isatty():
        return
    _prompt_for_token_if_missing(cfg)


def _avisar_falha_fatal(mensagem: str) -> None:
    """Último recurso quando não há console nem janela para mostrar o erro.

    Num `.exe` `--windowed`, uma falha no arranque da interface deixaria o
    operador vendo **nada** — foi exatamente o ".exe não abre nada" que ficou
    sem causa raiz na SESSAO §21. Uma caixa do próprio Windows (ctypes, sem
    dependência nova) pelo menos diz onde está o log.
    """
    logger.error("%s", mensagem)
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, mensagem, "GS PDV - Agente de Impressao", 0x10)
    except Exception:  # noqa: BLE001 — é o último recurso; não pode levantar
        pass


def _iniciar_com_interface(cfg) -> None:
    """Sobe servidor + janela (+ bandeja, se der) e entrega o laço à janela."""
    from app.ui import tray, window

    servidor = threading.Thread(target=lambda: _servir(cfg), name="uvicorn", daemon=True)
    servidor.start()
    app.state.actions = AgentActions(cfg, servidor_no_ar=servidor.is_alive)

    janela = window.AgentWindow(app.state.actions)
    bandeja = None

    if tray.disponivel():
        bandeja = tray.TrayAccessory(
            app.state.actions, agendar=janela.agendar, ao_mostrar_janela=janela.mostrar,
        )
        if not bandeja.iniciar():
            bandeja = None
        else:
            app.state.actions.observar(lambda: janela.agendar(bandeja.atualizar))

    # Esconder para a bandeja só é oferecido onde existe menu para trazer a
    # janela de volta. No Linux/X11 o pystray não suporta menu, e esconder
    # deixaria a configuração inalcançável — lá, fechar a janela pergunta se é
    # para encerrar o agente.
    com_bandeja = bandeja is not None and tray.suporta_menu()
    if com_bandeja:
        janela.permitir_esconder_na_bandeja(bandeja.atualizar)

    # Já configurado + bandeja com menu = sobe silencioso, só o ícone (decisão
    # do usuário em 2026-08-17). Faltando token ou impressora, a janela abre:
    # é a primeira instalação, e é onde ela precisa aparecer.
    pronto = app.state.actions.status().pronto
    janela.executar(iniciar_escondida=pronto and com_bandeja)

    if bandeja is not None:
        bandeja.parar()


def main() -> None:
    cfg = app.state.config
    com_interface = _com_interface()

    if not com_interface:
        _resolver_token_no_console(cfg)

    logger.info(
        "Subindo em 0.0.0.0:%d — impressora=%s (%d colunas) token=%s origens=%s modo=%s log=%s",
        cfg.port, cfg.printer_dest or "(não configurada)", cfg.chars_per_line,
        "configurado" if cfg.token else "AUSENTE (print vai recusar tudo)",
        cfg.allowed_origins, "janela" if com_interface else "headless",
        _arquivo_de_log or "(só console)",
    )

    if not com_interface:
        _servir(cfg)
        return

    from app.ui import window

    if not window.disponivel():
        logger.warning("Sem interface gráfica — subindo apenas como serviço.")
        _resolver_token_no_console(cfg)
        _servir(cfg)
        return

    try:
        _iniciar_com_interface(cfg)
    except Exception:  # noqa: BLE001 — interface quebrada não pode parar a impressão
        logger.exception("Falha ao subir a interface — seguindo apenas como serviço.")
        _avisar_falha_fatal(
            "Nao foi possivel abrir a janela do agente.\n\n"
            "O agente continua imprimindo em segundo plano.\n"
            f"Detalhes no log: {_arquivo_de_log or '(sem arquivo de log)'}",
        )
        _servir(cfg)


if __name__ == "__main__":
    main()
