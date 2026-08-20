"""Transaction classifier for the BNC importer.

Classifies BNCTransaction objects using merchant rules from the database.
Returns ClassifiedTransaction when a match is found, or None when the
caller needs to prompt the user for a category and description.
"""
from __future__ import annotations

from dataclasses import dataclass

from importer.db import Database
from importer.parser import BNCTransaction

_EXPENSE_TYPES = {
    "Compra de POS DebitMC",
    "Cargo Pago Movil BNC",
    "Retiro de Biopago",
}

_PROMPT_TYPES = {
    "Credito Inmediato Recibido",
    "Crédito Inmediato Emitido",
}


@dataclass
class ClassifiedTransaction:
    """A BNCTransaction enriched with category and description.

    Attributes:
        tx: The original parsed transaction.
        category: Expense category (e.g. "Comida"). Empty for prompt transactions.
        description: Human-readable label for Daily Expenses 4. Empty for prompt transactions.
        requires_prompt: True when the user must decide what to do (funding events).
    """

    tx: BNCTransaction
    category: str
    description: str
    requires_prompt: bool


def classify(tx: BNCTransaction, db: Database) -> ClassifiedTransaction | None:
    """Attempt to classify a BNC transaction using stored merchant rules.

    For expense transaction types (POS, Pago Movil, Biopago):
      - If a matching rule exists → returns ClassifiedTransaction
      - If no rule matches → returns None (caller must prompt user)

    For prompt transaction types (Credito Inmediato):
      - Returns ClassifiedTransaction with requires_prompt=True and
        empty category/description (caller handles the prompt).

    Args:
        tx: A parsed BNCTransaction from parser.py.
        db: Database instance to query merchant_rules.

    Returns:
        ClassifiedTransaction if classified or prompt-required, None if unknown merchant.
    """
    if tx.tx_type in _PROMPT_TYPES:
        return ClassifiedTransaction(
            tx=tx,
            category="",
            description="",
            requires_prompt=True,
        )

    if tx.debit > 0:
        rule = db.find_rule(tx.description)
        if rule is None:
            return None
        return ClassifiedTransaction(
            tx=tx,
            category=rule.category,
            description=rule.description,
            requires_prompt=False,
        )

    return None
