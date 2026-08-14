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
import time

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth import require_auth
from app.config import load_config, save_printer_config, save_token
from app.escpos import wrap_escpos
from app.printer_client import PrinterSendError, send_raw_bytes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("gs-pdv-print-agent")

app = FastAPI(title="GS-PDV Print Agent")
app.state.config = load_config()

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
    if body.chars_per_line < 20 or body.chars_per_line > 64:
        raise HTTPException(status_code=400, detail="chars_per_line deve estar entre 20 e 64")
    save_printer_config(app.state.config, body.printer_dest.strip(), body.chars_per_line)
    logger.info(
        "Impressora reconfigurada: %s (%d colunas)",
        app.state.config.printer_dest, app.state.config.chars_per_line,
    )
    return _health_out()


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
# já teria saído/re-executado antes do response terminar de ser escrito).
def _delayed_exit() -> None:
    time.sleep(0.3)
    os._exit(0)


def _delayed_restart() -> None:
    time.sleep(0.3)
    os.execv(sys.executable, [sys.executable] + sys.argv)


@app.post("/agent/stop", response_model=AgentActionOut, dependencies=[Depends(require_auth)])
def stop_agent():
    logger.info("Parando o agente a pedido do dashboard.")
    threading.Thread(target=_delayed_exit, daemon=True).start()
    return AgentActionOut(ok=True)


@app.post("/agent/restart", response_model=AgentActionOut, dependencies=[Depends(require_auth)])
def restart_agent():
    logger.info("Reiniciando o agente a pedido do dashboard.")
    threading.Thread(target=_delayed_restart, daemon=True).start()
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
    print()
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


if __name__ == "__main__":
    import uvicorn

    cfg = app.state.config
    _prompt_for_token_if_missing(cfg)
    logger.info(
        "Subindo em 0.0.0.0:%d — impressora=%s (%d colunas) token=%s origens=%s",
        cfg.port, cfg.printer_dest or "(não configurada)", cfg.chars_per_line,
        "configurado" if cfg.token else "AUSENTE (print vai recusar tudo)",
        cfg.allowed_origins,
    )
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)
