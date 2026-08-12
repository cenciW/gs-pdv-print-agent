"""Payload ESC/POS — portado **verbatim** de ``_wrap_escpos`` no GS-PDV
desktop (``GS-PDV/app/presentation/main_window.py``).

Não mudar esta sequência de bytes sem reler CLAUDE.md → "Impressão de Cupom
(margem ESC/POS)" primeiro: cada comando aqui corrige um bug real já
depurado (linha quebrada, deslocamento à direita) e a causa raiz não é óbvia
por inspeção — já foram gastas sessões inteiras de diagnóstico nisso no
desktop. Reaproveitar o byte a byte é o objetivo explícito da Fase 3, não
reinterpretar.
"""

from __future__ import annotations

# GS L 0 0 — margem esquerda = 0. A área imprimível do papel térmico (80mm →
# ~576 dots) já é exatamente o que `chars_line=48` (ver sale_receipt.py)
# preenche; qualquer margem > 0 empurra o conteúdo pra fora da borda direita
# e a impressora quebra os últimos caracteres (tipicamente os centavos) pra
# linha de baixo.
_SET_LEFT_MARGIN = b"\x1D\x4C\x00\x00"


def wrap_escpos(receipt_text: str) -> bytes:
    """Empacota o texto do cupom (monoespaçado) no payload ESC/POS de impressão.

    Sequência:
        ESC @      reset da impressora
        ESC a 0    justificação à esquerda (evita deslocamento por estado
                   residual de justificação centralizada da impressora)
        GS L 0 0   margem esquerda = 0 (nunca centralizar pela largura física)
        ...texto...
        \\n\\n\\n    avanço de papel antes do corte
        GS V 0     corte total do papel

    Args:
        receipt_text: Texto monoespaçado já formatado (ver
            ``app.core.entities.sale_receipt.build_sale_receipt_text`` do
            ``gs-menu-server`` — o agente não formata nada, só embrulha).

    Returns:
        Bytes prontos para envio cru à impressora térmica.
    """
    return (
        b"\x1B\x40"  # ESC @
        + b"\x1B\x61\x00"  # ESC a 0
        + _SET_LEFT_MARGIN
        + receipt_text.encode("cp850", errors="replace")
        + b"\n\n\n"
        + b"\x1D\x56\x00"  # GS V 0
    )
