"""SQLite database layer for the BNC importer.

This is the only module allowed to read or write the database.
All other modules interact with storage exclusively via the Database class.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class MerchantRule:
    """A rule that maps a raw BNC description pattern to a category and label.

    Attributes:
        id: Auto-assigned primary key.
        pattern: Case-insensitive substring or regex to match against raw descriptions.
        category: Expense category (e.g. "Comida", "Salud").
        description: Human-readable label loaded into Daily Expenses 4.
        is_regex: True if pattern should be treated as a regular expression.
    """

    id: int
    pattern: str
    category: str
    description: str
    is_regex: bool


@dataclass
class ExchangeRate:
    """A recorded Binance → BNC transfer exchange rate.

    Attributes:
        id: Auto-assigned primary key.
        rate: Bolivares per USD (e.g. 845.88).
        registered_at: ISO 8601 UTC datetime string when the rate was recorded.
        notes: Optional free-text note (e.g. "100 USDT → BNC").
    """

    id: int
    rate: float
    registered_at: str
    notes: str


class Database:
    """Manages the local SQLite database for the BNC importer.

    Creates the database file and all required tables automatically on first
    instantiation. Safe to instantiate multiple times on the same file.

    Args:
        path: Path to the SQLite database file.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._path))
        self._connection.row_factory = sqlite3.Row
        self._create_tables()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _create_tables(self) -> None:
        with self._connection:
            self._connection.executescript("""
                CREATE TABLE IF NOT EXISTS merchant_rules (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern     TEXT UNIQUE NOT NULL,
                    category    TEXT NOT NULL,
                    description TEXT NOT NULL,
                    is_regex    INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS processed_transactions (
                    reference    TEXT PRIMARY KEY,
                    processed_at TEXT NOT NULL,
                    amount_usd   INTEGER NOT NULL,
                    description  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exchange_rates (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    rate          REAL NOT NULL,
                    registered_at TEXT NOT NULL,
                    notes         TEXT NOT NULL DEFAULT ''
                );
            """)

    # ------------------------------------------------------------------
    # Merchant Rules
    # ------------------------------------------------------------------

    def add_rule(
        self,
        pattern: str,
        category: str,
        description: str,
        is_regex: bool = False,
    ) -> MerchantRule:
        """Insert a new merchant rule.

        Args:
            pattern: Case-insensitive substring or regex to match.
            category: Expense category (e.g. "Comida").
            description: Human-readable label for Daily Expenses 4.
            is_regex: Whether pattern is a regular expression.

        Returns:
            The newly created MerchantRule.

        Raises:
            ValueError: If a rule with the same pattern already exists.
        """
        try:
            with self._connection:
                cursor = self._connection.execute(
                    "INSERT INTO merchant_rules (pattern, category, description, is_regex) "
                    "VALUES (?, ?, ?, ?)",
                    (pattern, category, description, int(is_regex)),
                )
                return MerchantRule(
                    id=cursor.lastrowid,
                    pattern=pattern,
                    category=category,
                    description=description,
                    is_regex=is_regex,
                )
        except sqlite3.IntegrityError:
            raise ValueError(f"Rule with pattern '{pattern}' already exists.")

    def find_rule(self, raw_description: str) -> MerchantRule | None:
        """Find the first rule whose pattern matches the raw BNC description.

        Literal rules are evaluated before regex rules. Matching is
        case-insensitive. Returns None if no rule matches.

        Args:
            raw_description: The raw description field from the BNC statement.

        Returns:
            The first matching MerchantRule, or None.
        """
        rows = self._connection.execute(
            "SELECT * FROM merchant_rules ORDER BY is_regex ASC, id ASC"
        ).fetchall()

        needle = raw_description.lower()

        for row in rows:
            pattern = row["pattern"]
            if row["is_regex"]:
                if re.search(pattern, raw_description, re.IGNORECASE):
                    return self._row_to_rule(row)
            else:
                if pattern.lower() in needle:
                    return self._row_to_rule(row)

        return None

    def all_rules(self) -> list[MerchantRule]:
        """Return all merchant rules ordered by id.

        Returns:
            List of MerchantRule dataclasses, possibly empty.
        """
        rows = self._connection.execute(
            "SELECT * FROM merchant_rules ORDER BY id ASC"
        ).fetchall()
        return [self._row_to_rule(row) for row in rows]

    @staticmethod
    def _row_to_rule(row: sqlite3.Row) -> MerchantRule:
        return MerchantRule(
            id=row["id"],
            pattern=row["pattern"],
            category=row["category"],
            description=row["description"],
            is_regex=bool(row["is_regex"]),
        )

    # ------------------------------------------------------------------
    # Processed Transactions
    # ------------------------------------------------------------------

    def is_processed(self, reference: str) -> bool:
        """Check whether a transaction reference was already imported.

        Args:
            reference: The BNC "Referencia" field value.

        Returns:
            True if the reference exists in processed_transactions.
        """
        row = self._connection.execute(
            "SELECT 1 FROM processed_transactions WHERE reference = ?",
            (reference,),
        ).fetchone()
        return row is not None

    def mark_processed(
        self,
        reference: str,
        amount_usd: int,
        description: str,
    ) -> None:
        """Record a transaction as successfully imported.

        Args:
            reference: The BNC "Referencia" field value.
            amount_usd: Rounded whole-dollar amount that was loaded.
            description: Description as recorded in Daily Expenses 4.

        Raises:
            ValueError: If the reference was already marked as processed.
        """
        if self.is_processed(reference):
            raise ValueError(f"Transaction '{reference}' was already processed.")

        now = datetime.now(timezone.utc).isoformat()
        with self._connection:
            self._connection.execute(
                "INSERT INTO processed_transactions "
                "(reference, processed_at, amount_usd, description) "
                "VALUES (?, ?, ?, ?)",
                (reference, now, amount_usd, description),
            )

    # ------------------------------------------------------------------
    # Exchange Rates
    # ------------------------------------------------------------------

    def add_rate(
        self,
        rate: float,
        notes: str = "",
        registered_at: str | None = None,
    ) -> ExchangeRate:
        """Record a new Binance → BNC exchange rate.

        Args:
            rate: Bolivares per USD (must be positive).
            notes: Optional free-text note (e.g. "100 USDT → BNC").
            registered_at: Optional ISO date string (e.g. "2026-07-24"). Defaults to current time.

        Returns:
            The newly created ExchangeRate.

        Raises:
            ValueError: If rate is zero or negative.
        """
        if rate <= 0:
            raise ValueError(f"Exchange rate must be positive, got {rate}.")

        timestamp = registered_at or datetime.now(timezone.utc).isoformat()
        with self._connection:
            cursor = self._connection.execute(
                "INSERT INTO exchange_rates (rate, registered_at, notes) VALUES (?, ?, ?)",
                (rate, timestamp, notes),
            )
            return ExchangeRate(
                id=cursor.lastrowid,
                rate=rate,
                registered_at=timestamp,
                notes=notes,
            )

    def get_active_rate(self) -> ExchangeRate | None:
        """Return the most recently registered exchange rate.

        Returns:
            The latest ExchangeRate, or None if no rates have been recorded.
        """
        row = self._connection.execute(
            "SELECT * FROM exchange_rates ORDER BY id DESC LIMIT 1"
        ).fetchone()

        if row is None:
            return None

        return ExchangeRate(
            id=row["id"],
            rate=row["rate"],
            registered_at=row["registered_at"],
            notes=row["notes"],
        )
