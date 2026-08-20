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

            def test_works_for_pago_servicios(self, db):
                db.add_rule("MOVISTAR", "Hogar", "Movistar")
                tx = make_tx("Pago MOVISTAR BNCNet", "RECARGA / PAGO MOVISTAR : 04144967314", debit="2600")
                result = classify(tx, db)
                assert result.category == "Hogar"
                assert result.description == "Movistar"

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

            def test_unknown_service_payment_returns_none(self, db):
                tx = make_tx("Pago MOVISTAR BNCNet", "RECARGA / PAGO MOVISTAR : 04144967314", debit="2600")
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

        def test_abono_pago_movil_requires_prompt(self, db):
            tx = BNCTransaction(
                date=date(2026, 8, 19),
                time="11:32:33",
                reference="1444713301",
                tx_type="Abono Pago Movil BNC",
                op_type="P2POTR",
                description="PAGO MOVIL RECIBIDO",
                debit=Decimal("0"),
                credit=Decimal("45700"),
                balance=Decimal("89987.42"),
                ref2="",
            )
            result = classify(tx, db)
            assert result is not None
            assert result.requires_prompt is True

        def test_transferencia_recibida_requires_prompt(self, db):
            tx = BNCTransaction(
                date=date(2026, 7, 13),
                time="18:25:52",
                reference="182552143",
                tx_type="Tranf. entre Ctas. Internet",
                op_type="ABONO",
                description="TRANSFERENCIA RECIBIDA DEL BCO. NACIONAL DE CREDITO",
                debit=Decimal("0"),
                credit=Decimal("83464"),
                balance=Decimal("89260.62"),
                ref2="",
            )
            result = classify(tx, db)
            assert result is not None
            assert result.requires_prompt is True

        def test_any_positive_credit_requires_prompt(self, db):
            tx = BNCTransaction(
                date=date(2026, 7, 20),
                time="10:00:00",
                reference="999888",
                tx_type="Otro Ingreso",
                op_type="",
                description="ABONO ESPECIAL",
                debit=Decimal("0"),
                credit=Decimal("15000"),
                balance=Decimal("65000"),
                ref2="",
            )
            result = classify(tx, db)
            assert result is not None
            assert result.requires_prompt is True
