# Module Spec: `converter.py` + `rounder.py`

---

## `converter.py`

### Responsibility
Converts a BsF amount to USD using a given exchange rate.
Pure function, no side effects, no database interaction.

### Public Interface

```python
def to_usd(amount_bsf: Decimal, rate: Decimal) -> Decimal:
    """Convert bolivares to USD using an exchange rate.

    Args:
        amount_bsf: Amount in bolivares (must be positive).
        rate: Exchange rate in Bs per USD (must be positive).

    Returns:
        Amount in USD, rounded to 2 decimal places.

    Raises:
        ValueError: If amount_bsf or rate is zero or negative.
    """
```

### Edge Cases
| Case | Expected |
|---|---|
| Normal conversion | `8234 / 845.88 → Decimal("9.73")` |
| `rate <= 0` | Raises `ValueError` |
| `amount_bsf <= 0` | Raises `ValueError` |

---

## `rounder.py`

### Responsibility
Rounds USD amounts to whole integers using ROUND_HALF_UP, carrying the
rounding residual forward to the next call so errors accumulate and cancel out
over a session rather than compounding in one direction.

### Example
```
rnd = AccumulativeRounder()
rnd.round(Decimal("9.73"))  →  10    residual: -0.27
rnd.round(Decimal("9.20"))  →   9    effective: 9.20 + (-0.27) = 8.93 → 9, residual: -0.07
rnd.round(Decimal("1.07"))  →   1    effective: 1.07 + (-0.07) = 1.00 → 1, residual: 0.00
```

### Public Interface

```python
class AccumulativeRounder:
    def round(self, amount_usd: Decimal) -> int:
        """Round amount to nearest integer, carrying residual to next call."""

    @property
    def residue(self) -> Decimal:
        """Current accumulated residual."""

    def reset(self) -> None:
        """Reset residual to zero. Call between import sessions."""
```

### Edge Cases
| Case | Expected |
|---|---|
| Exactly 0.5 | Rounds up (ROUND_HALF_UP): `0.5 → 1` |
| Residual accumulates across calls | Verified over 3+ consecutive calls |
| `reset()` clears residual | `residue == 0` after reset |
