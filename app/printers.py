"""Descoberta das impressoras instaladas no computador da loja.

O agente já sabia **enviar** para o spooler do Windows (``win32print``) e para o
CUPS (``lp -o raw``) — ver ``printer_client.py``. O que faltava era **enxergar**
o que está instalado: sem isso, configurar a impressora significava o operador
digitar o nome exato, à mão, sem saber como o sistema o escreveu ("HPRT TP80K"
ou "HPRT_TP80K"? com ou sem acento?). Errar uma letra dá um erro de impressão
que não explica nada.

Toda falha aqui devolve lista vazia e loga: é uma comodidade da tela de
configuração, e nunca pode derrubar o agente nem impedir a impressão — o campo
de texto livre continua existindo como caminho alternativo (impressora de rede
por IP, por exemplo, não aparece em spooler nenhum).
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: Tempo máximo esperando o CUPS responder. Um `lpstat` travado (servidor de
#: impressão fora do ar) não pode segurar a tela de configuração.
_LPSTAT_TIMEOUT_S = 4.0


@dataclass(frozen=True)
class PrinterInfo:
    """Uma impressora que o sistema operacional conhece.

    Attributes:
        name: Nome exato como o spooler/CUPS espera receber — é o que vai para
            ``printer_dest``.
        is_default: Se é a impressora padrão do sistema. A tela usa para
            pré-selecionar a escolha mais provável.
    """

    name: str
    is_default: bool = False

    def to_dict(self) -> dict:
        return {"name": self.name, "is_default": self.is_default}


def list_printers() -> list[PrinterInfo]:
    """Impressoras instaladas, ordenadas com a padrão primeiro.

    Returns:
        Lista possivelmente vazia — máquina sem spooler, sem CUPS, ou com
        qualquer falha na consulta. Vazio significa "não consegui descobrir",
        nunca "não existe impressora": a tela cai no campo de texto livre.
    """
    try:
        encontradas = _listar_windows() if sys.platform == "win32" else _listar_cups()
    except Exception as exc:  # noqa: BLE001 — comodidade opcional, nunca derruba o agente
        logger.warning("Não foi possível listar as impressoras do sistema: %s", exc)
        return []

    # Padrão primeiro, resto em ordem alfabética — a lista é lida por gente.
    return sorted(encontradas, key=lambda p: (not p.is_default, p.name.lower()))


def _listar_windows() -> list[PrinterInfo]:
    """Spooler do Windows: impressoras locais **e** conexões de rede mapeadas."""
    import win32print  # type: ignore[import-not-found]

    padrao = ""
    try:
        padrao = win32print.GetDefaultPrinter()
    except Exception:  # noqa: BLE001 — máquina sem impressora padrão definida
        pass

    nivel = 2
    flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
    return [
        PrinterInfo(name=info["pPrinterName"], is_default=(info["pPrinterName"] == padrao))
        for info in win32print.EnumPrinters(flags, None, nivel)
    ]


def _listar_cups() -> list[PrinterInfo]:
    """CUPS (Linux/macOS) via ``lpstat``.

    ``lpstat -p`` lista as filas, ``lpstat -d`` diz qual é a padrão. Os dois
    saem em texto pensado para gente, então o parsing é deliberadamente frouxo:
    pega o segundo campo da linha e ignora o resto, que muda conforme o idioma
    do sistema. Máquina sem CUPS instalado devolve vazio (o binário nem existe).
    """
    filas = _executar(["lpstat", "-p"])
    padrao = _padrao_cups()

    impressoras: list[PrinterInfo] = []
    for linha in filas.splitlines():
        partes = linha.split()
        # Formato: "printer NOME is idle. enabled since ..." — em português,
        # "impressora NOME está ociosa...". O nome é sempre o segundo campo.
        if len(partes) >= 2 and partes[0].lower() in {"printer", "impressora"}:
            nome = partes[1]
            impressoras.append(PrinterInfo(name=nome, is_default=(nome == padrao)))
    return impressoras


def _padrao_cups() -> str:
    """Nome da impressora padrão, ou string vazia se não houver."""
    saida = _executar(["lpstat", "-d"])
    # "system default destination: NOME" / "no system default destination"
    if ":" not in saida:
        return ""
    return saida.split(":", 1)[1].strip()


def _executar(comando: list[str]) -> str:
    """Roda um comando de consulta, devolvendo stdout (vazio em qualquer falha).

    ``check=False``: `lpstat` sai com código diferente de zero em situações
    normais (nenhuma impressora configurada, por exemplo), e isso não é erro.
    """
    try:
        resultado = subprocess.run(
            comando, capture_output=True, text=True, timeout=_LPSTAT_TIMEOUT_S, check=False,
        )
        return resultado.stdout or ""
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        logger.debug("Comando %s indisponível: %s", comando[0], exc)
        return ""
