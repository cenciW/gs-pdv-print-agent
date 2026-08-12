from app.escpos import wrap_escpos


def test_wrap_escpos_exact_byte_sequence():
    """Sequência precisa casar byte a byte com o payload já depurado no
    GS-PDV desktop (ver CLAUDE.md "Impressão de Cupom") — qualquer desvio
    aqui reintroduz um bug de margem/justificação já resolvido antes.
    """
    payload = wrap_escpos("ABC")
    assert payload == (
        b"\x1B\x40"          # ESC @  reset
        + b"\x1B\x61\x00"    # ESC a 0  justifica à esquerda
        + b"\x1D\x4C\x00\x00"  # GS L 0 0  margem esquerda = 0
        + b"ABC"
        + b"\n\n\n"
        + b"\x1D\x56\x00"    # GS V 0  corte
    )


def test_wrap_escpos_encodes_accented_text_as_cp850():
    payload = wrap_escpos("Não fiscal — Café")
    # cp850 é a codepage padrão de impressoras ESC/POS pra acentuação PT-BR.
    assert "Não fiscal — Café".encode("cp850", errors="replace") in payload


def test_wrap_escpos_never_raises_on_unencodable_char():
    # errors="replace" — impressão nunca deve quebrar por causa de um
    # caractere fora da codepage (ex.: emoji colado num nome de produto).
    payload = wrap_escpos("Produto 🍔")
    assert isinstance(payload, bytes)
