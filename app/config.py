"""Configuração local do agente — via ``os.getenv()`` (mesmo padrão do resto
do monorepo), com fallback pra um ``config.json`` ao lado do executável pra
quem for configurar sem editar variável de ambiente (o público-alvo é o
técnico que instala a impressora na loja, não um dev).

Nunca hardcoded — ``PRINTER_DEST``/``AGENT_TOKEN`` ausentes fazem o agente
subir mesmo assim (``/health`` funciona pra diagnóstico), mas ``/print``
recusa com mensagem clara em vez de falhar de forma confusa.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _default_config_dir() -> Path:
    """Pasta onde ``config.json`` mora por padrão.

    Rodando via ``python main.py``, é o diretório de trabalho atual (como
    sempre foi). Empacotado com PyInstaller (``sys.frozen``), o CWD depende
    de como o SO/atalho/serviço invoca o processo — imprevisível — então usa
    o diretório do **executável**, mesmo padrão de app PyInstaller pra
    recursos ao lado do binário. Sem isso, o agente empacotado ora não acha
    o `config.json` que o técnico editou, ora grava um novo em outro lugar
    silenciosamente a cada restart.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(".")


def _config_path() -> Path:
    # Lido a cada chamada (não cacheado em constante de módulo) — senão
    # ``GS_PRINT_AGENT_CONFIG`` só valeria se definida antes do primeiro
    # import de qualquer módulo que importe este arquivo.
    override = os.getenv("GS_PRINT_AGENT_CONFIG")
    if override:
        return Path(override)
    return _default_config_dir() / "config.json"


@dataclass
class AgentConfig:
    """Configuração do agente.

    Attributes:
        printer_dest: Destino da impressora — ``"192.168.1.50"``,
            ``"192.168.1.50:9100"`` (rede) ou nome de impressora do SO.
        chars_per_line: Colunas de texto que a impressora comporta por linha
            física — **precisa bater com o hardware real**, não é um valor
            estético. 48 = 80mm no calibre já usado pelo GS-PDV desktop; 32 é
            o equivalente pra 58mm. Uma linha mais larga que isso não gera
            erro — a própria impressora quebra a sobra pra uma segunda linha
            física, e como o texto é preenchido com espaços até a largura
            configurada (`center`/`ljust`), essa segunda linha sai quase
            toda em branco. **Foi exatamente esse descasamento que causou o
            "muito papel em branco" relatado** com o default 48 fixo contra
            uma impressora mais estreita.
        token: Segredo compartilhado que o dashboard envia em
            ``Authorization: Bearer <token>``. Em branco = ``/print`` sempre
            recusa (falha fechada — nunca aceitar print sem token configurado).
        allowed_origins: Origens do browser autorizadas a chamar ``/print``.
        port: Porta HTTP local do agente.
    """

    printer_dest: str = ""
    chars_per_line: int = 48
    token: str = ""
    allowed_origins: list[str] = field(default_factory=lambda: ["http://localhost:3001"])
    port: int = 9123


def _read_config_file() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def load_config() -> AgentConfig:
    """Carrega a configuração: env var vence, senão ``config.json``, senão default."""
    file_data = _read_config_file()

    origins_env = os.getenv("ALLOWED_ORIGINS")
    if origins_env:
        allowed_origins = [o.strip() for o in origins_env.split(",") if o.strip()]
    else:
        allowed_origins = file_data.get("allowed_origins") or ["http://localhost:3001"]

    return AgentConfig(
        printer_dest=os.getenv("PRINTER_DEST", file_data.get("printer_dest", "")),
        chars_per_line=int(os.getenv("CHARS_PER_LINE", file_data.get("chars_per_line", 48))),
        token=os.getenv("AGENT_TOKEN", file_data.get("token", "")),
        allowed_origins=allowed_origins,
        port=int(os.getenv("AGENT_PORT", file_data.get("port", 9123))),
    )


def save_printer_config(config: AgentConfig, printer_dest: str, chars_per_line: int) -> None:
    """Grava ``printer_dest``/``chars_per_line`` no ``config.json``, sobrevivendo
    a um restart.

    Só esses dois campos são persistidos por aqui de propósito — ``token``/
    ``allowed_origins``/``port`` continuam só por env var ou edição manual do
    arquivo. Configurar a impressora (destino e largura) é uma operação de
    rotina (o técnico troca a impressora, o papel muda); girar o token é uma
    operação sensível que não deveria virar um botão na tela do PDV.
    """
    config.printer_dest = printer_dest
    config.chars_per_line = chars_per_line
    data = _read_config_file()
    data["printer_dest"] = printer_dest
    data["chars_per_line"] = chars_per_line
    _config_path().write_text(json.dumps(data, indent=2), encoding="utf-8")
