"""BsF to USD currency converter for the BNC importer."""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP


def to_usd(amount_bsf: Decimal, rate: Decimal) -> Decimal:
    """Convert bolivares to USD using an exchange rate.

    Args:
        amount_bsf: Amount in bolivares (must be positive).
        rate: Exchange rate in Bs per USD (must be positive).

    Returns:
        Amount in USD rounded to 2 decimal places.

    Raises:
        ValueError: If amount_bsf or rate is zero or negative.
    """
    if amount_bsf <= 0:
        raise ValueError(f"amount_bsf must be positive, got {amount_bsf}.")
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}.")
    return (amount_bsf / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
