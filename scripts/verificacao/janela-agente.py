"""Verificação em ambiente gráfico real da janela do agente.

Existe por causa da lição da Fase D: aquela verificação rodou o binário
empacotado, confirmou o processo de pé e o `/printers` respondendo — e não
clicou em nada. Como no Linux o menu da bandeja nem existe, o clique era o
único gesto capaz de revelar o defeito, e ele escapou até o usuário reprovar
a release em uso real.

Aqui a janela é montada de verdade, com Tk de verdade, os eventos são
injetados de verdade (`event_generate`) e no fim sai uma **captura da janela**
para alguém olhar. Rodar com:

    ./venv/bin/python scripts/verificacao/janela-agente.py
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

CAPTURAS = Path(__file__).resolve().parent / "capturas"

resultados: list[tuple[bool, str]] = []

#: `event_generate` precisa do NOME da tecla, não do caractere, para
#: pontuação — "." é "period", ":" é "colon".
_NOMES_DE_TECLA = {".": "period", ":": "colon", "-": "minus", "_": "underscore"}


def _keysym(caractere: str) -> str:
    return _NOMES_DE_TECLA.get(caractere, caractere)


def conferir(condicao: bool, descricao: str) -> None:
    resultados.append((bool(condicao), descricao))
    print(f"{'  OK  ' if condicao else ' FALHA'} | {descricao}", flush=True)


def main() -> int:
    import tkinter as tk

    from app.agent_actions import AgentActions
    from app.config import AgentConfig
    from app import agent_actions
    from app.printers import PrinterInfo
    from app.ui.window import _MODO_REDE, AgentWindow

    pasta = CAPTURAS
    pasta.mkdir(parents=True, exist_ok=True)
    import os
    os.environ["GS_PRINT_AGENT_CONFIG"] = str(pasta / "config-verificacao.json")

    # Lista longa de propósito: o usuário tinha 23 impressoras e a busca do
    # combo `readonly` da v0.2.0 não deixava filtrar.
    agent_actions.list_printers = lambda: [
        PrinterInfo("HPRT-TP80K", True), PrinterInfo("POS-80"),
        *[PrinterInfo(f"Escritorio-{n:02d}") for n in range(1, 21)],
        PrinterInfo("Cozinha-Fundos"),
    ]

    actions = AgentActions(AgentConfig(token="", printer_dest="", chars_per_line=48))
    janela = AgentWindow(actions)

    raiz = tk.Tk()
    janela._raiz = raiz
    janela._montar()
    raiz.update()
    raiz.geometry("+80+60")
    raiz.update()

    conferir(janela._lista.size() == 23, "lista mostra as 23 impressoras")
    conferir("padrao do sistema" in janela._lista.get(0), "impressora padrão vem marcada e no topo")

    # ── Busca: digitação tecla a tecla, como o operador faz ──
    entrada_busca = [w for w in janela._painel_instalada.winfo_children()[0].winfo_children()
                     if isinstance(w, tk.ttk.Entry if hasattr(tk, "ttk") else object)]
    from tkinter import ttk
    entrada_busca = [w for w in janela._painel_instalada.winfo_children()[0].winfo_children()
                     if isinstance(w, ttk.Entry)][0]
    entrada_busca.focus_set()
    # Só `event_generate`: num Entry com foco o próprio Tk insere o caractere.
    # Somar um `insert` manual dobrava cada letra ("ccoozziinnhhaa") — foi o que
    # fez esta verificação reprovar sozinha na primeira rodada.
    for letra in "cozinha":
        entrada_busca.event_generate("<KeyPress>", keysym=letra)
        raiz.update()
        time.sleep(0.02)
    conferir(janela._busca.get() == "cozinha",
             f"digitação chegou ao campo sem duplicar (leu {janela._busca.get()!r})")

    conferir(janela._lista.size() == 1, "busca por 'cozinha' filtrou de 23 para 1")
    conferir("Cozinha" in janela._lista.get(0), "o resultado da busca é o esperado")

    # ── Escolher pela lista e salvar ──
    janela._lista.selection_set(0)
    janela._lista.event_generate("<<ListboxSelect>>")
    raiz.update()
    conferir(janela._destino_escolhido() == "Cozinha-Fundos", "seleção da lista vira destino")
    conferir("não salvo" in janela._lbl_status.cget("text"), "status avisa que há mudança não salva")

    actions.salvar_impressora(janela._destino_escolhido(), janela._largura.get())
    janela._pintar_status()
    raiz.update()
    conferir("não salvo" not in janela._lbl_status.cget("text"), "aviso some depois de salvar")

    # ── O caminho que o usuário não achou na v0.2.0: IP manual ──
    janela._modo.set(_MODO_REDE)
    janela._sincronizar_modo()
    raiz.update()
    conferir(bool(janela._painel_rede.winfo_manager()), "modo 'Impressora de rede' revela o campo de IP")

    entrada_ip = [w for w in janela._painel_rede.winfo_children() if isinstance(w, ttk.Entry)][0]
    entrada_ip.focus_set()
    for caractere in "192.168.1.50:9100":
        entrada_ip.event_generate("<KeyPress>", keysym=_keysym(caractere))
        raiz.update()
        time.sleep(0.01)
    conferir(janela._destino_escolhido() == "192.168.1.50:9100", "IP digitado vira o destino")

    janela._largura.set(32)
    actions.salvar_impressora(janela._destino_escolhido(), janela._largura.get())
    raiz.update()
    conferir(actions.config.printer_dest == "192.168.1.50:9100", "IP foi salvo na configuração")

    salvo = (pasta / "config-verificacao.json").read_text()
    conferir("192.168.1.50:9100" in salvo and '"chars_per_line": 32' in salvo,
             "config.json no disco tem o IP e a largura de 58mm")

    # ── Reabrir: a janela precisa lembrar que é impressora de rede ──
    janela._recarregar_da_config()
    raiz.update()
    conferir(janela._modo.get() == _MODO_REDE, "ao recarregar, abre no modo rede (IP não está em spooler nenhum)")

    # ── Mudança vinda do painel web chega na janela aberta ──
    janela._cancelar_observador = actions.observar(lambda: janela.agendar(janela._recarregar_da_config))
    actions.salvar_impressora("POS-80", 48)
    janela._drenar()
    raiz.update()
    conferir(janela._destino_escolhido() == "POS-80",
             "mudança feita pelo painel web reflete na janela aberta")

    # ── A fila: a bandeja nunca executa nada na própria thread ──
    marca = []
    comeco = time.monotonic()
    janela.agendar(lambda: marca.append(1))
    conferir(time.monotonic() - comeco < 0.05 and marca == [],
             "agendar retorna na hora sem executar (é o que impede o congelamento)")
    janela._drenar()
    conferir(marca == [1], "o laço da janela é quem executa a ação")

    # ── Captura para alguém OLHAR ──
    janela._modo.set("instalada")
    janela._sincronizar_modo()
    janela._busca.set("")
    janela._recarregar_da_config()
    janela._pintar_status()
    raiz.update()
    raiz.lift()
    raiz.update()
    time.sleep(0.6)

    destino = pasta / "janela-agente.png"
    subprocess.run(["import", "-window", str(raiz.winfo_id()), str(destino)], check=False)
    ok_captura = destino.exists() and destino.stat().st_size > 5000
    conferir(ok_captura, f"captura da janela gerada em {destino}")

    conferir("ATENÇÃO" in janela._lbl_status.cget("text"),
             "sem token, a barra de status avisa que a impressão vai ser recusada")
    actions.salvar_token("tok-de-teste")
    janela._drenar()
    janela._pintar_status()
    raiz.update()
    conferir("ATENÇÃO" not in janela._lbl_status.cget("text"),
             "com token, o aviso some")

    raiz.destroy()

    falhas = [d for ok, d in resultados if not ok]
    print(f"\n{len(resultados) - len(falhas)}/{len(resultados)} verificações passaram", flush=True)
    for descricao in falhas:
        print(f"  FALHOU: {descricao}", flush=True)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
