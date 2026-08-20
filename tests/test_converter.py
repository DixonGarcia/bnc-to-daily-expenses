"""Tests for importer/converter.py — spec: _product/converter-rounder.md"""
from __future__ import annotations

from decimal import Decimal

import pytest

from importer.converter import to_usd


class TestToUsd:

    class WhenInputIsValid:
        def test_converts_bsf_to_usd(self):
            result = to_usd(Decimal("8234"), Decimal("845.88"))
            assert result == Decimal("9.73")

        def test_returns_decimal(self):
            result = to_usd(Decimal("8234"), Decimal("845.88"))
            assert isinstance(result, Decimal)

        def test_rounds_to_two_decimal_places(self):
            result = to_usd(Decimal("900"), Decimal("845.88"))
            # 900 / 845.88 = 1.064... → 1.06
            assert result == Decimal("1.06")

        def test_handles_decimal_rate(self):
            result = to_usd(Decimal("1000"), Decimal("500.00"))
            assert result == Decimal("2.00")

    class WhenInputIsInvalid:
        def test_raises_when_rate_is_zero(self):
            with pytest.raises(ValueError, match="positive"):
                to_usd(Decimal("1000"), Decimal("0"))

        def test_raises_when_rate_is_negative(self):
            with pytest.raises(ValueError, match="positive"):
                to_usd(Decimal("1000"), Decimal("-845.88"))

        def test_raises_when_amount_is_zero(self):
            with pytest.raises(ValueError, match="positive"):
                to_usd(Decimal("0"), Decimal("845.88"))

        def test_raises_when_amount_is_negative(self):
            with pytest.raises(ValueError, match="positive"):
                to_usd(Decimal("-100"), Decimal("845.88"))
