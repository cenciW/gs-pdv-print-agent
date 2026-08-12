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

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.auth import require_auth
from app.config import load_config, save_printer_config
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


if __name__ == "__main__":
    import uvicorn

    cfg = app.state.config
    logger.info(
        "Subindo em 0.0.0.0:%d — impressora=%s (%d colunas) token=%s origens=%s",
        cfg.port, cfg.printer_dest or "(não configurada)", cfg.chars_per_line,
        "configurado" if cfg.token else "AUSENTE (print vai recusar tudo)",
        cfg.allowed_origins,
    )
    uvicorn.run(app, host="0.0.0.0", port=cfg.port)
