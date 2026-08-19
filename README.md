# bnc-to-daily-expenses

A local CLI tool that automates importing **BNC (Banco Nacional de Crédito) Venezuela** bank statement transactions into the **Daily Expenses 4** web app (`dailyexpenses4.com`).

Built as a personal finance automation project to handle the Venezuelan dual-currency context (BsF ↔ USD via Binance).

---

## The Problem

Manually logging every expense is tedious and error-prone. The Daily Expenses 4 app has no public API and no import feature — so this tool simulates a human user interacting with the web app to load transactions automatically.

There are two layers of complexity:

1. **Parsing**: The BNC bank statement is a tab-separated `.txt` file with raw merchant descriptions that need to be mapped to human-readable categories.
2. **Currency conversion**: Expenses are paid in Venezuelan Bolívares (BsF) from a BNC account funded by Binance USDT transfers. Each transfer has a specific exchange rate, so the tool tracks the active rate and converts BsF → USD accordingly.

---

## Features

- 📄 **BNC TSV parser** — Reads the bank statement export and filters out noise (commissions, credits, balance rows)
- 🏪 **Merchant rule engine** — Maps raw bank descriptions to clean categories and labels (e.g. `KEYLA PATRICIA SANTAMA` → _Charcutería / Comida_). Rules are saved to a local SQLite DB and reused automatically
- 💱 **Exchange rate tracking** — Stores Binance → BNC transfer rates. Prompts you interactively when a new funding event is detected
- 🔢 **Accumulative rounding** — Rounds USD amounts to whole numbers and carries the residual to the next transaction (so $9.73 → $10, then $9.20 + residual → $9)
- 🔁 **Deduplication** — Tracks processed transactions by reference ID so re-running on the same file never creates duplicates
- 🤖 **Playwright automation** — Logs into the Daily Expenses 4 web app and loads each expense automatically, simulating user interaction
- 🖥️ **Interactive CLI** — Pauses on ambiguous or unknown merchants to ask for category, description, and whether to save the rule for the future

---

## Architecture

```
BNC .txt export
       │
       ▼
   [Parser] ──► filter commissions, credits, balance rows
       │
       ▼
   [Deduplicator] ──► skip already-processed references (SQLite)
       │
       ▼
   [Classifier] ──► match merchant rules (SQLite)
       │                    │
       │              no match?
       │                    ▼
       │           [Interactive prompt] ──► save new rule?
       │
       ▼
   [Converter] ──► BsF ÷ active exchange rate = USD
       │
       ▼
   [Rounder] ──► accumulative ROUND_HALF_UP to whole dollars
       │
       ▼
   [Playwright] ──► load into dailyexpenses4.com
       │
       ▼
   [DB] ──► mark transaction as processed
```

---

## Stack

| Component | Technology |
|---|---|
| Language | Python 3.12+ |
| Local database | SQLite (stdlib) |
| Web automation | Playwright |
| CLI | Rich + Questionary |
| Config | TOML (stdlib) |
| Tests | pytest |

---

## Usage

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Copy and edit your config
cp data/config.toml.example data/config.toml

# Dry run — preview what would be imported
python -m importer.main --input "my_statement.txt" --dry-run

# Full import — loads into Daily Expenses 4
python -m importer.main --input "my_statement.txt"

# Manage merchant rules
python -m importer.main --manage-rules
```

---

## Project Structure

```
bnc-to-daily-expenses/
├── importer/
│   ├── main.py            # CLI entry point
│   ├── parser.py          # BNC TSV parser
│   ├── classifier.py      # merchant rule matching
│   ├── converter.py       # BsF → USD conversion
│   ├── rounder.py         # accumulative rounding
│   ├── db.py              # SQLite: rules, processed txs, rates
│   └── web_automator.py   # Playwright: Daily Expenses 4 automation
├── data/
│   └── config.toml.example
├── tests/
│   ├── test_parser.py
│   ├── test_classifier.py
│   ├── test_converter.py
│   └── test_rounder.py
├── requirements.txt
└── README.md
```

---

## Roadmap

- [ ] Support multiple accounts (Efectivo, Zelle, etc.)
- [ ] Auto-detect funding events from statement patterns
- [ ] Export summary report (CSV / JSON)
- [ ] Support additional Venezuelan banks

---

## Context

This project was designed with an AI-assisted planning workflow using [Antigravity](https://antigravity.dev), demonstrating how to go from a real-world problem description to a structured, production-ready implementation plan before writing a single line of code.
