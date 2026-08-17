"""Janela de configuração do agente (tkinter).

Existe porque configurar a impressora exigia editar ``config.json`` na mão ou
abrir o painel web — e o painel só ajuda depois que o token já está certo, o
que é justamente o passo que trava a primeira instalação. Com a janela, o
lojista abre o executável, cola o token e escolhe a impressora numa lista.

``tkinter`` é biblioteca padrão do Python: nada a mais para empacotar, e o
PyInstaller já sabe incluí-la. O import é **preguiçoso** (dentro das funções)
de propósito: uma máquina sem Tk instalado, ou um build headless, precisa
continuar imprimindo normalmente — a janela é conforto, o serviço é o produto.

Esta janela e o painel web gravam pelo MESMO ``save_printer_config``/
``save_token`` do ``config.py``. São duas portas para a mesma configuração,
nunca duas fontes de verdade.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from app.config import AgentConfig, save_printer_config, save_token
from app.printers import list_printers

logger = logging.getLogger(__name__)

#: Larguras oferecidas — as duas bitolas do parque de impressoras. O valor
#: precisa bater com o hardware: errar aqui é a causa clássica do "muito papel
#: em branco" (cada linha é preenchida até a largura configurada, e a sobra
#: estoura para uma segunda linha física quase vazia).
LARGURAS = [("80mm (48 colunas)", 48), ("58mm (32 colunas)", 32)]

_DESTINO_MANUAL = "Outro (digitar IP ou nome)"


def disponivel() -> bool:
    """Se dá para abrir janela nesta máquina (Tk presente e com display)."""
    try:
        import tkinter  # noqa: F401
    except Exception:  # noqa: BLE001 — Tk ausente é motivo legítimo de seguir headless
        return False
    return True


def abrir_configuracao(
    config: AgentConfig,
    ao_salvar: Optional[Callable[[], None]] = None,
    testar_impressao: Optional[Callable[[], None]] = None,
) -> None:
    """Abre a janela de configuração (bloqueia até fechar).

    Args:
        config: Configuração viva do agente — a janela grava nela e no arquivo.
        ao_salvar: Chamado depois de salvar, para a bandeja atualizar o rótulo
            de status sem esperar o próximo poll.
        testar_impressao: Ação do botão "Testar impressão"; omitir esconde o botão.
    """
    import tkinter as tk
    from tkinter import messagebox, ttk

    janela = tk.Tk()
    janela.title("GS PDV — Agente de Impressão")
    janela.resizable(False, False)

    moldura = ttk.Frame(janela, padding=16)
    moldura.grid(sticky="nsew")

    linha = 0

    def _rotulo(texto: str) -> None:
        nonlocal linha
        ttk.Label(moldura, text=texto).grid(row=linha, column=0, sticky="w", pady=(8, 2))
        linha += 1

    # ── Impressora ───────────────────────────────────────────────────────────
    _rotulo("Impressora")
    instaladas = list_printers()
    opcoes = [p.name for p in instaladas] + [_DESTINO_MANUAL]

    escolha_impressora = tk.StringVar()
    # Pré-seleciona o que já está configurado; se for algo que não está na lista
    # (impressora de rede por IP, por exemplo), cai no modo manual.
    if config.printer_dest and config.printer_dest in opcoes:
        escolha_impressora.set(config.printer_dest)
    elif config.printer_dest:
        escolha_impressora.set(_DESTINO_MANUAL)
    else:
        padrao = next((p.name for p in instaladas if p.is_default), None)
        escolha_impressora.set(padrao or _DESTINO_MANUAL)

    combo = ttk.Combobox(moldura, values=opcoes, textvariable=escolha_impressora, state="readonly", width=42)
    combo.grid(row=linha, column=0, sticky="we")
    linha += 1

    _rotulo("Endereço manual (IP de rede ou nome exato)")
    destino_manual = tk.StringVar(value=config.printer_dest)
    entrada_manual = ttk.Entry(moldura, textvariable=destino_manual, width=44)
    entrada_manual.grid(row=linha, column=0, sticky="we")
    linha += 1

    dica = ttk.Label(
        moldura,
        text="Impressora de rede não aparece na lista do sistema — use o endereço\n"
             "manual, no formato 192.168.1.50 ou 192.168.1.50:9100.",
        foreground="#666",
        justify="left",
    )
    dica.grid(row=linha, column=0, sticky="w", pady=(2, 0))
    linha += 1

    def _sincronizar_manual(*_args) -> None:
        """Campo manual só fica editável quando a escolha é "Outro"."""
        manual = escolha_impressora.get() == _DESTINO_MANUAL
        entrada_manual.configure(state="normal" if manual else "disabled")
        if not manual:
            destino_manual.set(escolha_impressora.get())

    escolha_impressora.trace_add("write", _sincronizar_manual)
    _sincronizar_manual()

    # ── Largura ──────────────────────────────────────────────────────────────
    _rotulo("Largura do papel")
    rotulo_por_valor = {valor: rotulo for rotulo, valor in LARGURAS}
    escolha_largura = tk.StringVar(
        value=rotulo_por_valor.get(config.chars_per_line, f"{config.chars_per_line} colunas"),
    )
    valores_largura = [rotulo for rotulo, _ in LARGURAS]
    if config.chars_per_line not in rotulo_por_valor:
        valores_largura.append(escolha_largura.get())
    ttk.Combobox(
        moldura, values=valores_largura, textvariable=escolha_largura, state="readonly", width=42,
    ).grid(row=linha, column=0, sticky="we")
    linha += 1

    # ── Token ────────────────────────────────────────────────────────────────
    _rotulo("Token do painel (Config. > Impressão)")
    token = tk.StringVar(value=config.token)
    ttk.Entry(moldura, textvariable=token, width=44, show="•").grid(row=linha, column=0, sticky="we")
    linha += 1

    status = ttk.Label(moldura, text="", foreground="#0a0")
    status.grid(row=linha, column=0, sticky="w", pady=(10, 0))
    linha += 1

    # ── Ações ────────────────────────────────────────────────────────────────
    def _salvar() -> None:
        destino = destino_manual.get().strip()
        rotulo_largura = escolha_largura.get()
        largura = next((v for r, v in LARGURAS if r == rotulo_largura), config.chars_per_line)

        novo_token = token.get().strip()
        if novo_token != config.token:
            save_token(config, novo_token)
        save_printer_config(config, destino, largura)

        status.configure(text="Configuração salva.", foreground="#0a0")
        logger.info("Configuração salva pela janela: %s (%d colunas)", destino or "(nenhuma)", largura)
        if ao_salvar:
            ao_salvar()

    def _testar() -> None:
        if not config.printer_dest:
            messagebox.showwarning("Sem impressora", "Salve uma impressora antes de testar.")
            return
        try:
            if testar_impressao:
                testar_impressao()
            status.configure(text="Teste enviado à impressora.", foreground="#0a0")
        except Exception as exc:  # noqa: BLE001 — a mensagem do erro é o resultado do teste
            status.configure(text=f"Falhou: {exc}", foreground="#a00")

    botoes = ttk.Frame(moldura)
    botoes.grid(row=linha, column=0, sticky="we", pady=(14, 0))
    ttk.Button(botoes, text="Salvar", command=_salvar).grid(row=0, column=0, padx=(0, 8))
    if testar_impressao:
        ttk.Button(botoes, text="Testar impressão", command=_testar).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(botoes, text="Fechar", command=janela.destroy).grid(row=0, column=2)

    janela.mainloop()


def pedir_token(config: AgentConfig) -> bool:
    """Janela mínima de primeira execução, só para colar o token.

    Substitui o ``input()`` no console quando não há console (build de bandeja):
    sem token, ``/print`` recusa tudo, então parar aqui é melhor que subir um
    agente que só vai falhar na primeira impressão sem dizer por quê.

    Returns:
        ``True`` se um token foi informado e salvo.
    """
    import tkinter as tk
    from tkinter import ttk

    janela = tk.Tk()
    janela.title("GS PDV — Primeira configuração")
    janela.resizable(False, False)

    moldura = ttk.Frame(janela, padding=16)
    moldura.grid()

    ttk.Label(
        moldura,
        text="Cole aqui o token do agente.\n\nEle fica no painel, em Config. > Impressão.",
        justify="left",
    ).grid(row=0, column=0, sticky="w", pady=(0, 10))

    valor = tk.StringVar()
    entrada = ttk.Entry(moldura, textvariable=valor, width=46)
    entrada.grid(row=1, column=0, sticky="we")
    entrada.focus_set()

    salvo = {"ok": False}

    def _confirmar() -> None:
        texto = valor.get().strip()
        if not texto:
            return
        save_token(config, texto)
        salvo["ok"] = True
        janela.destroy()

    entrada.bind("<Return>", lambda _e: _confirmar())

    botoes = ttk.Frame(moldura)
    botoes.grid(row=2, column=0, sticky="e", pady=(14, 0))
    ttk.Button(botoes, text="Salvar", command=_confirmar).grid(row=0, column=0, padx=(0, 8))
    ttk.Button(botoes, text="Agora não", command=janela.destroy).grid(row=0, column=1)

    janela.mainloop()
    return salvo["ok"]
