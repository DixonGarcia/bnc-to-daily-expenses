# Module Spec: `main.py`

## Responsibility

The CLI entry point that coordinates the entire import pipeline:
1. **Parse & Sort**: Reads the BNC `.txt` export and sorts transactions chronologically (oldest to newest).
2. **Deduplicate**: Skips all transactions already marked in `processed_transactions`.
3. **Initial Rate**: Prompts for the active rate, displaying its real effective date (e.g. `24/07/2026`).
4. **Interactive Classification Loop**:
   - **Rule Suggestions**: Matched merchant rules are presented as suggestions (press Enter to accept, or edit).
   - **Income Prompts**: Any incoming transfer/credit (`credit > 0`) prompts whether it represents a Binance → BNC funding rate or should be omitted.
   - **Dynamic Rates**: If a new rate is registered on a transfer, subsequent transactions in the file use the new rate.
   - **Category Selection**: 21 predefined categories from Daily Expenses 4 (with option to enter a custom category).
   - **Undo Navigation**: `⬅️ Volver a la transacción anterior` allows stepping back to correct any previous classification.
   - **Exit Options**: `❌ Salir / Cancelar` (or Ctrl+C) prompts whether to process/import classified transactions or discard everything.
5. **Convert & Round**: Converts each transaction using the rate active at that step with `AccumulativeRounder`.
6. **Summary**: Displays the full summary table with Bs, Rate, USD exact, and Rounded USD.
7. **Web Automation**: (unless `--dry-run`) Loads movements into Daily Expenses 4.
8. **Mark Processed**: Records processed transactions in SQLite so subsequent runs skip them automatically.

---

## Command-Line Interface

```bash
# Dry run preview (no web browser)
python -m importer.main --input "statement.txt" --dry-run

# Full import into Daily Expenses 4
python -m importer.main --input "statement.txt"
```
