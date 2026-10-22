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

- 📄 **BNC TSV parser & chronological sorting** — Reads the bank statement export, sorts transactions chronologically (oldest to newest), and filters out noise (commissions, balance rows)
- 🏪 **Merchant rule engine & smart pattern extraction** — Automatically extracts clean merchant/beneficiary identifiers from POS, Biopago, Pago Móvil, and wire transfers. Suggests matching categories and descriptions with 1-click confirmation or inline editing
- 💱 **Dynamic exchange rate tracking** — Records Binance → BNC transfer rates with their exact effective transaction dates. Prompts on funding events to register new rates that take effect chronologically for subsequent expenses
- 🔢 **Accumulative rounding** — Rounds USD amounts to whole numbers and carries the residual forward (e.g. $9.73 → $10, then $9.20 + residual → $9)
- 🔁 **Deduplication & status tracking** — Tracks transactions by reference ID with granular statuses (`synced`, `failed`, `skipped`) to prevent duplicate imports
- 🔄 **Failed sync recovery** — Detects previously classified transactions that failed during web sync and offers direct 1-click resync or re-classification
- 📜 **Session logging** — Generates complete audit logs in `tmp/importer.log` recording classifications, rate changes, sync attempts, and session summaries
- 🤖 **Playwright web automation** — Automatically loads expenses into Daily Expenses 4 with datepicker month navigation and exact time picker support (runs headless by default or headed with `--visible`)
- 🖥️ **Interactive CLI & flow control** — Select from 21 app categories, edit rule suggestions, undo previous steps (`⬅️ Volver`), cancel with save/discard options, and review before sync

---

## Architecture

```
BNC .txt export
       │
       ▼
   [Parser] ──► filter commissions & balance rows, sort chronologically
       │
       ▼
   [Deduplicator] ──► skip already-processed references / detect failed syncs (SQLite)
       │
       ▼
   [Classifier] ──► match merchant rules / prompt new rates on funding credits
       │                    │
       │              no match?
       │                    ▼
       │           [Interactive prompt] ──► save/update rule?
       │
       ▼
   [Converter] ──► BsF ÷ step active exchange rate = USD
       │
       ▼
   [Rounder] ──► accumulative ROUND_HALF_UP to whole dollars
       │
       ▼
   [Playwright] ──► load into dailyexpenses4.com (headless or visible)
       │
       ▼
   [DB & Logger] ──► mark transaction status & record session audit log
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

### Setup

```bash
# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Copy and edit your config
cp data/config.toml.example data/config.toml
```

### Running the Importer

```bash
# Dry run — preview and verify classifications and conversions without web loading
python -m importer.main -i "my_statement.txt" --dry-run

# Full import — runs headless in the background
python -m importer.main -i "my_statement.txt"

# Visible browser — watch the automation run in real-time
python -m importer.main -i "my_statement.txt" --visible
```

### CLI Options

| Flag | Aliases | Description |
|---|---|---|
| `-i, --input` | | **(Required)** Path to the BNC `.txt` bank statement export |
| `-d, --dry-run` | | Preview transactions, rates, and rounding summary table without loading into the web app |
| `-v, --visible` | `--show-browser`, `--gui`, `--headed` | Open a visible Chromium browser window to watch the web automation in real-time (default is headless) |
| `-h, --help` | | Show CLI options and help message |

> **Note**: Merchant rules and exchange rates are managed interactively during execution and persisted automatically in SQLite (`data/importer.db`). Execution logs are saved to `tmp/importer.log`.

---

## Project Structure

```
bnc-to-daily-expenses/
├── importer/
│   ├── main.py            # CLI entry point and pipeline orchestrator
│   ├── parser.py          # BNC TSV parser and transaction extractor
│   ├── classifier.py      # merchant rule matching engine
│   ├── converter.py       # BsF → USD dynamic conversion
│   ├── rounder.py         # accumulative ROUND_HALF_UP rounding
│   ├── db.py              # SQLite: merchant_rules, processed_transactions, exchange_rates
│   ├── logger.py          # execution audit logging (tmp/importer.log)
│   └── web_automator.py   # Playwright: Daily Expenses 4 browser automation
├── data/
│   ├── config.toml.example
│   └── config.toml        # gitignored — real config with account names
├── tests/
│   ├── conftest.py
│   ├── test_parser.py
│   ├── test_classifier.py
│   ├── test_converter.py
│   ├── test_rounder.py
│   ├── test_db.py
│   ├── test_logger.py
│   ├── test_main.py
│   └── test_web_automator.py
├── tmp/
│   └── importer.log       # session execution and sync logs
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
