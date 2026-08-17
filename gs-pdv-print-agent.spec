# -*- mode: python ; coding: utf-8 -*-
# Build local (Linux, rápido, pra testar o binário empacotado antes de
# publicar uma tag) — mesmo espírito do GS-PDV.spec do desktop. O CI
# (.github/workflows/build_and_release.yml) usa flags de linha de comando
# equivalentes, não este .spec — ao mudar uma opção de build, mudar nos
# DOIS lugares (mesma armadilha já documentada no CLAUDE.md do monorepo
# pro GS-PDV desktop).
import certifi
from PyInstaller.utils.hooks import collect_all

# `--hidden-import tkinter` declara o MÓDULO; o que faz a janela abrir são os
# DADOS do Tcl/Tk (tcl86t.dll, tk86t.dll, pastas tcl/ e tk/). Com o import
# preguiçoso — dentro das funções, para máquina sem ambiente gráfico seguir
# imprimindo — a análise estática pode não disparar o hook que copia esses
# arquivos: o build passa, o .exe sobe, e a janela falha só na máquina do
# cliente. Agora que a janela é a interface PRINCIPAL, isso deixou de ser
# cosmético. `collect_all` garante módulo + binários + dados.
tk_datas, tk_binaries, tk_hidden = collect_all("tkinter")

datas = [(certifi.where(), "certifi"), *tk_datas]
hiddenimports = [
    *tk_hidden,
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "certifi",
    # Bandeja e janela (2026-08-17). Os dois são importados de forma
    # preguiçosa dentro de funções, então o PyInstaller não os enxerga
    # sozinho na análise estática — sem declarar aqui, o executável sai sem
    # ícone e sem janela, e só se descobre no computador do cliente.
    "pystray",
    "PIL.Image",
    "PIL.ImageDraw",
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=tk_binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="gs-pdv-print-agent",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    # Sem console (2026-08-17): o agente virou aplicação de bandeja, e um
    # console preto aberto atrás do ícone assusta o operador de loja e é
    # fechado por engano — derrubando a impressão da loja sem ninguém
    # entender por quê.
    #
    # Isto só é seguro porque o log passou a ir para ARQUIVO
    # (app/logging_setup.py, ao lado do config.json). Sem console e sem
    # arquivo, diagnosticar problema no Windows vira adivinhação — foi o que
    # deixou o ".exe não abre nada" da SESSAO-PDV-WEB §21 sem causa raiz.
    #
    # Quem precisa de serviço headless de verdade roda com `--headless`
    # (systemd/serviço), que não abre bandeja nem janela.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
