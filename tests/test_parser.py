"""Tests for importer/parser.py — spec: _product/parser.md"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from importer.parser import BNCTransaction, parse


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_content():
    """Raw content of the BNC example input file."""
    return Path("input example.txt").read_text(encoding="utf-8")


@pytest.fixture
def charcuteria_row():
    """Single TSV data row for the Charcutería purchase."""
    return (
        "01910253022100010934@GARCIA DIAZ DIXON EFRAIN@25 ULTIMOS MOVIMIENTOS\r\n"
        "\r\n"
        "Fecha\tHora\tReferencia\tCod. Transacción\tTipo Transacción\tTip. Operación\t"
        "Descripción\tDebe\tHaber\tSaldo\tReferencia 2\r\n"
        "19/08/2026\t11:48:55.826\t819154846\t377\tMAESTR\tCompra de POS DebitMC\t"
        "KEYLA PATRICIA SANTAMA COJEDES       VEN ZONA= BANCO:010403\t-8234\t0\t68253,42\t123186\r\n"
    )


@pytest.fixture
def commission_row():
    """Single TSV data row for a Pago Movil commission (should be filtered)."""
    return (
        "01910253022100010934@GARCIA DIAZ DIXON EFRAIN@25 ULTIMOS MOVIMIENTOS\r\n"
        "\r\n"
        "Fecha\tHora\tReferencia\tCod. Transacción\tTipo Transacción\tTip. Operación\t"
        "Descripción\tDebe\tHaber\tSaldo\tReferencia 2\r\n"
        "19/08/2026\t11:20:45.106\t862470815\t751\tP2PCSO\tComisión Pago Movil\t"
        "TELF.:584127781247 CED.:016774620 BANCO:0102 Café Panadería\t-14\t0\t44287,42\t584124553435\r\n"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParse:

    class WhenGivenTheExampleFile:
        def test_returns_a_list(self, sample_content):
            result = parse(sample_content)
            assert isinstance(result, list)

        def test_all_items_are_bnc_transactions(self, sample_content):
            result = parse(sample_content)
            assert all(isinstance(tx, BNCTransaction) for tx in result)

        def test_filters_out_commissions(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert not any("Comisión" in t for t in tx_types)

        def test_filters_out_saldo_inicial(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Saldo Inicial" not in tx_types

        def test_filters_out_abono_pago_movil(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Abono Pago Movil BNC" not in tx_types

        def test_keeps_compra_pos(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Compra de POS DebitMC" in tx_types

        def test_keeps_cargo_pago_movil(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Cargo Pago Movil BNC" in tx_types

        def test_keeps_retiro_biopago(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Retiro de Biopago" in tx_types

        def test_keeps_credito_inmediato_recibido(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Credito Inmediato Recibido" in tx_types

        def test_keeps_credito_inmediato_emitido(self, sample_content):
            result = parse(sample_content)
            tx_types = [tx.tx_type for tx in result]
            assert "Crédito Inmediato Emitido" in tx_types

    class WhenParsingAKnownTransaction:
        def test_parses_date_correctly(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].date == date(2026, 8, 19)

        def test_parses_time_as_string(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].time == "11:48:55.826"

        def test_parses_reference(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].reference == "819154846"

        def test_parses_tx_type(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].tx_type == "Compra de POS DebitMC"

        def test_parses_op_type(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].op_type == "MAESTR"

        def test_parses_description(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert "KEYLA PATRICIA SANTAMA" in result[0].description

        def test_debit_is_positive_decimal(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].debit == Decimal("8234")
            assert result[0].debit > 0

        def test_credit_is_zero(self, charcuteria_row):
            result = parse(charcuteria_row)
            assert result[0].credit == Decimal("0")

    class WhenHandlingEdgeCases:
        def test_returns_empty_list_for_header_only(self):
            header_only = (
                "01910253022100010934@GARCIA DIAZ DIXON EFRAIN@25 ULTIMOS MOVIMIENTOS\r\n"
                "\r\n"
                "Fecha\tHora\tReferencia\tCod. Transacción\tTipo Transacción\tTip. Operación\t"
                "Descripción\tDebe\tHaber\tSaldo\tReferencia 2\r\n"
            )
            assert parse(header_only) == []

        def test_skips_trailing_empty_line(self, sample_content):
            # The example file ends with an empty line — should not crash
            result = parse(sample_content)
            assert all(isinstance(tx, BNCTransaction) for tx in result)

        def test_handles_comma_decimal_in_debit(self):
            """Debit value with comma decimal separator e.g. -4272,08"""
            content = (
                "01910253022100010934@GARCIA DIAZ DIXON EFRAIN@25 ULTIMOS MOVIMIENTOS\r\n"
                "\r\n"
                "Fecha\tHora\tReferencia\tCod. Transacción\tTipo Transacción\tTip. Operación\t"
                "Descripción\tDebe\tHaber\tSaldo\tReferencia 2\r\n"
                "19/08/2026\t11:53:11.561\t819155311\t393\t\tRetiro de Biopago\t"
                "FARMAIGNACIO\t-4272,08\t0\t63981,34\t987321\r\n"
            )
            result = parse(content)
            assert result[0].debit == Decimal("4272.08")

        def test_handles_empty_reference(self):
            """Saldo Inicial row has empty reference — filtered out, so test with valid tx."""
            content = (
                "01910253022100010934@GARCIA DIAZ DIXON EFRAIN@25 ULTIMOS MOVIMIENTOS\r\n"
                "\r\n"
                "Fecha\tHora\tReferencia\tCod. Transacción\tTipo Transacción\tTip. Operación\t"
                "Descripción\tDebe\tHaber\tSaldo\tReferencia 2\r\n"
                "19/08/2026\t11:48:55.826\t\t377\t\tCompra de POS DebitMC\t"
                "KEYLA PATRICIA\t-8234\t0\t68253,42\t123186\r\n"
            )
            result = parse(content)
            assert result[0].reference == ""

        def test_commission_row_is_filtered(self, commission_row):
            assert parse(commission_row) == []
