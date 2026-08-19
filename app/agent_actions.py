"""Ações do agente — o núcleo que as três interfaces compartilham.

Antes de 2026-08-17 a mesma operação estava escrita mais de uma vez: a janela
gravava a configuração de um jeito, as rotas HTTP de outro, a bandeja falava
com ``autostart`` direto e o cupom de teste existia em duas versões (aqui e no
``lib/pos/print-test.ts`` do painel). Toda funcionalidade nova precisava ser
lembrada em três lugares — e "lembrar de copiar" é exatamente o que produz
janela e painel discordando sobre qual impressora está configurada.

Este módulo é a resposta: **uma** implementação de cada ação, sem tkinter, sem
pystray e sem FastAPI. Quem desenha tela chama daqui; quem serve HTTP chama
daqui. Por não importar nenhuma dessas três coisas, é testável direto, sem
display e sem subir servidor.

A dependência aponta só para dentro (``config``, ``printers``,
``printer_client``, ``escpos``, ``autostart``), a mesma regra de camadas do
resto do monorepo.
"""

from __future__ import annotations

import logging
import os
import sys
import textwrap
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from app import autostart, rede
from app.config import (
    AgentConfig, config_path, log_path, origem_autorizada, save_origins,
    save_printer_config, save_token,
)
from app.escpos import wrap_escpos
from app.printer_client import send_raw_bytes, test_connection
from app.printers import PrinterInfo, list_printers

logger = logging.getLogger(__name__)

#: Larguras oferecidas na tela — as duas bitolas do parque de impressoras.
#:
#: O valor precisa bater com o hardware: errar aqui é a causa clássica do "muito
#: papel em branco". Cada linha do cupom é preenchida com espaços até a largura
#: configurada; se isso passa do que a impressora comporta, a sobra estoura para
#: uma segunda linha física quase toda vazia.
LARGURAS = ((48, "80 mm (48 colunas)"), (32, "58 mm (32 colunas)"))

#: Faixa aceita para largura — a mesma que ``PUT /config/printer`` já valida.
LARGURA_MIN, LARGURA_MAX = 20, 64

#: Atraso antes de sair/reexecutar, para a resposta HTTP terminar de ser
#: escrita antes de o processo morrer. Sem isso, quem pediu "reiniciar" pelo
#: painel nunca recebe a confirmação.
_ATRASO_ENCERRAMENTO_S = 0.3

#: Quantas origens recusadas guardar para oferecer na tela. Poucas de propósito:
#: é uma lista para uma pessoa ler e decidir, não um registro de auditoria.
_MAXIMO_ORIGENS_DETECTADAS = 5


class ConfiguracaoInvalida(ValueError):
    """Entrada recusada, com mensagem já pronta para aparecer na tela."""


@dataclass(frozen=True)
class StatusAgente:
    """Retrato do agente num instante — o que a tela e o menu exibem.

    Attributes:
        pronto: Se uma impressão feita agora tem chance de dar certo.
        motivo: Por que não está pronto. Vazio quando ``pronto``.
        printer_dest: Destino configurado (nome do spooler ou ``ip[:porta]``).
        chars_per_line: Largura configurada, em colunas.
        porta: Porta HTTP local.
        token_configurado: Sem token, ``/print`` recusa tudo (falha fechada).
        servidor_no_ar: Se a thread do uvicorn está viva.
        arquivo_de_config: Onde o ``config.json`` foi lido/gravado.
        arquivo_de_log: Onde o log está sendo escrito, se estiver.
    """

    pronto: bool
    motivo: str
    printer_dest: str
    chars_per_line: int
    porta: int
    token_configurado: bool
    servidor_no_ar: bool
    arquivo_de_config: Path
    arquivo_de_log: Optional[Path]

    def resumo(self) -> str:
        """Uma linha para o título da bandeja e a barra de status da janela."""
        if not self.pronto:
            return self.motivo
        return f"Pronto — {self.printer_dest} ({self.chars_per_line} col)"


