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
History of Binance → BNC transfer rates with their effective transaction dates.

| Column | Type | Notes |
|---|---|---|
| `id` | INTEGER PK | |
| `rate` | REAL | e.g. 845.88 (Bs per USD) |
| `registered_at` | TEXT | ISO date/datetime (e.g. "2026-07-24" based on transaction date) |
| `notes` | TEXT | Free text, e.g. "100 USDT → BNC" |

---

## 🔄 Transaction Processing Rules

### Transactions to IGNORE (filtered in `parser.py`)
- `tx_type` contains `"Comisión"` — bank commissions (< $0.02, noise)
- `tx_type` == `"Saldo Inicial"` — balance header row
- `tx_type` contains `"Comisión Credito Inmediato"` — transfer commission

### Transactions that trigger an INTERACTIVE PROMPT
- Any incoming credit (`credit > 0`, e.g. `Credito Inmediato Recibido`, `Abono Pago Movil`, `Transferencia Recibida`) — user decides if it represents a new Binance → BNC funding rate or should be omitted.
- `Crédito Inmediato Emitido` — outgoing transfer.
- Any debit with no matching merchant rule — interactive category selection (from the 21 app categories) + description + save rule option.
- Existing merchant rules are presented as **editable suggestions** (Accept with Enter, or edit).

### Transactions to PROCESS as expenses
- `Compra de POS DebitMC`
- `Cargo Pago Movil BNC`
- `Retiro de Biopago`
- `Pago MOVISTAR BNCNet` (and any debited service payment)

---

## 💱 Currency Conversion, Rates & Rounding

- **Chronological Sorting**: Transactions are sorted from oldest to newest prior to processing.
- **Dynamic Rates**: If a new rate is registered on a transfer, it takes effect from that transaction forward for all subsequent expenses in the statement.
- **Historical Rate Date**: Exchange rates record the actual transaction date (e.g. `24/07/2026`), not the current system clock time.
- **Conversion**: `amount_usd = amount_bsf / active_rate` (rate active at that specific transaction step).
- **Rounding**: `ROUND_HALF_UP` with accumulative residual.
  - Residual carries over to the next transaction in chronological sequence.
  - e.g. $9.73 → $10 (residual: -0.27), next $9.20 → effective $8.93 → $9

---

## 🧪 Spec-Driven Development Workflow

This project follows a **spec-first TDD** cycle. The agent MUST follow this order
for every module — no exceptions.

### The Cycle

```
1. READ   → understand the module's contract from the plan
2. SPEC   → write all tests first (they must fail)
3. VERIFY → run pytest, confirm all new tests are RED
4. BUILD  → implement the module until all tests are GREEN
5. COMMIT → two separate commits (test first, then feat)
6. REFACTOR (optional) → clean up, commit as refactor
```

### Step-by-Step Agent Behavior

**Step 1 — Write specs first**
- Create `tests/test_<module>.py` with all cases grouped by class.
- Cover: happy path, edge cases, and error cases.
- Do NOT write any implementation code yet.

**Step 2 — Confirm tests fail (red)**
```bash
pytest tests/test_<module>.py -v
# Expected: all new tests FAIL with ImportError or AssertionError
```

**Step 3 — Commit the failing tests**
```bash
git add tests/test_<module>.py
git commit -m "test: add <module> specs"
```

**Step 4 — Implement the module**
- Write only enough code to make the tests pass.
- No gold-plating. No features not covered by a test.

**Step 5 — Confirm tests pass (green)**
```bash
pytest tests/ -v
# Expected: all tests PASS, including previous ones (no regressions)
```

**Step 6 — Commit the implementation**
```bash
git add importer/<module>.py
git commit -m "feat: implement <module>"
git push
```

### Module Implementation Order

Follow this sequence — each module depends on the previous:

| # | Module | Depends on |
|---|---|---|
| 1 | `db.py` | nothing |
| 2 | `parser.py` | nothing |
| 3 | `classifier.py` | `db.py`, `parser.py` |
| 4 | `converter.py` | nothing |
| 5 | `rounder.py` | nothing |
| 6 | `main.py` | all above |
| 7 | `web_automator.py` | `main.py` |

See [`.agents/rules.md`](./rules.md) for pytest conventions and fixture patterns.

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
