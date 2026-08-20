"""Tests for importer/main.py — spec: _product/main.md"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from importer.main import (
    DEFAULT_CATEGORIES,
    _format_date,
    _tx_key,
)
from importer.parser import BNCTransaction
from importer.rounder import AccumulativeRounder
from importer.converter import to_usd


def make_sample_tx(
    date_val: date,
    time_val: str,
    debit: str = "1000",
    credit: str = "0",
    ref: str = "12345",
    desc: str = "TEST MERCHANT",
) -> BNCTransaction:
    return BNCTransaction(
        date=date_val,
        time=time_val,
        reference=ref,
        tx_type="Compra de POS DebitMC" if Decimal(debit) > 0 else "Tranf. entre Ctas. Internet",
        op_type="",
        description=desc,
        debit=Decimal(debit),
        credit=Decimal(credit),
        balance=Decimal("50000"),
        ref2="",
    )


class TestFormatDate:

    class WhenGivenAnIsoDateString:
        def test_formats_iso_date_to_dmy(self):
            assert _format_date("2026-07-24") == "24/07/2026"

        def test_formats_iso_datetime_to_dmy(self):
            assert _format_date("2026-07-24T18:00:00+00:00") == "24/07/2026"

    class WhenGivenInvalidOrNonIsoString:
        def test_returns_raw_string_fallback(self):
            assert _format_date("invalid-date") == "invalid-da"


class TestTxKey:

    class WhenReferenceIsPresent:
        def test_returns_reference_directly(self):
            tx = make_sample_tx(date(2026, 7, 24), "12:00:00", ref="819154846")
            assert _tx_key(tx) == "819154846"

    class WhenReferenceIsEmpty:
        def test_generates_deterministic_fallback_key(self):
            tx = make_sample_tx(date(2026, 7, 24), "11:48:55.826", ref="", debit="8234", desc="KEYLA PATRICIA SANTAMA")
            key = _tx_key(tx)
            assert key.startswith("2026-07-24_11:48:55.826_8234")
            assert "KEYLA" in key

        def test_identical_transactions_produce_identical_keys(self):
            tx1 = make_sample_tx(date(2026, 7, 24), "11:00:00", ref="", debit="500", desc="FARMACIA")
            tx2 = make_sample_tx(date(2026, 7, 24), "11:00:00", ref="", debit="500", desc="FARMACIA")
            assert _tx_key(tx1) == _tx_key(tx2)


class TestDefaultCategories:

    def test_contains_expected_21_categories(self):
        assert len(DEFAULT_CATEGORIES) == 21
        assert "Comida" in DEFAULT_CATEGORIES
        assert "Salud" in DEFAULT_CATEGORIES
        assert "Transporte" in DEFAULT_CATEGORIES
        assert "Diversión" in DEFAULT_CATEGORIES
        assert "Tecnología" in DEFAULT_CATEGORIES


class TestChronologicalSortingAndDynamicRate:

    def test_chronological_sort_orders_by_date_then_time(self):
        tx_old = make_sample_tx(date(2026, 7, 10), "09:00:00")
        tx_mid = make_sample_tx(date(2026, 7, 10), "18:00:00")
        tx_new = make_sample_tx(date(2026, 7, 24), "11:00:00")

        unsorted = [tx_new, tx_old, tx_mid]
        sorted_txs = sorted(unsorted, key=lambda t: (t.date, t.time))

        assert sorted_txs == [tx_old, tx_mid, tx_new]

    def test_dynamic_rate_applies_forward(self):
        """Transactions before rate change use rate 1; transactions after use rate 2."""
        tx1 = make_sample_tx(date(2026, 7, 10), "10:00:00", debit="8000")  # rate 800 -> $10
        # Rate change event occurs at July 15: new rate = 850
        tx2 = make_sample_tx(date(2026, 7, 20), "10:00:00", debit="8500")  # rate 850 -> $10

        rate1 = Decimal("800.00")
        rate2 = Decimal("850.00")

        rnd = AccumulativeRounder()
        usd1 = rnd.round(to_usd(tx1.debit, rate1))
        usd2 = rnd.round(to_usd(tx2.debit, rate2))

        assert usd1 == 10
        assert usd2 == 10
