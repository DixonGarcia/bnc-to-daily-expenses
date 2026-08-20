"""BNC bank statement parser.

Reads the raw text content of a BNC export file and returns a filtered list
of BNCTransaction dataclasses. Rows that are not actionable expenses or
prompts (commissions, balance headers, incoming credits) are dropped silently.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass
class BNCTransaction:
    """A single transaction row from a BNC bank statement.

    Attributes:
        date: Transaction date.
        time: Transaction time as a string (e.g. "11:48:55.826").
        reference: BNC reference number used for deduplication. May be empty.
        tx_type: Transaction type (e.g. "Compra de POS DebitMC").
        op_type: Operation subtype code (e.g. "MAESTR", "P2PTSO"). May be empty.
        description: Raw merchant or transfer description from BNC.
        debit: Amount debited, always positive. Zero if this is a credit.
        credit: Amount credited, always positive. Zero if this is a debit.
        balance: Account balance after this transaction.
    """

    date: date
    time: str
    reference: str
    tx_type: str
    op_type: str
    description: str
    debit: Decimal
    credit: Decimal
    balance: Decimal


# Transaction types that are silently dropped — never expenses.
_IGNORED_TX_TYPES = {
    "Saldo Inicial",
}

_IGNORED_TX_SUBSTRINGS = (
    "Comisión",
)

_IGNORED_CREDIT_TYPES = (
    "Abono",
)


def parse(content: str) -> list[BNCTransaction]:
    """Parse the text content of a BNC bank statement.

    Skips the account header, the blank line, and the column-names line.
    Filters out ignored transaction types (commissions, balance rows, credits).
    Returns remaining rows as BNCTransaction dataclasses.

    Args:
        content: Full UTF-8 string content of the BNC .txt export file.

    Returns:
        List of BNCTransaction objects in file order. May be empty.
    """
    lines = content.splitlines()
    transactions = []

    for line in lines:
        # Skip header line, blank lines, and the column-names line
        if not line.strip():
            continue
        if line.startswith("Fecha\t") or "@" in line.split("\t")[0]:
            continue

        columns = line.split("\t")
        if len(columns) < 9:
            continue

        tx_type = columns[5].strip()
        op_type = columns[4].strip()
        description = columns[6].strip()
        raw_debit = columns[7].strip()
        raw_credit = columns[8].strip()
        raw_balance = columns[9].strip() if len(columns) > 9 else "0"

        # Apply filtering rules
        if tx_type in _IGNORED_TX_TYPES:
            continue
        if any(sub in tx_type for sub in _IGNORED_TX_SUBSTRINGS):
            continue

        credit = _to_decimal(raw_credit)
        if credit > 0 and any(sub in tx_type for sub in _IGNORED_CREDIT_TYPES):
            continue

        debit_raw = _to_decimal(raw_debit)
        debit = abs(debit_raw)

        raw_date = columns[0].strip()
        tx_date = _parse_date(raw_date)

        transactions.append(BNCTransaction(
            date=tx_date,
            time=columns[1].strip(),
            reference=columns[2].strip(),
            tx_type=tx_type,
            op_type=op_type,
            description=description,
            debit=debit,
            credit=credit,
            balance=_to_decimal(raw_balance),
        ))

    return transactions


def _to_decimal(value: str) -> Decimal:
    """Normalize a BNC numeric string to Decimal.

    Handles the Venezuelan comma-as-decimal-separator format:
      "-8.234,50" → Decimal("-8234.50")
      "-8234"     → Decimal("-8234")
      "0"         → Decimal("0")

    Args:
        value: Raw numeric string from the TSV.

    Returns:
        Normalized Decimal value.
    """
    normalized = value.strip().replace(".", "").replace(",", ".")
    if not normalized or normalized == "-":
        return Decimal("0")
    return Decimal(normalized)


def _parse_date(value: str) -> date:
    """Parse a BNC date string (DD/MM/YYYY) into a date object.

    Args:
        value: Date string e.g. "19/08/2026".

    Returns:
        Corresponding date object.
    """
    day, month, year = value.split("/")
    return date(int(year), int(month), int(day))
