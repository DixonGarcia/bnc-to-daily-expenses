# Module Spec: `db.py`

## Responsibility

Manages the local SQLite database. It is the **only** module allowed to read or write
to the database file. All other modules interact with the database exclusively through
an instance of the `Database` class.

---

## Design Decision: Class-based interface

`db.py` exposes a single class `Database` that is instantiated once at startup and
passed to every module that needs it.

```python
db = Database("data/importer.db")
```

**Why a class and not standalone functions?**
- The connection is opened once and reused for the entire import session (performance).
- Tests can inject a temporary in-memory DB without touching the real file.
- Makes dependencies explicit: if a module receives a `Database`, it's clear it needs storage.

---

## Initialization Behavior

- If the database file does not exist, `Database.__init__` creates it automatically.
- On every instantiation, the three tables are created with `CREATE TABLE IF NOT EXISTS`
  (safe to run multiple times, never drops existing data).
- No rules are pre-seeded. Rules are built organically through use.

---

## Schema

### `merchant_rules`
Maps raw BNC description fragments to a human-readable category and description.
Rules are added interactively during import sessions when a new merchant is encountered.

```sql
CREATE TABLE IF NOT EXISTS merchant_rules (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern     TEXT UNIQUE NOT NULL,
    category    TEXT NOT NULL,
    description TEXT NOT NULL,
    is_regex    INTEGER NOT NULL DEFAULT 0
);
```

| Column | Notes |
|---|---|
| `pattern` | Case-insensitive substring to match against raw BNC description. UNIQUE. |
| `category` | e.g. `"Comida"`, `"Salud"`, `"Personal"` |
| `description` | Human-readable label loaded into Daily Expenses 4, e.g. `"Charcutería"` |
| `is_regex` | `0` = literal substring match, `1` = full regex match |

### `processed_transactions`
Tracks every transaction that has been successfully imported to prevent duplicates.

```sql
CREATE TABLE IF NOT EXISTS processed_transactions (
    reference    TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL,
    amount_usd   INTEGER NOT NULL,
    description  TEXT NOT NULL
);
```

| Column | Notes |
|---|---|
| `reference` | BNC "Referencia" field. Used as the deduplication key. |
| `processed_at` | ISO 8601 datetime string, e.g. `"2026-08-19T17:00:00"` |
| `amount_usd` | Rounded whole-dollar amount that was loaded into the app |
| `description` | Description as recorded in Daily Expenses 4 |

### `exchange_rates`
Stores the history of Binance → BNC transfer rates entered manually by the user.

```sql
CREATE TABLE IF NOT EXISTS exchange_rates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    rate          REAL NOT NULL,
    registered_at TEXT NOT NULL,
    notes         TEXT
);
```

| Column | Notes |
|---|---|
| `rate` | Bs per USD, e.g. `845.88` |
| `registered_at` | ISO 8601 datetime string |
| `notes` | Free text, e.g. `"100 USDT → BNC"` |

---

## Public Interface

### Merchant Rules

```python
def find_rule(self, raw_description: str) -> MerchantRule | None
```
Searches `merchant_rules` for the first pattern that matches `raw_description`
(case-insensitive). Literal patterns are checked before regex patterns.
Returns `None` if no match is found.

```python
def add_rule(self, pattern: str, category: str, description: str, is_regex: bool = False) -> MerchantRule
```
Inserts a new rule. Raises `ValueError` if `pattern` already exists.

```python
def all_rules(self) -> list[MerchantRule]
```
Returns all rules ordered by `id`. Used by the `--manage-rules` CLI command.

---

### Processed Transactions

```python
def is_processed(self, reference: str) -> bool
```
Returns `True` if `reference` already exists in `processed_transactions`.

```python
def mark_processed(self, reference: str, amount_usd: int, description: str) -> None
```
Inserts a record into `processed_transactions` with the current UTC datetime.
Raises `ValueError` if `reference` was already processed.

---

### Exchange Rates

```python
def get_active_rate(self) -> ExchangeRate | None
```
Returns the most recently registered `ExchangeRate`, or `None` if no rates exist.

```python
def add_rate(self, rate: float, notes: str = "", registered_at: str | None = None) -> ExchangeRate
```
Inserts a new exchange rate. `registered_at` is an optional ISO date/datetime string (defaults to current UTC timestamp).
Raises `ValueError` if `rate <= 0`.

---

## Return Types

```python
@dataclass
class MerchantRule:
    id: int
    pattern: str
    category: str
    description: str
    is_regex: bool

@dataclass
class ExchangeRate:
    id: int
    rate: float
    registered_at: str
    notes: str
```

---

## Edge Cases

| Case | Expected behavior |
|---|---|
| DB file does not exist | Created automatically on init |
| `find_rule` with no matching pattern | Returns `None` |
| `add_rule` with duplicate pattern | Raises `ValueError` |
| `is_processed` with unknown reference | Returns `False` |
| `mark_processed` with duplicate reference | Raises `ValueError` |
| `get_active_rate` with empty table | Returns `None` |
| `add_rate` with `rate <= 0` | Raises `ValueError` |

---

## What this module does NOT do

- Does not parse BNC statements (that is `parser.py`).
- Does not classify transactions (that is `classifier.py`).
- Does not convert currencies (that is `converter.py`).
- Does not interact with the web app (that is `web_automator.py`).
