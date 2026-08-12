#!/bin/bash
set -e

# Build Linux local (rápido, pra testar o binário empacotado antes de
# publicar uma tag). O build Windows é feito pelo GitHub Actions
# (.github/workflows/build_and_release.yml) — mesmo padrão do GS-PDV
# desktop (build_executables.sh).

echo "==> Limpando builds anteriores..."
rm -rf build/ dist/

echo "==> Compilando..."
source venv/bin/activate
pyinstaller --noconfirm gs-pdv-print-agent.spec

echo ""
echo "Pronto: dist/gs-pdv-print-agent"
echo "Rodar:  AGENT_TOKEN=... PRINTER_DEST=... ./dist/gs-pdv-print-agent"
echo "(config.json ao lado do binário também funciona — ver README.md)"
