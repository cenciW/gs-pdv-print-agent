"""Verificação da bandeja: o gesto que a Fase D não executou.

A Fase D validou o processo de pé e o `/printers` respondendo, e por isso o
defeito escapou até o usuário reprovar a release. Aqui a bandeja sobe de
verdade e recebe um ButtonPress X **real** na janela do ícone — o mesmo
caminho do dedo do operador.

O que este roteiro prova nesta máquina (Linux/X11):

1. o ícone sobe e é adotado pelo gerenciador da bandeja;
2. o laço da janela **continua vivo** depois do clique (era o congelamento);
3. `suporta_menu()` diz a verdade sobre o X11 — onde o pystray descarta o menu.

O congelamento em si é do Windows, e está travado por
`tests/test_tray.py::test_item_de_menu_nao_executa_na_thread_da_bandeja`, que
independe de sistema operacional.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(RAIZ))

resultados: list[tuple[bool, str]] = []


def conferir(condicao: bool, descricao: str) -> None:
    resultados.append((bool(condicao), descricao))
    print(f"{'  OK  ' if condicao else ' FALHA'} | {descricao}", flush=True)


def main() -> int:
    os.environ["GS_PRINT_AGENT_CONFIG"] = str(
        Path(__file__).resolve().parent / "capturas" / "config-bandeja.json",
    )

    import tkinter as tk

    from app.agent_actions import AgentActions
    from app.config import AgentConfig
    from app.ui.tray import TrayAccessory, suporta_menu
    from app.ui.window import AgentWindow

    actions = AgentActions(AgentConfig(token="tok", printer_dest="192.168.1.50", chars_per_line=48))
    janela = AgentWindow(actions)
    raiz = tk.Tk()
    janela._raiz = raiz
    janela._montar()
    raiz.withdraw()

    aberturas = []
    bandeja = TrayAccessory(
        actions, agendar=janela.agendar, ao_mostrar_janela=lambda: aberturas.append(1),
    )
    conferir(bandeja.iniciar(), "ícone da bandeja subiu sem derrubar o processo")
    time.sleep(2.5)

    icone = bandeja._icone
    conferir(icone is not None and icone.visible, "ícone foi adotado pelo gerenciador da bandeja")

    # ── O clique de verdade ──
    import Xlib.display
    import Xlib.protocol.event
    import Xlib.X

    disp = Xlib.display.Display()
    evento = Xlib.protocol.event.ButtonPress(
        time=Xlib.X.CurrentTime, root=disp.screen().root, window=icone._window,
        same_screen=1, child=Xlib.X.NONE, root_x=0, root_y=0, event_x=0, event_y=0,
        state=0, detail=1,
    )
    icone._window.send_event(evento, propagate=False)
    disp.flush()
    time.sleep(1.0)

    # ── Prova de vida: o laço do Tk responde depois do clique ──
    vivo = []
    raiz.after(0, lambda: vivo.append(1))
    raiz.update()
    conferir(vivo == [1], "o laço da janela continua respondendo depois do clique na bandeja")

    # ── A fila continua funcionando (é por ela que o menu age) ──
    feito = []
    comeco = time.monotonic()
    bandeja._item(lambda: feito.append(1))()
    decorrido = time.monotonic() - comeco
    conferir(decorrido < 0.05, f"item de menu retornou em {decorrido*1000:.1f}ms (não segura a bandeja)")
    janela._drenar()
    conferir(feito == [1], "a ação do menu foi executada pelo laço da janela")

    # ── Honestidade sobre o X11 ──
    conferir(
        suporta_menu() is False,
        "suporta_menu() reconhece que o backend X11 desta máquina não desenha menu "
        "(era o defeito silencioso da v0.2.0)",
    )
    conferir(
        janela._ao_fechar_para_bandeja is None,
        "sem menu, a janela NÃO se esconde na bandeja (ficaria inalcançável)",
    )

    # ── Encerrar a bandeja não pode travar ──
    parou = threading.Event()
    threading.Thread(target=lambda: (bandeja.parar(), parou.set()), daemon=True).start()
    conferir(parou.wait(timeout=5), "bandeja parou sem travar")

    raiz.destroy()

    falhas = [d for ok, d in resultados if not ok]
    print(f"\n{len(resultados) - len(falhas)}/{len(resultados)} verificações passaram", flush=True)
    for descricao in falhas:
        print(f"  FALHOU: {descricao}", flush=True)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
