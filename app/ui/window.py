"""Janela do agente — a interface principal, dona do laço principal.

Até a ``v0.2.0`` a bandeja era dona da thread principal e a janela era aberta
de dentro de um callback dela. Isso produziu um defeito real no Windows: o
``pystray`` despacha o callback do menu **de dentro da bomba de mensagens**
(``_win32.py`` → ``_on_notify`` → ``DispatchMessage``), e chamar ``mainloop()``
ali congela a bandeja enquanto a janela viver. O relato do usuário foi
exatamente esse: a janela abriu, listou as impressoras, e "ficou toda travada a
aplicação" — nenhum item de menu voltou a responder.

A correção não é tomar cuidado dentro do callback: é **inverter a posse**. Aqui
o Tk é dono do laço principal e a bandeja virou acessório que só *enfileira*
ações (``agendar``). Callback de bandeja passa a retornar em microssegundos,
então a bomba de mensagens nunca fica presa — o defeito morre por construção,
não por disciplina de quem escrever o próximo callback.

Por que fila e não ``root.after()`` direto de outra thread: ``after``
cross-thread depende de o Tcl ter sido compilado com suporte a threads, o que
não é garantido em toda distribuição nem em todo empacotamento. Uma
``queue.Queue`` drenada pelo próprio laço do Tk não depende disso, e deixa
óbvio no código que existe **uma única porta** de entrada vinda de fora.
"""

from __future__ import annotations

import logging
import queue
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Callable, Optional

from app.agent_actions import LARGURAS, AgentActions, ConfiguracaoInvalida
from app.printer_client import PrinterSendError

logger = logging.getLogger(__name__)

#: De quanto em quanto tempo o laço do Tk drena a fila e repinta o status.
#: Um único temporizador para as duas coisas — dois relógios num formulário
#: seriam duas fontes de "quando a tela está velha".
_INTERVALO_TICK_MS = 700

_MODO_INSTALADA = "instalada"
_MODO_REDE = "rede"


def disponivel() -> bool:
    """Se dá para abrir janela nesta máquina (Tk presente **e** com display).

    Importar ``tkinter`` não basta: o módulo existe em servidor sem ambiente
    gráfico e só falha no ``Tk()``. Como a janela virou a interface principal,
    a diferença entre "não tem janela" e "quebra ao abrir" decide se o agente
    sobe como serviço ou morre sem dizer nada.
    """
    try:
        import tkinter

        raiz = tkinter.Tk()
        raiz.destroy()
    except Exception as exc:  # noqa: BLE001 — ausência de Tk/display é caso previsto
        logger.info("Sem interface gráfica disponível (%s) — modo serviço.", exc)
        return False
    return True


