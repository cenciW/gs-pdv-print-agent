"""Ícone na área de notificação — acessório, nunca dono do laço principal.

Mudou de papel na ``v0.3.0``. Na ``v0.2.0`` a bandeja era a interface: ela
segurava a thread principal e abria a janela de dentro de um callback próprio.
Isso produziu dois defeitos reais, um por sistema operacional:

* **Windows** — o ``pystray`` despacha o callback do menu de dentro da bomba de
  mensagens (``_win32.py:224``, dentro de ``_on_notify``, dentro de
  ``DispatchMessage``). Chamar ``mainloop()`` do Tk ali **para a bomba**: a
  janela abre e a bandeja congela atrás dela. Foi o defeito relatado.
* **Linux/X11** — pior e mais silencioso: ``pystray/_xorg.py`` declara
  ``HAS_MENU = False`` e ``_update_menu`` é literalmente ``pass``
  ("Menus are not supported on X"). O menu inteiro era **descartado sem
  aviso**: o ícone aparecia e não fazia absolutamente nada.

Agora: a janela é dona do laço principal, a bandeja roda destacada e todo item
de menu apenas **enfileira** a ação (``janela.agendar``). O callback retorna em
microssegundos, então nada pode prender a bomba de mensagens — o defeito do
Windows morre por construção. E o código pergunta ``suporta_menu()`` em vez de
assumir, para não prometer no Linux um menu que não existe.
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from app.agent_actions import AgentActions

logger = logging.getLogger(__name__)

_TAMANHO_ICONE = 64

#: Substituições para manter o título dentro de latin-1.
#:
#: O backend X11 do pystray codifica o título da janela em latin-1 e **levanta**
#: em qualquer caractere fora dessa faixa — um travessão no título derrubou o
#: agente inteiro no primeiro teste (2026-08-17), com o servidor HTTP já no ar.
_SUBSTITUICOES_TITULO = {"—": "-", "–": "-", "“": '"', "”": '"', "…": "...", "’": "'"}


def _titulo_seguro(texto: str) -> str:
    """Título compatível com o backend X11, sem perder a mensagem."""
    for origem, destino in _SUBSTITUICOES_TITULO.items():
        texto = texto.replace(origem, destino)
    return texto.encode("latin-1", errors="replace").decode("latin-1")


def disponivel() -> bool:
    """Se ``pystray``/``Pillow`` estão instalados nesta máquina."""
    try:
        import PIL  # noqa: F401
        import pystray  # noqa: F401
    except Exception:  # noqa: BLE001 — ausência é motivo legítimo de seguir sem ícone
        return False
    return True


def suporta_menu() -> bool:
    """Se o backend desta máquina realmente desenha um menu de clique direito.

    Existe porque o backend X11 do ``pystray`` aceita um menu e o descarta em
    silêncio. Sem esta pergunta, o agente ofereceria "minimizar para a bandeja"
    num sistema onde não há como voltar — e a configuração ficaria
    inalcançável.
    """
    if not disponivel():
        return False
    try:
        import pystray

        return bool(getattr(pystray.Icon, "HAS_MENU", False))
    except Exception:  # noqa: BLE001
        return False


def _desenhar_icone(pronto: bool):
    """Ícone da bandeja: um cupom saindo da impressora, verde ou cinza.

    Desenhado em runtime em vez de embutido como arquivo — um asset a menos
    para o PyInstaller esquecer, e a cor acompanha o estado sem duas imagens.
    """
    from PIL import Image, ImageDraw

    cor = (34, 197, 94) if pronto else (113, 113, 122)
    imagem = Image.new("RGBA", (_TAMANHO_ICONE, _TAMANHO_ICONE), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    desenho.rounded_rectangle([8, 24, 56, 48], radius=6, fill=cor)
    desenho.rectangle([18, 10, 46, 26], fill=(250, 250, 250))
    desenho.rectangle([18, 44, 46, 58], fill=(250, 250, 250))
    desenho.line([22, 50, 42, 50], fill=cor, width=2)
    desenho.line([22, 54, 36, 54], fill=cor, width=2)
    return imagem


class TrayAccessory:
    """Ícone da bandeja rodando numa thread própria.

    Args:
        actions: Núcleo de ações — o mesmo que a janela usa.
        agendar: Como pedir trabalho ao laço da janela. **Toda** ação de menu
            passa por aqui; nada é executado na thread da bandeja.
        ao_mostrar_janela: Ação de "Abrir configuração".
    """

    def __init__(
        self,
        actions: AgentActions,
        agendar: Callable[[Callable[[], None]], None],
        ao_mostrar_janela: Callable[[], None],
    ) -> None:
        self._actions = actions
        self._agendar = agendar
        self._mostrar_janela = ao_mostrar_janela
        self._icone = None
        self._thread: Optional[threading.Thread] = None

    # ── Menu ─────────────────────────────────────────────────────────────────

    def _item(self, acao: Callable[[], None]) -> Callable[[], None]:
        """Embrulha uma ação para ela rodar no laço da janela, não aqui.

        **Este embrulho é a correção do congelamento.** Executar qualquer coisa
        demorada — e abrir janela é o caso extremo — dentro do callback do
        ``pystray`` prende a bomba de mensagens do Windows. Enfileirar retorna
        na hora.
        """
        return lambda: self._agendar(acao)

    def _montar_menu(self):
        import pystray

        # Lambdas para o texto ser reavaliado a cada abertura do menu — assim o
        # status e o estado do autostart não ficam congelados no que eram
        # quando o ícone subiu.
        return pystray.Menu(
            pystray.MenuItem(lambda _i: self._actions.status().resumo(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Abrir configuração", self._item(self._mostrar_janela), default=True,
            ),
            pystray.MenuItem("Testar impressão", self._item(self._testar)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Iniciar com o computador",
                self._item(self._actions.alternar_autostart),
                checked=lambda _i: self._actions.autostart_ativo(),
            ),
            pystray.MenuItem("Reiniciar agente", self._item(self._actions.reiniciar)),
            pystray.MenuItem("Sair", self._item(self._sair)),
        )

    def _testar(self) -> None:
        """Testar pela bandeja abre a janela e testa por lá.

        Um erro de impressão precisa de uma tela para ser lido; a bandeja não
        tem onde mostrar "a impressora não respondeu".
        """
        self._mostrar_janela()
        try:
            self._actions.testar_impressao()
        except Exception as exc:  # noqa: BLE001 — a mensagem é o resultado do teste
            logger.warning("Teste de impressão pela bandeja falhou: %s", exc)

    def _sair(self) -> None:
        self.parar()
        self._actions.encerrar()

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    def iniciar(self) -> bool:
        """Sobe o ícone numa thread própria. Devolve se conseguiu.

        Nunca levanta: a bandeja é conforto. Perder o ícone é aceitável; perder
        a impressão da loja não é — foi o que já aconteceu quando um travessão
        no título matou o processo inteiro com o servidor no ar.
        """
        try:
            import pystray

            self._icone = pystray.Icon(
                "gs-pdv-print-agent",
                icon=_desenhar_icone(self._actions.status().pronto),
                title=_titulo_seguro(f"GS PDV Print Agent - {self._actions.status().resumo()}"),
                menu=self._montar_menu(),
            )
            self._thread = threading.Thread(
                target=self._correr, name="bandeja", daemon=True,
            )
            self._thread.start()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("Não foi possível subir o ícone da bandeja — seguindo sem ele.")
            return False

    def _correr(self) -> None:
        try:
            self._icone.run()
        except Exception:  # noqa: BLE001 — falha da bandeja vira degradação, não queda
            logger.exception("Falha na bandeja do sistema — o agente continua imprimindo.")

    def atualizar(self) -> None:
        """Redesenha ícone e título — chamado depois de salvar configuração."""
        if self._icone is None:
            return
        try:
            status = self._actions.status()
            self._icone.icon = _desenhar_icone(status.pronto)
            self._icone.title = _titulo_seguro(f"GS PDV Print Agent - {status.resumo()}")
            self._icone.update_menu()
        except Exception as exc:  # noqa: BLE001 — bandeja é conforto, nunca derruba
            logger.debug("Não foi possível atualizar a bandeja: %s", exc)

    def parar(self) -> None:
        if self._icone is None:
            return
        try:
            self._icone.stop()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Não foi possível parar a bandeja: %s", exc)