class AgentActions:
    """Operações do agente, sem nenhuma dependência de interface.

    Args:
        config: Configuração viva — o mesmo objeto que as rotas HTTP mutam.
        servidor_no_ar: Como perguntar se a thread do servidor segue viva.
            Injetado em vez de importado para este módulo não depender do
            arranque (e para o teste não precisar subir uvicorn).
    """

    def __init__(
        self,
        config: AgentConfig,
        servidor_no_ar: Callable[[], bool] = lambda: True,
    ) -> None:
        self._config = config
        self._servidor_no_ar = servidor_no_ar
        self._observadores: list[Callable[[], None]] = []
        # Origens que tentaram usar este agente e foram recusadas. É o que
        # permite a janela perguntar "um painel em http://192.168.1.135:3001
        # tentou imprimir aqui — autorizar?" em vez de exigir que o lojista
        # saiba o IP do servidor de cor. Quem autoriza continua sendo a pessoa.
        self._origens_recusadas: list[str] = []

    @property
    def config(self) -> AgentConfig:
        return self._config

    # ── Observador ───────────────────────────────────────────────────────────
    # A configuração tem DUAS portas — a janela do agente e o painel web
    # (`PUT /config/printer`). Sem aviso, a janela aberta continuaria mostrando
    # o valor antigo depois de alguém salvar pelo painel, e as duas portas
    # viravam duas verdades. Quem desenha tela se inscreve aqui.

    def observar(self, callback: Callable[[], None]) -> Callable[[], None]:
        """Registra quem quer saber de mudanças. Devolve como cancelar."""
        self._observadores.append(callback)
        return lambda: self._observadores.remove(callback)

    def notificar(self) -> None:
        """Avisa os inscritos. Falha de um observador nunca derruba a ação."""
        for callback in list(self._observadores):
            try:
                callback()
            except Exception as exc:  # noqa: BLE001 — tela quebrada não desfaz um save
                logger.warning("Observador de configuração falhou: %s", exc)

    # ── Consulta ─────────────────────────────────────────────────────────────

    def status(self) -> StatusAgente:
        cfg = self._config
        if not cfg.token:
            motivo = "Sem token — a impressão vai ser recusada"
        elif not cfg.printer_dest:
            motivo = "Sem impressora configurada"
        else:
            motivo = ""
        return StatusAgente(
            pronto=not motivo,
            motivo=motivo,
            printer_dest=cfg.printer_dest,
            chars_per_line=cfg.chars_per_line,
            porta=cfg.port,
            token_configurado=bool(cfg.token),
            servidor_no_ar=self._servidor_no_ar(),
            arquivo_de_config=config_path(),
            arquivo_de_log=log_path() if log_path().exists() else None,
        )

    def listar_impressoras(self) -> list[PrinterInfo]:
        """Impressoras que o sistema conhece. Vazio = não consegui descobrir."""
        return list_printers()

    # ── Gravação ─────────────────────────────────────────────────────────────

    def salvar_impressora(self, destino: str, chars_per_line: int) -> None:
        """Grava destino e largura, validando antes de tocar no disco.

        Raises:
            ConfiguracaoInvalida: Largura fora da faixa que o hardware aceita.
        """
        if not LARGURA_MIN <= chars_per_line <= LARGURA_MAX:
            raise ConfiguracaoInvalida(
                f"A largura precisa estar entre {LARGURA_MIN} e {LARGURA_MAX} colunas.",
            )
        save_printer_config(self._config, destino.strip(), chars_per_line)
        logger.info(
            "Impressora configurada: %s (%d colunas)",
            self._config.printer_dest or "(nenhuma)", self._config.chars_per_line,
        )
        self.notificar()

    def salvar_token(self, token: str) -> None:
        """Grava o token. Vazio é aceito de propósito: é como se apaga um token
        errado, e o estado "sem token" já é tratado em todo lugar (falha
        fechada — ``/print`` recusa tudo)."""
        save_token(self._config, token.strip())
        logger.info("Token %s pela janela do agente.", "salvo" if self._config.token else "removido")
        self.notificar()

    # ── Origens autorizadas ──────────────────────────────────────────────────

    def salvar_origens(self, origens: list[str]) -> None:
        """Grava a lista de origens, normalizada.

        Raises:
            ConfiguracaoInvalida: Alguma entrada não parece um endereço de
                painel. Recusar cedo é melhor que gravar ``192.168.1.135:3001``
                sem esquema e o operador ficar sem entender por que continua
                bloqueado — o navegador manda a origem **com** ``http://``.
        """
        limpas: list[str] = []
        for bruta in origens:
            origem = bruta.strip().rstrip("/")
            if not origem:
                continue
            if not origem.startswith(("http://", "https://")):
                raise ConfiguracaoInvalida(
                    f"'{origem}' precisa começar com http:// ou https:// — é assim "
                    "que o navegador identifica o painel.",
                )
            if origem not in limpas:
                limpas.append(origem)

        save_origins(self._config, limpas)
        logger.info("Origens autorizadas: %s", limpas)
        # Sai da lista de "tentaram e foram recusadas" o que acabou de ser
        # autorizado, senão a janela seguiria oferecendo autorizar de novo.
        self._origens_recusadas = [o for o in self._origens_recusadas if o not in limpas]
        self.notificar()

    def registrar_origem_recusada(self, origem: str) -> None:
        """Anota um painel que tentou usar este agente sem estar autorizado."""
        # MESMO critério do CORS (`origem_autorizada`), não uma segunda cópia:
        # com duas checagens, a janela oferecia "autorizar" um endereço que já
        # funcionava — desde que a rede local passou a ser aceita por padrão,
        # todo celular do salão cairia nessa lista sem motivo.
        if not origem or origem_autorizada(self._config, origem):
            return
        if origem in self._origens_recusadas:
            return
        self._origens_recusadas.append(origem)
        del self._origens_recusadas[:-_MAXIMO_ORIGENS_DETECTADAS]
        logger.info("Painel não autorizado tentou usar o agente: %s", origem)
        self.notificar()

    def origens_recusadas(self) -> list[str]:
        return list(self._origens_recusadas)

    def origem_sugerida(self) -> str:
        """Melhor palpite de endereço do painel **nesta** máquina.

        Serve para o caso em que o painel roda no mesmo computador do agente.
        Quando o painel está noutra máquina — o caso da loja com um servidor —
        quem resolve é ``origens_recusadas``, que sabe o endereço real porque
        ele bateu na porta.
        """
        ip = rede.ip_local()
        return f"http://{ip}:3001" if ip else ""

    # ── Impressão de teste ───────────────────────────────────────────────────

    def testar_impressao(self, chars_per_line: Optional[int] = None) -> None:
        """Imprime o cupom de teste na largura pedida (ou na configurada).

        Aceita ``chars_per_line`` avulso para a janela poder testar uma largura
        **antes** de salvá-la — é assim que o operador calibra: imprime, olha o
        papel, ajusta. Obrigá-lo a salvar antes de testar transformaria a
        calibração num vaivém.

        Raises:
            ConfiguracaoInvalida: Sem impressora configurada.
            PrinterSendError: A impressora não respondeu — a mensagem já vem
                pronta para a tela.
        """
        destino = self._config.printer_dest
        if not destino:
            raise ConfiguracaoInvalida("Escolha uma impressora antes de testar.")
        largura = chars_per_line or self._config.chars_per_line
        send_raw_bytes(wrap_escpos(montar_cupom_de_teste(largura)), destino)
        logger.info("Cupom de teste enviado para %s (%d colunas).", destino, largura)

    def testar_conexao(self, destino: Optional[str] = None) -> float:
        """Confere se este computador **alcança** a impressora de rede.

        Devolve o tempo de resposta em milissegundos. Não imprime nada — ver
        ``printer_client.test_connection`` para o porquê.

        Raises:
            ConfiguracaoInvalida: Nenhum endereço informado.
            PrinterSendError: Não alcançou, com a mensagem já pronta.
        """
        alvo = (destino or self._config.printer_dest).strip()
        if not alvo:
            raise ConfiguracaoInvalida("Informe o endereço da impressora antes de testar.")
        latencia = test_connection(alvo)
        logger.info("Conexão com %s respondeu em %.0f ms.", alvo, latencia)
        return latencia

    # ── Sistema ──────────────────────────────────────────────────────────────

    def autostart_ativo(self) -> bool:
        return autostart.esta_ativo()

    def autostart_aviso(self) -> str:
        """Por que a inicialização automática pode não estar funcionando.

        Vazio quando não há nada a dizer. Existe porque *"ele inicializa
        normal, mas não inicializa junto com o windows"* não tinha explicação
        nenhuma em tela — a opção marcada dizia que estava tudo bem.
        """
        return autostart.diagnostico()

    def alternar_autostart(self) -> bool:
        """Liga/desliga o início automático. Devolve o estado **resultante**.

        Devolve o estado real depois da tentativa, não o que foi pedido: criar
        o atalho é best-effort (pasta sem permissão, ``APPDATA`` ausente), e uma
        caixa marcada por engano faria o lojista acreditar que o agente sobe
        sozinho quando não sobe.
        """
        if autostart.esta_ativo():
            autostart.desativar()
        else:
            autostart.ativar()
        self.notificar()
        return autostart.esta_ativo()

    def reiniciar(self) -> None:
        """Reexecuta o próprio processo, depois de responder quem pediu.

        ``sys.executable`` vira o próprio binário quando empacotado
        (``sys.frozen``), então isto funciona tanto via ``python main.py``
        quanto no ``.exe``.
        """
        logger.info("Reiniciando o agente.")
        self._depois(lambda: os.execv(sys.executable, [sys.executable] + sys.argv))

    def encerrar(self) -> None:
        logger.info("Encerrando o agente.")
        self._depois(lambda: os._exit(0))

    @staticmethod
    def _depois(acao: Callable[[], None]) -> None:
        def _correr() -> None:
            time.sleep(_ATRASO_ENCERRAMENTO_S)
            acao()

        threading.Thread(target=_correr, daemon=True).start()


