"""Ícone na bandeja do sistema (área de notificação / "ícones ocultos").

O agente é um serviço sem janela: sobe, escuta em ``127.0.0.1:9123`` e some.
Isso produzia duas perguntas sem resposta na loja — "ele está rodando?" e "como
eu mexo nisso?" —, e a única forma de responder era abrir o painel web ou o
Gerenciador de Tarefas. O ícone na bandeja responde a primeira só de existir, e
a segunda com um menu de clique direito.

``pystray`` + ``Pillow`` são as únicas dependências novas, e o ícone é
**desenhado em código** para não haver asset a empacotar e nada que possa faltar
no build.

Todo o módulo é opcional: se a bandeja não puder subir (servidor sem ambiente
gráfico, backend de bandeja ausente no Linux), o agente continua imprimindo
normalmente — quem manda é o serviço, não o ícone.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from app import autostart
from app.config import AgentConfig

logger = logging.getLogger(__name__)

_TAMANHO_ICONE = 64

#: Substituições para manter o título da bandeja dentro de latin-1.
#:
#: O backend X11 do pystray codifica o título da janela em latin-1 e **levanta**
#: em qualquer caractere fora dessa faixa (bug real: um travessão "—" no título
#: derrubou o agente inteiro no primeiro teste, 2026-08-17). Como o título é
#: montado com texto em português, é mais seguro higienizar aqui do que confiar
#: que ninguém vai escrever um traço bonito numa mensagem futura.
_SUBSTITUICOES_TITULO = {"—": "-", "–": "-", "“": '"', "”": '"', "…": "...", "’": "'"}


def _titulo_seguro(texto: str) -> str:
    """Título compatível com o backend X11, sem perder a mensagem."""
    for origem, destino in _SUBSTITUICOES_TITULO.items():
        texto = texto.replace(origem, destino)
    # Rede de segurança para qualquer caractere não previsto acima.
    return texto.encode("latin-1", errors="replace").decode("latin-1")


def disponivel() -> bool:
    """Se ``pystray``/``Pillow`` estão instalados nesta máquina."""
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except Exception:  # noqa: BLE001 — ausência é motivo legítimo de seguir headless
        return False
    return True


def _desenhar_icone(conectado: bool):
    """Ícone da bandeja: um cupom saindo da impressora, verde ou cinza.

    Desenhado em runtime em vez de embutido como arquivo — um asset a menos
    para o PyInstaller esquecer de incluir, e a cor acompanha o estado sem
    precisar de duas imagens.
    """
    from PIL import Image, ImageDraw

    cor = (34, 197, 94) if conectado else (113, 113, 122)
    imagem = Image.new("RGBA", (_TAMANHO_ICONE, _TAMANHO_ICONE), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    # Corpo da impressora.
    desenho.rounded_rectangle([8, 24, 56, 48], radius=6, fill=cor)
    # Papel saindo por cima.
    desenho.rectangle([18, 10, 46, 26], fill=(250, 250, 250))
    # Cupom saindo por baixo.
    desenho.rectangle([18, 44, 46, 58], fill=(250, 250, 250))
    desenho.line([22, 50, 42, 50], fill=cor, width=2)
    desenho.line([22, 54, 36, 54], fill=cor, width=2)
    return imagem


class TrayIcon:
    """Ciclo de vida do ícone da bandeja.

    Guarda referência ao ``config`` vivo do app (o mesmo objeto que as rotas
    HTTP mutam), então o rótulo de status reflete mudanças feitas pelo painel
    web sem precisar reiniciar nada.
    """

    def __init__(
        self,
        config: AgentConfig,
        ao_abrir_configuracao: Callable[[], None],
        ao_testar_impressao: Callable[[], None],
        ao_reiniciar: Callable[[], None],
        ao_sair: Callable[[], None],
        url_painel: str = "http://localhost:3001/impressao",
    ) -> None:
        self._config = config
        self._abrir_configuracao = ao_abrir_configuracao
        self._testar_impressao = ao_testar_impressao
        self._reiniciar = ao_reiniciar
        self._sair = ao_sair
        self._url_painel = url_painel
        self._icone = None

    # ── Rótulos ──────────────────────────────────────────────────────────────

    def _texto_status(self) -> str:
        """Primeira linha do menu: responde "está funcionando?" sem abrir nada."""
        if not self._config.token:
            return "Sem token - a impressao vai ser recusada"
        if not self._config.printer_dest:
            return "Sem impressora configurada"
        return f"Pronto - {self._config.printer_dest} ({self._config.chars_per_line} col)"

    def _pronto(self) -> bool:
        return bool(self._config.token and self._config.printer_dest)

    # ── Ações ────────────────────────────────────────────────────────────────

    def _abrir_painel(self) -> None:
        import webbrowser
        webbrowser.open(self._url_painel)

    def _alternar_autostart(self) -> None:
        if autostart.esta_ativo():
            autostart.desativar()
        else:
            autostart.ativar()
        self.atualizar()

    def atualizar(self) -> None:
        """Redesenha ícone e menu — chamado depois de salvar configuração."""
        if self._icone is None:
            return
        try:
            self._icone.icon = _desenhar_icone(self._pronto())
            self._icone.title = _titulo_seguro(f"GS PDV Print Agent - {self._texto_status()}")
            self._icone.update_menu()
        except Exception as exc:  # noqa: BLE001 — bandeja é conforto, nunca derruba
            logger.debug("Não foi possível atualizar a bandeja: %s", exc)

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    def _montar_menu(self):
        import pystray

        # Itens construídos com lambdas para o texto ser reavaliado a cada
        # abertura do menu — assim o status e o check do autostart ficam vivos.
        return pystray.Menu(
            pystray.MenuItem(lambda _i: self._texto_status(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Configurar impressora…", lambda: self._abrir_configuracao(), default=True),
            pystray.MenuItem("Testar impressão", lambda: self._testar_impressao()),
            pystray.MenuItem("Abrir painel no navegador", lambda: self._abrir_painel()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Iniciar com o computador",
                lambda: self._alternar_autostart(),
                checked=lambda _i: autostart.esta_ativo(),
            ),
            pystray.MenuItem("Reiniciar agente", lambda: self._reiniciar()),
            pystray.MenuItem("Sair", lambda: self._encerrar()),
        )

    def _encerrar(self) -> None:
        if self._icone is not None:
            self._icone.stop()
        self._sair()

    def run(self) -> None:
        """Assume a thread atual com o laço da bandeja (não retorna até sair).

        A bandeja precisa da **thread principal** na maioria dos sistemas — por
        isso o uvicorn é que roda em thread separada, e não o contrário.
        """
        import pystray

        self._icone = pystray.Icon(
            "gs-pdv-print-agent",
            icon=_desenhar_icone(self._pronto()),
            title=_titulo_seguro(f"GS PDV Print Agent - {self._texto_status()}"),
            menu=self._montar_menu(),
        )
        self._icone.run()


def iniciar_em_thread(alvo: Callable[[], None], nome: str) -> threading.Thread:
    """Sobe ``alvo`` numa thread daemon — usado para o servidor HTTP."""
    thread = threading.Thread(target=alvo, name=nome, daemon=True)
    thread.start()
    return thread


def resolver_url_painel(config: AgentConfig) -> Optional[str]:
    """Melhor palpite de onde o painel está, a partir das origens autorizadas.

    O agente já sabe quais origens podem falar com ele (``allowed_origins``);
    a primeira delas é, na prática, o endereço do painel daquela loja. Melhor
    que chutar ``localhost:3001`` numa loja que acessa o painel pela LAN.
    """
    for origem in config.allowed_origins:
        if origem.startswith("http"):
            return f"{origem.rstrip('/')}/impressao"
    return None
