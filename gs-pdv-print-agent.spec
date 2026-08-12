# -*- mode: python ; coding: utf-8 -*-
# Build local (Linux, rápido, pra testar o binário empacotado antes de
# publicar uma tag) — mesmo espírito do GS-PDV.spec do desktop. O CI
# (.github/workflows/build_and_release.yml) usa flags de linha de comando
# equivalentes, não este .spec — ao mudar uma opção de build, mudar nos
# DOIS lugares (mesma armadilha já documentada no CLAUDE.md do monorepo
# pro GS-PDV desktop).
import certifi

datas = [(certifi.where(), "certifi")]
hiddenimports = [
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "certifi",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
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
    # Console de propósito — é um serviço headless (FastAPI/uvicorn), não um
    # app com janela; o técnico precisa ver os logs ao rodar manualmente.
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
