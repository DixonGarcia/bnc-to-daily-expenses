"""Accumulative ROUND_HALF_UP rounder for the BNC importer.

Rounds USD amounts to whole integers while carrying the rounding residual
forward to the next call, so errors distribute across transactions rather
than compounding in one direction.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


class AccumulativeRounder:
    """Rounds USD Decimal amounts to integers, accumulating residual across calls.

    Example::

        rnd = AccumulativeRounder()
        rnd.round(Decimal("9.73"))  # → 10  (residual: -0.27)
        rnd.round(Decimal("9.20"))  # → 9   (effective 8.93 → 9, residual: -0.07)
        rnd.round(Decimal("1.07"))  # → 1   (effective 1.00 → 1, residual: 0.00)
    """

    def __init__(self) -> None:
        self._residue: Decimal = Decimal("0")

    def round(self, amount_usd: Decimal) -> int:
        """Round amount to nearest integer, carrying residual to next call.

        Args:
            amount_usd: Amount in USD (positive Decimal).

        Returns:
            Rounded integer value.
        """
        adjusted = amount_usd + self._residue
        rounded = int(adjusted.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        self._residue = adjusted - Decimal(rounded)
        return rounded

    @property
    def residue(self) -> Decimal:
        """Current accumulated rounding residual."""
        return self._residue

    def reset(self) -> None:
        """Reset residual to zero. Call between import sessions."""
        self._residue = Decimal("0")
