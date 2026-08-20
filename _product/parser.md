# Module Spec: `parser.py`

## Responsibility

Reads a BNC bank statement `.txt` file and returns a list of `BNCTransaction`
objects, filtering out rows that are never relevant as expenses.

The parser does **not** classify, convert, or deduplicate — it only extracts
and filters raw data from the file.

---

## Input File Format

The file has three sections:

```
Line 1:  Account header  (account number @ owner name @ description)
Line 2:  Empty
Line 3:  TSV column headers
Line 4+: TSV data rows
```

### Column order (0-indexed)
| # | Column | Example |
|---|---|---|
| 0 | Fecha | `19/08/2026` |
| 1 | Hora | `11:48:55.826` |
| 2 | Referencia | `819154846` |
| 3 | Cod. Transacción | `377` |
| 4 | Tipo Transacción | `MAESTR` |
| 5 | Tip. Operación | `Compra de POS DebitMC` |
| 6 | Descripción | `KEYLA PATRICIA SANTAMA COJEDES...` |
| 7 | Debe | `-8234` |
| 8 | Haber | `0` |
| 9 | Saldo | `68253,42` |
| 10 | Referencia 2 | `123186` |

**Notes:**
- Delimiter: tab (`\t`)
- Encoding: UTF-8
- Decimal separator: comma (`,`) — must be normalized to `.` for `Decimal`
- The file uses Windows line endings (`\r\n`)
- `Debe` (debit) values appear as negative numbers (e.g. `-8234`)
- `Haber` (credit) values are positive (e.g. `45700`)

---

## Output: `BNCTransaction` dataclass

```python
@dataclass
class BNCTransaction:
    date: date          # parsed from "19/08/2026" → date(2026, 8, 19)
    time: str           # kept as string "11:48:55.826"
    reference: str      # deduplication key — may be empty string
    tx_type: str        # "Compra de POS DebitMC", "Cargo Pago Movil BNC"…
    op_type: str        # "MAESTR", "P2PTSO", "CIOPPS"… (may be empty)
    description: str    # raw merchant/description text
    debit: Decimal      # absolute value (always >= 0). e.g. 8234
    credit: Decimal     # absolute value (always >= 0). e.g. 45700
    balance: Decimal
```

**`debit` is stored as a positive value** even though the file has it negative.
The sign is discarded — context (debit vs credit) is carried by the field name.

---

## Filtering Rules

The following rows are silently dropped and never returned:

| Condition | Example from file |
|---|---|
| `tx_type` == `"Saldo Inicial"` | Line 4 — balance header row |
| `tx_type` contains `"Comisión"` | Lines 9, 11, 15… — bank commissions |
| `tx_type` == `"Comisión Credito Inmediato"` | Line 19 — transfer commission |
| `credit > 0` and `tx_type != "Credito Inmediato Recibido"` | Line 8, 10 — incoming payments and transfers |
| Row has fewer than 9 columns | Malformed / empty trailing line |

### Rows that ARE returned (for further processing)

| `tx_type` | Treatment |
|---|---|
| `"Compra de POS DebitMC"`, `"Cargo Pago Movil BNC"`, `"Retiro de Biopago"`, `"Pago MOVISTAR BNCNet"` (any debit > 0) | Expense — classify and import |
| `"Credito Inmediato Recibido"` | Passed through — triggers interactive prompt |
| `"Crédito Inmediato Emitido"` | Passed through — triggers interactive prompt |

---

## Public Interface

```python
def parse(content: str) -> list[BNCTransaction]:
    """Parse the text content of a BNC bank statement.

    Skips the header line, the empty line, and the column-names line.
    Filters out ignored transaction types.
    Returns remaining rows as BNCTransaction dataclasses.

    Args:
        content: Full string content of the .txt file.

    Returns:
        List of BNCTransaction, possibly empty. Order matches the file.
    """
```

The module exposes **one public function**: `parse(content)`.
Callers are responsible for reading the file — the parser only handles strings.

---

## Edge Cases

| Case | Expected behavior |
|---|---|
| Empty file / only headers | Returns `[]` |
| Row with empty Referencia | `reference` is `""` (empty string) |
| Decimal with comma (e.g. `8.234,50`) | Converted to `Decimal("8234.50")` |
| Debit value is negative in file (`-8234`) | Stored as `Decimal("8234")` (absolute) |
| Trailing empty line (line 30 in example) | Skipped (fewer than 9 columns) |
| `Haber` is `0` and `Debe` is negative | `credit=0`, `debit=abs(value)` |
