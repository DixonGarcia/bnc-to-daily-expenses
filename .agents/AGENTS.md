# BNC to Daily Expenses — Agent Instructions

This file is the entry point for all AI agents working on this codebase.
Read it at the start of every session before touching any code.

---

## 🎯 Project Purpose

A local Python CLI tool that automates importing **BNC (Banco Nacional de Crédito) Venezuela**
bank statement transactions into the **Daily Expenses 4** web app (`dailyexpenses4.com`).

The app has no public API and no import feature — so this tool simulates user interaction
via Playwright to load transactions automatically.

**Two accounts in scope:**
- **Binance** — USD (USDT). This is the target account in Daily Expenses 4.
- **BNC** — Venezuelan Bolívares (BsF). Source of the bank statement. All expenses are
  converted to USD before being recorded in Daily Expenses 4.

---

## 📂 Repository Structure

```
bnc-to-daily-expenses/
├── .agents/
│   ├── AGENTS.md          ← you are here
│   └── rules.md           ← coding conventions and patterns
├── importer/
│   ├── __init__.py
│   ├── main.py            # CLI entry point
│   ├── parser.py          # BNC TSV parser + transaction filtering
│   ├── classifier.py      # merchant rule matching engine
│   ├── converter.py       # BsF → USD conversion
│   ├── rounder.py         # accumulative ROUND_HALF_UP rounding
│   ├── db.py              # SQLite: merchant_rules, processed_transactions, exchange_rates
│   └── web_automator.py   # Playwright: loads expenses into dailyexpenses4.com
├── data/
│   ├── config.toml.example  # committed template
│   └── config.toml          # gitignored — real config with account names
├── tests/
│   ├── conftest.py          # shared fixtures (db, sample_statement, etc.)
│   ├── test_parser.py
│   ├── test_classifier.py
│   ├── test_converter.py
│   └── test_rounder.py
├── requirements.txt
└── README.md
```

---

## 🗄️ SQLite Schema

Three tables — defined in `importer/db.py`:

### `merchant_rules`
Maps raw BNC description fragments to human-readable category + description.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `pattern` | TEXT UNIQUE | Case-insensitive substring or regex |
| `category` | TEXT | e.g. "Comida", "Salud", "Personal" |
| `description` | TEXT | e.g. "Charcutería", "Farmacia" |
| `is_regex` | INTEGER | 0 = literal, 1 = regex |

### `processed_transactions`
Tracks every imported transaction to prevent duplicates.

| Column | Type | Notes |
|---|---|---|
| `reference` | TEXT PK | BNC "Referencia" field |
| `processed_at` | TEXT | ISO datetime |
| `amount_usd` | REAL | Rounded USD amount that was loaded |
| `description` | TEXT | Description as loaded into the app |

### `exchange_rates`
History of Binance → BNC transfer rates.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `rate` | REAL | e.g. 845.88 (Bs per USD) |
| `registered_at` | TEXT | ISO datetime |
| `notes` | TEXT | Free text, e.g. "100 USDT → BNC" |

---

## 🔄 Transaction Processing Rules

### Transactions to IGNORE (filtered in `parser.py`)
- `tx_type` contains `"Comisión"` — bank commissions (< $0.02, noise)
- `credit > 0` and `tx_type` contains `"Abono"` — incoming transfers
- `tx_type` == `"Saldo Inicial"` — balance header row
- `tx_type` contains `"Comisión Credito Inmediato"` — transfer commission

### Transactions that trigger an INTERACTIVE PROMPT
- `Credito Inmediato Recibido` — may be a Binance → BNC funding event.
  Ask: "Register new exchange rate? / Ignore?"
- `Crédito Inmediato Emitido` — outgoing transfer.
  Ask: "What is this? / Ignore?"
- Any debit with no matching merchant rule — ask for category + description + save rule?

### Transactions to PROCESS as expenses
- `Compra de POS DebitMC`
- `Cargo Pago Movil BNC`
- `Retiro de Biopago`

---

## 💱 Currency Conversion & Rounding

- **Conversion**: `amount_usd = amount_bsf / active_rate` (last registered exchange rate)
- **Rounding**: `ROUND_HALF_UP` with accumulative residual.
  - Residual carries over to the next transaction in the same import session.
  - e.g. $9.73 → $10 (residual: -0.27), next $9.20 → effective $8.93 → $9

---

## 🧪 Testing Workflow (Spec-First TDD)

1. Write specs first (red)
2. Implement until tests pass (green)
3. Refactor
4. Commit: `test: ...` then `feat: ...`

See [`.agents/rules.md`](./rules.md) for full conventions.

---

## 🌐 Web Automation Notes

- App: **Gastos Diarios 4** — Angular SPA at `https://dailyexpenses4.com`
- Auth: Google Sign-In (OAuth). Session stored in `data/session_cookies.json` (gitignored).
- First run: headed browser for manual login. Subsequent runs: headless with saved cookies.
- Selectors: mapped with `playwright codegen` during Phase 6 implementation.

---

## 🔧 Environment

- Python 3.12+
- SSH remote: `git@github.com-personal:DixonGarcia/bnc-to-daily-expenses.git`
- GitHub account: `DixonGarcia` (personal)
- All commands run from repo root.
