"""Tests for importer/rounder.py — spec: _product/converter-rounder.md"""
from __future__ import annotations

from decimal import Decimal

from importer.rounder import AccumulativeRounder


class TestAccumulativeRounder:

    class WhenRoundingASingleValue:
        def test_rounds_up_at_half(self):
            rnd = AccumulativeRounder()
            assert rnd.round(Decimal("0.5")) == 1

        def test_rounds_down_below_half(self):
            rnd = AccumulativeRounder()
            assert rnd.round(Decimal("0.4")) == 0

        def test_rounds_up_above_half(self):
            rnd = AccumulativeRounder()
            assert rnd.round(Decimal("9.73")) == 10

        def test_residue_is_set_after_first_call(self):
            rnd = AccumulativeRounder()
            rnd.round(Decimal("9.73"))
            assert rnd.residue == Decimal("-0.27")

    class WhenResidualAccumulates:
        def test_second_call_uses_residual(self):
            rnd = AccumulativeRounder()
            rnd.round(Decimal("9.73"))   # residual: -0.27
            result = rnd.round(Decimal("9.20"))  # effective: 8.93 → 9
            assert result == 9

        def test_residual_after_two_calls(self):
            rnd = AccumulativeRounder()
            rnd.round(Decimal("9.73"))   # residual: -0.27
            rnd.round(Decimal("9.20"))   # effective: 8.93 → 9, residual: -0.07
            assert rnd.residue == Decimal("8.93") - Decimal("9")

        def test_accumulates_over_multiple_calls(self):
            rnd = AccumulativeRounder()
            # 1.60 → 2 (residual -0.40)
            # 1.60 + (-0.40) = 1.20 → 1 (residual +0.20)
            # 1.60 + 0.20 = 1.80 → 2 (residual -0.20)
            results = [rnd.round(Decimal("1.60")) for _ in range(3)]
            assert results == [2, 1, 2]

        def test_residual_carries_positive_too(self):
            rnd = AccumulativeRounder()
            rnd.round(Decimal("1.40"))   # rounds to 1, residual: +0.40
            result = rnd.round(Decimal("1.20"))  # effective: 1.60 → 2
            assert result == 2

    class WhenReset:
        def test_reset_clears_residual(self):
            rnd = AccumulativeRounder()
            rnd.round(Decimal("9.73"))
            rnd.reset()
            assert rnd.residue == Decimal("0")

        def test_after_reset_behaves_like_new_instance(self):
            rnd = AccumulativeRounder()
            rnd.round(Decimal("9.73"))
            rnd.reset()
            result = rnd.round(Decimal("9.73"))
            assert result == 10
            assert rnd.residue == Decimal("-0.27")
