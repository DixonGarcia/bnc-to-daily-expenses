"""Tests for importer/classifier.py — spec: _product/classifier.md"""
from __future__ import annotations

from decimal import Decimal
from datetime import date

import pytest

from importer.classifier import ClassifiedTransaction, classify
from importer.parser import BNCTransaction


def make_tx(tx_type: str, description: str = "SOME MERCHANT", debit: str = "1000") -> BNCTransaction:
    """Helper to build a BNCTransaction for testing."""
    return BNCTransaction(
        date=date(2026, 8, 19),
        time="12:00:00",
        reference="123456",
        tx_type=tx_type,
        op_type="",
        description=description,
        debit=Decimal(debit),
        credit=Decimal("0"),
        balance=Decimal("50000"),
    )


class TestClassify:

    class WhenTransactionIsAnExpense:

        class AndARuleMatches:
            def test_returns_classified_transaction(self, db):
                db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
                tx = make_tx("Compra de POS DebitMC", "KEYLA PATRICIA SANTAMA COJEDES")
                result = classify(tx, db)
                assert isinstance(result, ClassifiedTransaction)

            def test_category_comes_from_rule(self, db):
                db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
                tx = make_tx("Compra de POS DebitMC", "KEYLA PATRICIA SANTAMA COJEDES")
                result = classify(tx, db)
                assert result.category == "Comida"

            def test_description_comes_from_rule(self, db):
                db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
                tx = make_tx("Compra de POS DebitMC", "KEYLA PATRICIA SANTAMA COJEDES")
                result = classify(tx, db)
                assert result.description == "Charcutería"

            def test_original_tx_is_preserved(self, db):
                db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
                tx = make_tx("Compra de POS DebitMC", "KEYLA PATRICIA SANTAMA COJEDES")
                result = classify(tx, db)
                assert result.tx is tx

            def test_requires_prompt_is_false(self, db):
                db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
                tx = make_tx("Compra de POS DebitMC", "KEYLA PATRICIA SANTAMA COJEDES")
                result = classify(tx, db)
                assert result.requires_prompt is False

            def test_works_for_cargo_pago_movil(self, db):
                db.add_rule("Café Panadería", "Comida", "Panadería")
                tx = make_tx("Cargo Pago Movil BNC", "TELF.:584120000000 Café Panadería Tamanaco")
                result = classify(tx, db)
                assert result.description == "Panadería"

            def test_works_for_retiro_biopago(self, db):
                db.add_rule("FARMAIGNACIO", "Salud", "Farmacia Ignacio")
                tx = make_tx("Retiro de Biopago", "FARMAIGNACIO TINAQUILL CCS NOROESTE")
                result = classify(tx, db)
                assert result.description == "Farmacia Ignacio"

        class AndNoRuleMatches:
            def test_returns_none(self, db):
                tx = make_tx("Compra de POS DebitMC", "UNKNOWN MERCHANT XYZ")
                result = classify(tx, db)
                assert result is None

            def test_returns_none_even_with_other_rules_in_db(self, db):
                db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
                tx = make_tx("Compra de POS DebitMC", "MULTIMARCAS 2022 C A SAN CARLOS")
                result = classify(tx, db)
                assert result is None

    class WhenTransactionRequiresPrompt:

        def test_credito_inmediato_recibido_returns_classified(self, db):
            tx = make_tx("Credito Inmediato Recibido")
            result = classify(tx, db)
            assert isinstance(result, ClassifiedTransaction)

        def test_credito_inmediato_recibido_requires_prompt(self, db):
            tx = make_tx("Credito Inmediato Recibido")
            result = classify(tx, db)
            assert result.requires_prompt is True

        def test_credito_inmediato_recibido_has_empty_category(self, db):
            tx = make_tx("Credito Inmediato Recibido")
            result = classify(tx, db)
            assert result.category == ""

        def test_credito_inmediato_emitido_requires_prompt(self, db):
            tx = make_tx("Crédito Inmediato Emitido")
            result = classify(tx, db)
            assert result.requires_prompt is True

        def test_prompt_tx_original_tx_is_preserved(self, db):
            tx = make_tx("Credito Inmediato Recibido")
            result = classify(tx, db)
            assert result.tx is tx