# ── Cupom de teste ──────────────────────────────────────────────────────────
# Mesmo conteúdo do `buildTestReceipt` do painel (`lib/pos/print-test.ts`), de
# propósito: o operador que testa pela janela e pelo painel precisa poder
# comparar o mesmo papel. Se um dia divergirem, "o teste do painel sai
# diferente do teste do agente" vira um diagnóstico falso sobre a impressora.


#: Explicação do cupom de teste, em texto corrido — quebrada por palavra na
#: largura de destino, nunca escrita em linhas fixas.
#:
#: Escrever as linhas à mão parece inofensivo e não é: em 32 colunas (papel de
#: 58mm) a frase "linhas em branco extras, a largura" tem 34 caracteres e a
#: própria impressora a quebra. O cupom que existe para provar que a largura
#: está certa sairia quebrado **justamente numa configuração correta**, e o
#: operador concluiria o contrário. Mesma lição que o GS-PDV desktop já pagou
#: com o rodapé cortado no meio da palavra.
_EXPLICACAO_TESTE = (
    "Se este cupom saiu certo, sem linhas em branco extras, a largura esta correta."
)


def montar_cupom_de_teste(largura: int) -> str:
    """Cupom de teste **na largura informada**, nunca numa largura fixa.

    É justamente a largura errada que causa o "muito papel em branco", então o
    teste precisa reproduzir o efeito para o operador calibrar olhando o papel.
    """
    regua = "-" * largura
    return "\n".join([
        "TESTE DE IMPRESSAO".center(largura),
        regua,
        *textwrap.wrap(_EXPLICACAO_TESTE, width=largura),
        regua,
        *textwrap.wrap(f"Largura configurada: {largura} colunas", width=largura),
        _regua_numerada(largura),
        "", "",
    ])


def _regua_numerada(largura: int) -> str:
    """``"....5...10...15"`` até a largura — uma marca a cada 5 colunas.

    Mostra visualmente onde a linha termina: se os números quebrarem para a
    linha de baixo, a largura configurada é maior que a do papel.
    """
    linha = ""
    for coluna in range(1, largura + 1):
        if coluna % 5 == 0:
            marca = str(coluna)
            linha = linha[: max(0, len(linha) - (len(marca) - 1))] + marca
        elif len(linha) < coluna:
            linha += "."
    return linha[:largura]
