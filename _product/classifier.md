# Module Spec: `classifier.py`

## Responsibility

Takes a `BNCTransaction` and a `Database` instance and attempts to classify
the transaction into a known category and description using the merchant rules
stored in the database.

Returns a `ClassifiedTransaction` if a rule matches, or `None` if not — which
signals the caller (main.py) to prompt the user interactively.

---

## Design

The classifier is a thin layer on top of `db.find_rule()`. It does not contain
matching logic itself — that belongs to the database layer.

Its main job is:
1. Determine if the transaction type is one that should be classified as an expense
2. Determine if the transaction type requires an interactive prompt (funding events)
3. Apply the rule match and wrap the result in a `ClassifiedTransaction`

---

## Transaction Categories

### Expense transactions — classify against merchant rules
- Any transaction with `debit > 0` (e.g. `"Compra de POS DebitMC"`, `"Cargo Pago Movil BNC"`, `"Retiro de Biopago"`, `"Pago MOVISTAR BNCNet"`, etc.)

### Prompt transactions — returned with `requires_prompt=True`
- Any transaction with `credit > 0` (e.g. `"Credito Inmediato Recibido"`, `"Abono Pago Movil"`, `"Tranf. entre Ctas. Internet"`) — may be a Binance → BNC funding event
- `"Crédito Inmediato Emitido"` — outgoing transfer, user decides

### All other types — should never reach the classifier (already filtered by parser)

---

## Output: `ClassifiedTransaction` dataclass

```python
@dataclass
class ClassifiedTransaction:
    tx: BNCTransaction          # original transaction
    category: str               # e.g. "Comida", "Salud"
    description: str            # human-readable label e.g. "Charcutería"
    requires_prompt: bool       # True for Credito Inmediato types
```

---

## Public Interface

```python
def classify(tx: BNCTransaction, db: Database) -> ClassifiedTransaction | None:
    """Attempt to classify a BNC transaction using stored merchant rules.

    For expense transaction types (POS, Pago Movil, Biopago):
      - If a matching rule exists → returns ClassifiedTransaction
      - If no rule matches → returns None (caller must prompt user)

    For prompt transaction types (Credito Inmediato):
      - Returns ClassifiedTransaction with requires_prompt=True,
        category="" and description="" (caller handles the prompt)

    Args:
        tx: A parsed BNCTransaction from parser.py.
        db: Database instance to query merchant_rules.

    Returns:
        ClassifiedTransaction if classified or prompt-required, None if unknown merchant.
    """
```

---

## Edge Cases

| Case | Expected behavior |
|---|---|
| Expense tx with matching rule | Returns `ClassifiedTransaction` with rule's category/description |
| Expense tx with no matching rule | Returns `None` |
| `Credito Inmediato Recibido` | Returns `ClassifiedTransaction(requires_prompt=True, category="", description="")` |
| `Crédito Inmediato Emitido` | Returns `ClassifiedTransaction(requires_prompt=True, category="", description="")` |