class AgentWindow:
    """Janela de configuração do agente.

    Args:
        actions: Núcleo de ações — a janela não fala com ``config``/``printers``
            direto, só por aqui.
    """

    def __init__(self, actions: AgentActions) -> None:
        self._actions = actions
        self._ao_fechar_para_bandeja: Optional[Callable[[], None]] = None
        self._fila: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._raiz = None
        self._impressoras: list = []
        # Espelha o que a lista mostra AGORA (depois do filtro) — é por ele que
        # o índice selecionado vira nome de impressora, então precisa existir
        # antes da primeira filtragem.
        self._visiveis: list = []
        self._avisou_bandeja = False

    def permitir_esconder_na_bandeja(self, ao_esconder: Callable[[], None]) -> None:
        """Declara que existe uma bandeja **com menu** para trazer a janela de volta.

        Só quem sabe disso é o arranque, e só depois de a bandeja subir de
        verdade — por isso não é parâmetro do construtor. Sem esta chamada,
        fechar a janela pergunta se é para encerrar o agente, que é o
        comportamento correto onde não há como reabrir (Linux/X11).
        """
        self._ao_fechar_para_bandeja = ao_esconder

    # ── Porta única para outras threads ──────────────────────────────────────

    def agendar(self, acao: Callable[[], None]) -> None:
        """Pede ao laço do Tk para executar ``acao``. Seguro de outra thread.

        É o que a bandeja usa. Retorna imediatamente — nunca executa nada na
        thread de quem chamou.
        """
        self._fila.put(acao)

    def _drenar(self) -> None:
        while True:
            try:
                acao = self._fila.get_nowait()
            except queue.Empty:
                return
            try:
                acao()
            except Exception:  # noqa: BLE001 — ação de menu não pode derrubar a janela
                logger.exception("Falha ao executar ação agendada.")

    # ── Ciclo de vida ────────────────────────────────────────────────────────

    def executar(self, iniciar_escondida: bool = False) -> None:
        """Assume a thread principal com o laço do Tk. Só retorna ao encerrar."""
        import tkinter as tk

        self._raiz = tk.Tk()
        self._montar()
        self._cancelar_observador = self._actions.observar(
            lambda: self.agendar(self._recarregar_da_config),
        )
        if iniciar_escondida:
            self._raiz.withdraw()
        self._tick()
        self._raiz.mainloop()

    def mostrar(self) -> None:
        """Traz a janela para a frente — chamado pelo menu da bandeja."""
        if self._raiz is None:
            return
        self._raiz.deiconify()
        self._raiz.lift()
        self._raiz.focus_force()

    def _tick(self) -> None:
        """Único temporizador: drena a fila e repinta a barra de status."""
        self._drenar()
        self._pintar_status()
        if self._raiz is not None:
            self._raiz.after(_INTERVALO_TICK_MS, self._tick)

    def _ao_pedir_fechamento(self) -> None:
        """Botão X da janela.

        Esconder para a bandeja só é oferecido quando existe uma bandeja com
        menu de verdade. No Linux/X11 o ``pystray`` não suporta menu
        (``HAS_MENU = False``), então esconder deixaria o operador sem nenhuma
        forma de voltar — melhor perguntar de frente.
        """
        from tkinter import messagebox

        if self._ao_fechar_para_bandeja is not None:
            self._ao_fechar_para_bandeja()
            self._raiz.withdraw()
            if not self._avisou_bandeja:
                self._avisou_bandeja = True
                messagebox.showinfo(
                    "O agente continua rodando",
                    "A janela foi fechada, mas o agente continua imprimindo.\n\n"
                    "Para abrir de novo, clique no ícone da área de notificação "
                    "(perto do relógio).",
                    parent=self._raiz,
                )
            return

        if messagebox.askyesno(
            "Encerrar o agente?",
            "Fechar esta janela encerra o agente — a loja para de imprimir "
            "pelo cupom automático.\n\nEncerrar mesmo assim?",
            default="no",
            parent=self._raiz,
        ):
            self._actions.encerrar()
            self._raiz.destroy()

    # ── Montagem ─────────────────────────────────────────────────────────────

    def _montar(self) -> None:
        import tkinter as tk
        from tkinter import ttk

        raiz = self._raiz
        raiz.title("GS PDV — Agente de Impressão")
        raiz.protocol("WM_DELETE_WINDOW", self._ao_pedir_fechamento)
        # A altura mínima é calculada do conteúdo no fim de `_montar`, não
        # chutada aqui: um número fixo vira recorte silencioso toda vez que a
        # tela ganha um campo. Já aconteceu duas vezes na mesma sessão.
        raiz.minsize(560, 400)

        corpo = ttk.Frame(raiz, padding=12)
        corpo.pack(fill="both", expand=True)

        # Botões e barra de status são empacotados PRIMEIRO, ancorados embaixo.
        # No `pack` do Tk quem chega antes reserva espaço antes: com eles por
        # último, um bloco que cresce empurra o "Salvar" para fora da janela.
        # Foi o que aconteceu ao acrescentar as origens autorizadas — só
        # apareceu olhando a captura da verificação, porque nenhuma asserção
        # perguntava se o botão estava VISÍVEL.
        acoes = ttk.Frame(corpo)
        acoes.pack(side="bottom", fill="x", pady=(8, 0))
        self._btn_salvar = ttk.Button(acoes, text="Salvar", command=self._salvar)
        self._btn_salvar.pack(side="left")
        ttk.Button(acoes, text="Testar impressão", command=self._testar).pack(side="left", padx=6)
        ttk.Button(acoes, text="Fechar", command=self._ao_pedir_fechamento).pack(side="right")

        # Barra de status: responde "está funcionando?" sem abrir mais nada.
        self._lbl_status = ttk.Label(corpo, text="", anchor="w")
        self._lbl_status.pack(side="bottom", fill="x", pady=(10, 0))

        self._montar_bloco_impressora(tk, ttk, corpo)
        self._montar_bloco_conexao(tk, ttk, corpo)
        self._montar_bloco_sistema(tk, ttk, corpo)

        self._recarregar_impressoras(preservar_escolha=False)
        self._recarregar_da_config()
        self._ajustar_altura_ao_conteudo()

    def _ajustar_altura_ao_conteudo(self) -> None:
        """Faz a janela caber tudo o que ela tem dentro.

        O `pack` do Tk **recorta em silêncio** o que não cabe: nada de erro, nada
        no log — o widget simplesmente não aparece. Nesta sessão isso escondeu
        primeiro o botão "Salvar" e depois o caminho do arquivo de log. Perguntar
        ao próprio Tk qual é a altura necessária (`winfo_reqheight`) elimina a
        classe inteira de defeito, em vez de corrigir um caso por vez.
        """
        raiz = self._raiz
        raiz.update_idletasks()

        # **Sem `geometry()` de propósito.** Fixar um tamanho aqui congela a
        # janela num número medido antes de o Tk terminar de calcular o texto —
        # foi assim que as linhas de caminho ficaram 64px fora da janela, com
        # `reqheight` já valendo 755 e a janela presa em 691. Sem `geometry`, o
        # toplevel acompanha o conteúdo sozinho, que é o comportamento padrão do
        # Tk e não depende de eu acertar o instante da medição.
        #
        # `minsize` continua, para o operador não conseguir encolher a janela
        # até esconder o "Salvar" com o mouse. Fica limitado à tela: monitor de
        # máquina de loja é pequeno, e um mínimo maior que o monitor recriaria o
        # recorte por outro caminho.
        largura = max(raiz.winfo_reqwidth(), 560)
        altura = min(raiz.winfo_reqheight(), int(raiz.winfo_screenheight() * 0.85))
        raiz.minsize(largura, altura)

    def _montar_bloco_impressora(self, tk, ttk, pai) -> None:
        bloco = ttk.LabelFrame(pai, text=" Impressora ", padding=10)
        bloco.pack(fill="both", expand=True)

        # Os dois caminhos são botões de opção, lado a lado, em vez de a
        # impressora de rede ser um item "Outro" no fim de uma lista longa.
        # Foi exatamente isso que o usuário não achou na v0.2.0 ("não consigo
        # inserir um IP manual"): o caminho existia, escondido.
        self._modo = tk.StringVar(value=_MODO_INSTALADA)
        linha_modo = ttk.Frame(bloco)
        linha_modo.pack(fill="x")
        ttk.Radiobutton(
            linha_modo, text="Instalada neste computador", value=_MODO_INSTALADA,
            variable=self._modo, command=self._sincronizar_modo,
        ).pack(side="left")
        ttk.Radiobutton(
            linha_modo, text="Impressora de rede (IP)", value=_MODO_REDE,
            variable=self._modo, command=self._sincronizar_modo,
        ).pack(side="left", padx=(14, 0))

        # ── Instalada: busca + lista filtrada ──
        self._painel_instalada = ttk.Frame(bloco)
        self._painel_instalada.pack(fill="both", expand=True, pady=(8, 0))

        linha_busca = ttk.Frame(self._painel_instalada)
        linha_busca.pack(fill="x")
        ttk.Label(linha_busca, text="Buscar:").pack(side="left")
        self._busca = tk.StringVar()
        # Filtra enquanto digita. O Combobox `readonly` da v0.2.0 não deixava
        # digitar para filtrar e, com 23 impressoras, "buscar" virava rolar.
        self._busca.trace_add("write", lambda *_: self._filtrar())
        ttk.Entry(linha_busca, textvariable=self._busca).pack(
            side="left", fill="x", expand=True, padx=(6, 6),
        )
        ttk.Button(linha_busca, text="Atualizar", command=self._recarregar_impressoras).pack(side="left")

        # Com barra de rolagem: numa máquina de loja a lista passa de 20
        # impressoras (o usuário tinha 23), e uma caixa de 8 linhas sem barra
        # não avisa que existe mais coisa embaixo — o operador conclui que a
        # impressora dele "não aparece".
        caixa = ttk.Frame(self._painel_instalada)
        caixa.pack(fill="both", expand=True, pady=(6, 0))
        self._lista = tk.Listbox(caixa, height=5, exportselection=False, activestyle="none")
        rolagem = ttk.Scrollbar(caixa, orient="vertical", command=self._lista.yview)
        self._lista.configure(yscrollcommand=rolagem.set)
        self._lista.pack(side="left", fill="both", expand=True)
        rolagem.pack(side="right", fill="y")
        self._lista.bind("<<ListboxSelect>>", lambda _e: self._pintar_status())

        self._lbl_lista_vazia = ttk.Label(
            self._painel_instalada,
            text="Nenhuma impressora encontrada neste computador.\n"
                 "Se a sua é de rede, escolha \"Impressora de rede (IP)\" acima.",
            foreground="#a06000", justify="left",
        )

        # ── Rede: endereço manual ──
        self._painel_rede = ttk.Frame(bloco)
        ttk.Label(self._painel_rede, text="Endereço da impressora:").pack(anchor="w")
        self._endereco = tk.StringVar()
        linha_end = ttk.Frame(self._painel_rede)
        linha_end.pack(fill="x", pady=(4, 0))
        ttk.Entry(linha_end, textvariable=self._endereco).pack(
            side="left", fill="x", expand=True,
        )
        # Separado do "Testar impressão" de propósito: "o computador não alcança
        # a impressora" (IP errado, desligada, firewall, outra faixa de rede) e
        # "alcança mas não imprimiu" (papel, largura, ESC/POS) têm soluções
        # diferentes, e antes davam a mesma mensagem genérica.
        ttk.Button(linha_end, text="Testar conexão", command=self._testar_conexao).pack(
            side="left", padx=(6, 0),
        )
        ttk.Label(
            self._painel_rede,
            text="Formato: 192.168.1.50 ou 192.168.1.50:9100 (a porta 9100 é o padrão).\n"
                 "Impressora de rede não aparece na lista do sistema.",
            foreground="#666", justify="left",
        ).pack(anchor="w", pady=(4, 0))

        # ── Largura ──
        linha_largura = ttk.Frame(bloco)
        linha_largura.pack(fill="x", pady=(10, 0))
        ttk.Label(linha_largura, text="Largura do papel:").pack(side="left")
        self._largura = tk.IntVar(value=LARGURAS[0][0])
        for valor, rotulo in LARGURAS:
            ttk.Radiobutton(
                linha_largura, text=rotulo, value=valor, variable=self._largura,
            ).pack(side="left", padx=(10, 0))

    def _montar_bloco_conexao(self, tk, ttk, pai) -> None:
        bloco = ttk.LabelFrame(pai, text=" Conexão com o painel ", padding=10)
        bloco.pack(fill="x", pady=(10, 0))

        ttk.Label(bloco, text="Token do agente (painel > Impressão):").pack(anchor="w")
        linha = ttk.Frame(bloco)
        linha.pack(fill="x", pady=(4, 0))
        self._token = tk.StringVar()
        self._entrada_token = ttk.Entry(linha, textvariable=self._token, show="*")
        self._entrada_token.pack(side="left", fill="x", expand=True)
        self._mostrar_token = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            linha, text="Mostrar", variable=self._mostrar_token,
            command=lambda: self._entrada_token.configure(
                show="" if self._mostrar_token.get() else "*",
            ),
        ).pack(side="left", padx=(6, 0))

        ttk.Label(
            bloco,
            text="Sem token o agente recusa toda impressão — é proposital.",
            foreground="#666",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(bloco, text="Endereços do painel autorizados a imprimir aqui:").pack(
            anchor="w", pady=(10, 0),
        )
        self._origens = tk.Text(bloco, height=2, wrap="none")
        self._origens.pack(fill="x", pady=(4, 0))

        # A linha que resolve o caso real: o painel roda noutro computador da
        # loja, e ninguém sabe o IP dele de cor. O agente sabe — quem tentou
        # imprimir bateu na porta e ficou registrado. A pessoa só confirma.
        self._linha_detectada = ttk.Frame(bloco)
        self._lbl_detectada = ttk.Label(self._linha_detectada, foreground="#a06000")
        self._lbl_detectada.pack(side="left")
        ttk.Button(
            self._linha_detectada, text="Autorizar", command=self._autorizar_detectada,
        ).pack(side="left", padx=(8, 0))

        ttk.Label(
            bloco,
            text="Endereços da REDE LOCAL (192.168.x, 10.x, 172.16-31.x) já são "
                 "aceitos sem precisar estar nesta lista — é o caso do painel "
                 "aberto no celular. Um endereço por linha; é o que aparece na "
                 "barra do navegador ao abrir o painel.",
            foreground="#666",
        ).pack(anchor="w", pady=(4, 0))

    def _montar_bloco_sistema(self, tk, ttk, pai) -> None:
        bloco = ttk.LabelFrame(pai, text=" Sistema ", padding=10)
        bloco.pack(fill="x", pady=(10, 0))

        self._autostart = tk.BooleanVar(value=self._actions.autostart_ativo())
        ttk.Checkbutton(
            bloco, text="Iniciar junto com o computador",
            variable=self._autostart, command=self._alternar_autostart,
        ).pack(anchor="w")

        # A opção marcada não prova que o Windows vai executar: ele deixa a
        # pessoa desativar a inicialização por fora (Gerenciador de Tarefas), e
        # o registro pode ter ficado apontando para uma pasta antiga. Quando é
        # esse o caso, a tela DIZ — antes, o agente jurava estar configurado
        # enquanto nada subia no logon.
        self._lbl_autostart = ttk.Label(
            bloco, text="", foreground="#b06000", wraplength=520, justify="left",
        )
        self._lbl_autostart.pack(anchor="w", pady=(2, 0))

        # "Inicializou sozinho, mas pede uma permissão para executar": o
        # arquivo veio da internet e o Windows pergunta a cada início. Num
        # computador de loja isso anula o autostart — o agente fica esperando
        # alguém clicar, e o primeiro cupom do dia não sai.
        self._linha_motw = ttk.Frame(bloco)
        ttk.Label(
            self._linha_motw,
            text="O Windows pede confirmação toda vez que o agente abre.",
            foreground="#b06000", wraplength=380, justify="left",
        ).pack(side="left")
        ttk.Button(
            self._linha_motw, text="Não pedir mais", command=self._remover_aviso_windows,
        ).pack(side="left", padx=(8, 0))

        linha = ttk.Frame(bloco)
        linha.pack(fill="x", pady=(8, 0))
        ttk.Button(linha, text="Abrir pasta de configuração", command=self._abrir_pasta).pack(side="left")
        ttk.Button(linha, text="Ver log", command=self._abrir_log).pack(side="left", padx=6)
        ttk.Button(linha, text="Reiniciar agente", command=self._reiniciar).pack(side="left")

        # O caminho na tela porque "onde fica o arquivo?" é a primeira pergunta
        # quando algo dá errado numa máquina de loja — e a resposta muda entre
        # rodar pelo Python e rodar empacotado.
        self._lbl_caminhos = ttk.Label(bloco, text="", foreground="#666", justify="left")
        self._lbl_caminhos.pack(anchor="w", pady=(8, 0))

    # ── Estado da tela ───────────────────────────────────────────────────────

    def _sincronizar_modo(self) -> None:
        if self._modo.get() == _MODO_REDE:
            self._painel_instalada.pack_forget()
            self._painel_rede.pack(fill="x", expand=False, pady=(8, 0))
        else:
            self._painel_rede.pack_forget()
            self._painel_instalada.pack(fill="both", expand=True, pady=(8, 0))
        self._pintar_status()

    def _recarregar_impressoras(self, preservar_escolha: bool = True) -> None:
        anterior = self._destino_escolhido() if preservar_escolha else ""
        self._impressoras = self._actions.listar_impressoras()
        self._filtrar()
        if anterior:
            self._selecionar_na_lista(anterior)

    def _filtrar(self) -> None:
        termo = self._busca.get().strip().lower()
        selecionado = self._destino_escolhido()
        self._visiveis = [p for p in self._impressoras if termo in p.name.lower()]
        self._lista.delete(0, "end")
        for impressora in self._visiveis:
            sufixo = "   (padrao do sistema)" if impressora.is_default else ""
            self._lista.insert("end", f"{impressora.name}{sufixo}")
        if not self._impressoras:
            self._lbl_lista_vazia.pack(anchor="w", pady=(6, 0))
        else:
            self._lbl_lista_vazia.pack_forget()
        if selecionado:
            self._selecionar_na_lista(selecionado)

    def _selecionar_na_lista(self, nome: str) -> None:
        for indice, impressora in enumerate(self._visiveis):
            if impressora.name == nome:
                self._lista.selection_clear(0, "end")
                self._lista.selection_set(indice)
                self._lista.see(indice)
                return

    def _destino_escolhido(self) -> str:
        """O destino que a tela está propondo agora — pode não estar salvo."""
        if self._modo.get() == _MODO_REDE:
            return self._endereco.get().strip()
        selecao = self._lista.curselection()
        if not selecao:
            return ""
        return self._visiveis[selecao[0]].name

    def _recarregar_da_config(self) -> None:
        """Traz para a tela o que está salvo — inclusive mudança feita pelo painel."""
        status = self._actions.status()
        self._token.set(self._actions.config.token)
        self._largura.set(status.chars_per_line)
        self._autostart.set(self._actions.autostart_ativo())
        self._atualizar_aviso_autostart()

        destino = status.printer_dest
        instaladas = {p.name for p in self._impressoras}
        if destino and destino not in instaladas:
            self._modo.set(_MODO_REDE)
            self._endereco.set(destino)
        else:
            self._modo.set(_MODO_INSTALADA)
            if destino:
                # Um filtro de busca ativo pode estar escondendo justamente a
                # impressora salva — e aí a seleção sumiria em silêncio, com a
                # tela dizendo "nenhuma escolhida" enquanto o config.json diz
                # outra coisa. Recarregar significa "me mostre o que está
                # salvo", então o filtro cede a vez. Defeito real, achado pela
                # verificação em ambiente gráfico (o teste unitário passava
                # porque não tinha busca preenchida).
                if not any(p.name == destino for p in self._visiveis):
                    self._busca.set("")
                self._selecionar_na_lista(destino)
        self._sincronizar_modo()

        self._origens.delete("1.0", "end")
        self._origens.insert("1.0", "\n".join(self._actions.config.allowed_origins))
        self._pintar_detectada()

        self._lbl_caminhos.configure(
            text=f"Configuração e log em: {status.arquivo_de_config.parent}",
        )

    def _pintar_status(self) -> None:
        # A barra nasce depois dos blocos, e há gatilho de tela (seleção da
        # lista, troca de modo) que dispara durante a própria montagem.
        if self._raiz is None or getattr(self, "_lbl_status", None) is None:
            return
        status = self._actions.status()
        servico = f"no ar em 0.0.0.0:{status.porta}" if status.servidor_no_ar else "FORA DO AR"
        destino = self._destino_escolhido() or "(nenhuma escolhida)"
        pendente = "" if destino == status.printer_dest else "   [não salvo]"
        linha = f"Serviço {servico}  |  {destino} - {self._largura.get()} col{pendente}"

        # "O serviço está no ar" NÃO é a mesma coisa que "a loja consegue
        # imprimir": sem token o agente recusa tudo. Olhando a captura da
        # verificação, a barra dizia "Serviço no ar | POS-80 - 48 col" com o
        # token em branco — um operador leria como tudo certo e só descobriria
        # no primeiro pedido que não sai.
        if not status.pronto:
            linha = f"ATENÇÃO: {status.motivo}  |  {linha}"
        self._lbl_status.configure(
            text=linha, foreground="#a00" if not status.pronto else "",
        )

    # ── Ações ────────────────────────────────────────────────────────────────

    def _salvar(self) -> None:
        from tkinter import messagebox

        destino = self._destino_escolhido()
        if not destino:
            messagebox.showwarning(
                "Escolha a impressora",
                "Selecione uma impressora da lista ou informe o endereço de rede.",
                parent=self._raiz,
            )
            return
        try:
            self._actions.salvar_impressora(destino, self._largura.get())
            self._actions.salvar_token(self._token.get())
            self._actions.salvar_origens(self._origens_na_tela())
        except ConfiguracaoInvalida as exc:
            messagebox.showerror("Configuração inválida", str(exc), parent=self._raiz)
            return
        messagebox.showinfo("Salvo", "Configuração salva.", parent=self._raiz)
        self._pintar_status()

    def _testar(self) -> None:
        """Testa a largura que está **na tela**, mesmo sem salvar.

        É assim que se calibra: imprime, olha o papel, ajusta. Exigir salvar
        antes transformaria a calibração num vaivém.
        """
        from tkinter import messagebox

        destino = self._destino_escolhido()
        if not destino:
            messagebox.showwarning(
                "Escolha a impressora",
                "Selecione uma impressora antes de testar.", parent=self._raiz,
            )
            return
        if destino != self._actions.config.printer_dest:
            try:
                self._actions.salvar_impressora(destino, self._largura.get())
            except ConfiguracaoInvalida as exc:
                messagebox.showerror("Configuração inválida", str(exc), parent=self._raiz)
                return
        try:
            self._actions.testar_impressao(self._largura.get())
        except (ConfiguracaoInvalida, PrinterSendError) as exc:
            messagebox.showerror("Não foi possível imprimir", str(exc), parent=self._raiz)
            return
        messagebox.showinfo(
            "Teste enviado",
            "Cupom de teste enviado.\n\nConfira no papel: se os números da régua "
            "quebrarem para a linha de baixo, a largura está maior que o papel.",
            parent=self._raiz,
        )

    def _origens_na_tela(self) -> list[str]:
        return [l for l in self._origens.get("1.0", "end").splitlines() if l.strip()]

    def _pintar_detectada(self) -> None:
        """Mostra o painel que tentou imprimir aqui e ainda não foi autorizado."""
        recusadas = self._actions.origens_recusadas()
        if not recusadas:
            self._linha_detectada.pack_forget()
            return
        self._lbl_detectada.configure(text=f"Tentou imprimir aqui: {recusadas[-1]}")
        self._linha_detectada.pack(fill="x", pady=(6, 0))

    def _autorizar_detectada(self) -> None:
        from tkinter import messagebox

        recusadas = self._actions.origens_recusadas()
        if not recusadas:
            return
        try:
            self._actions.salvar_origens([*self._origens_na_tela(), recusadas[-1]])
        except ConfiguracaoInvalida as exc:
            messagebox.showerror("Endereço inválido", str(exc), parent=self._raiz)
            return
        self._recarregar_da_config()

    def _testar_conexao(self) -> None:
        from tkinter import messagebox

        try:
            latencia = self._actions.testar_conexao(self._endereco.get())
        except (ConfiguracaoInvalida, PrinterSendError) as exc:
            messagebox.showerror("Sem conexão com a impressora", str(exc), parent=self._raiz)
            return
        messagebox.showinfo(
            "Conexão OK",
            f"Este computador alcançou a impressora em {latencia:.0f} ms.\n\n"
            "Isso confirma a rede. Se mesmo assim não sair papel, use "
            "'Testar impressão' — aí o problema é na impressora, não na rede.",
            parent=self._raiz,
        )

    def _atualizar_aviso_autostart(self) -> None:
        rotulo = getattr(self, "_lbl_autostart", None)
        if rotulo is None:
            return
        aviso = self._actions.autostart_aviso()
        rotulo.configure(text=("⚠ " + aviso) if aviso else "")

        linha = getattr(self, "_linha_motw", None)
        if linha is None:
            return
        if self._actions.windows_pede_confirmacao():
            linha.pack(fill="x", pady=(4, 0))
        else:
            linha.pack_forget()

    def _remover_aviso_windows(self) -> None:
        from tkinter import messagebox

        if self._actions.remover_aviso_do_windows():
            messagebox.showinfo(
                "Pronto",
                "O Windows não vai mais pedir confirmação para abrir o agente "
                "nesta cópia do programa.",
                parent=self._raiz,
            )
        else:
            messagebox.showwarning(
                "Não consegui remover",
                "O Windows não deixou alterar o arquivo. Dá para fazer à mão: "
                "clique com o botão direito no gs-pdv-print-agent.exe → "
                "Propriedades → marque \"Desbloquear\" → OK.",
                parent=self._raiz,
            )
        self._atualizar_aviso_autostart()

    def _alternar_autostart(self) -> None:
        # Reflete o estado REAL: criar o atalho é best-effort, e uma caixa
        # marcada por engano faria o lojista crer que o agente sobe sozinho.
        self._autostart.set(self._actions.alternar_autostart())
        self._atualizar_aviso_autostart()

    def _reiniciar(self) -> None:
        from tkinter import messagebox

        if messagebox.askyesno(
            "Reiniciar o agente?",
            "O agente vai fechar e abrir de novo. Uma impressao em andamento "
            "pode ser perdida.", default="no", parent=self._raiz,
        ):
            self._actions.reiniciar()

    def _abrir_pasta(self) -> None:
        abrir_no_sistema(self._actions.status().arquivo_de_config.parent)

    def _abrir_log(self) -> None:
        from tkinter import messagebox

        log = self._actions.status().arquivo_de_log
        if log is None:
            messagebox.showinfo(
                "Sem log ainda",
                "Nenhum arquivo de log foi criado até agora.", parent=self._raiz,
            )
            return
        abrir_no_sistema(log)


def abrir_no_sistema(caminho: Path) -> None:
    """Abre arquivo ou pasta no gerenciador do sistema. Nunca levanta.

    Falhar em abrir o gerenciador de arquivos não pode derrubar a janela do
    agente — no pior caso o caminho continua escrito na tela para o operador
    achar à mão.
    """
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", str(caminho)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            webbrowser.open(caminho.as_uri())
    except Exception as exc:  # noqa: BLE001 — comodidade, nunca derruba a janela
        logger.warning("Não foi possível abrir %s: %s", caminho, exc)
