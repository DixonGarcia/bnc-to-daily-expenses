"""CLI entry point for the BNC to Daily Expenses importer.

Orchestrates the full import pipeline:
  1. Parse the BNC statement file
  2. Filter already-processed transactions (deduplication)
  3. Prompt for exchange rate
  4. Classify each transaction (rules DB or interactive prompt)
  5. Convert BsF → USD and round
  6. Show summary table and confirm
  7. Load into Daily Expenses 4 via Playwright (unless --dry-run)
  8. Mark each transaction as processed
"""
from __future__ import annotations

import argparse
import sys
import tomllib
from decimal import Decimal
from pathlib import Path

import questionary
from rich.console import Console
from rich.table import Table

from importer.classifier import classify
from importer.converter import to_usd
from importer.db import Database
from importer.parser import parse
from importer.rounder import AccumulativeRounder

console = Console()

_DB_PATH = Path("data/importer.db")
_CONFIG_PATH = Path("data/config.toml")


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        console.print(
            f"[red]Config file not found:[/red] {_CONFIG_PATH}\n"
            "Copy data/config.toml.example → data/config.toml and fill in your values."
        )
        sys.exit(1)
    with open(_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _resolve_rate(db: Database) -> Decimal:
    """Ask the user whether to use the current rate or register a new one."""
    active = db.get_active_rate()

    if active:
        use_existing = questionary.confirm(
            f"Active exchange rate: {active.rate} Bs/USD "
            f"(registered {active.registered_at[:10]}). Use it?",
            default=True,
        ).ask()
        if use_existing:
            return Decimal(str(active.rate))

    rate_str = questionary.text(
        "Enter new exchange rate (Bs per USD, e.g. 845.88):"
    ).ask()
    notes = questionary.text("Notes (optional, e.g. '100 USDT → BNC'):").ask() or ""
    rate = Decimal(rate_str.replace(",", "."))
    db.add_rate(float(rate), notes=notes)
    console.print(f"[green]✅ Rate saved:[/green] {rate} Bs/USD")
    return rate


def _handle_prompt_transaction(tx, db: Database) -> tuple[str, str] | None:
    """Ask the user what to do with a Credito Inmediato transaction.

    Returns (category, description) or None if the transaction should be skipped.
    """
    console.print(
        f"\n[yellow]⚡ Special transaction detected:[/yellow]\n"
        f"   Type: {tx.tx_type}\n"
        f"   Description: {tx.description}\n"
        f"   Amount: {'+'if tx.credit else '-'}{tx.credit or tx.debit:,.2f} Bs"
    )
    action = questionary.select(
        "What is this?",
        choices=[
            "Register new Binance → BNC exchange rate",
            "Ignore this transaction",
        ],
    ).ask()

    if "Ignore" in action:
        return None

    rate_str = questionary.text("Exchange rate for this transfer (Bs per USD):").ask()
    notes = questionary.text("Notes:").ask() or ""
    rate = Decimal(rate_str.replace(",", "."))
    db.add_rate(float(rate), notes=notes)
    console.print(f"[green]✅ Rate saved:[/green] {rate} Bs/USD")
    return None  # Funding events are not recorded as expenses


def _handle_unknown_merchant(tx, rate: Decimal, db: Database) -> tuple[str, str] | None:
    """Ask the user to classify an unknown merchant.

    Returns (category, description) or None to skip.
    """
    usd = to_usd(tx.debit, rate)
    console.print(
        f"\n[yellow]⚠️  Unknown merchant:[/yellow]\n"
        f"   Raw: {tx.description}\n"
        f"   Amount: Bs {tx.debit:,.2f} → ~${usd:.2f}"
    )
    action = questionary.select(
        "What do you want to do?",
        choices=["Classify it", "Skip this transaction"],
    ).ask()

    if action == "Skip this transaction":
        return None

    category = questionary.text("Category (e.g. Comida, Salud, Personal):").ask()
    description = questionary.text("Description for the app:").ask()
    save = questionary.confirm("Save rule for future matches?", default=True).ask()

    if save:
        # Use first significant word cluster as pattern
        pattern = tx.description[:20].strip()
        try:
            db.add_rule(pattern, category, description)
            console.print(f"[green]✅ Rule saved:[/green] '{pattern}' → {category} / {description}")
        except ValueError:
            console.print("[dim]Rule already exists, skipping save.[/dim]")

    return category, description


def _print_summary(records: list[dict]) -> None:
    table = Table(title="Transactions to Import", show_lines=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Date", style="cyan")
    table.add_column("Description", style="white")
    table.add_column("Category", style="green")
    table.add_column("Bs", justify="right")
    table.add_column("USD (exact)", justify="right", style="yellow")
    table.add_column("Rounded $", justify="right", style="bold green")

    for i, r in enumerate(records, 1):
        table.add_row(
            str(i),
            str(r["date"]),
            r["description"],
            r["category"],
            f"{r['debit']:,.2f}",
            f"${r['usd_exact']:.2f}",
            f"${r['usd_rounded']}",
        )

    console.print(table)
    total = sum(r["usd_rounded"] for r in records)
    console.print(f"\n[bold]Total: {len(records)} transactions, ${total} USD[/bold]")


def run(input_path: Path, dry_run: bool = False) -> None:
    """Main import pipeline.

    Args:
        input_path: Path to the BNC .txt statement file.
        dry_run: If True, show summary without loading into the web app.
    """
    console.rule("[bold blue]🏦 BNC → Daily Expenses 4 Importer[/bold blue]")

    db = Database(_DB_PATH)
    config = _load_config()

    # 1. Parse
    content = input_path.read_text(encoding="utf-8")
    all_transactions = parse(content)
    console.print(f"\n📄 Parsed [bold]{len(all_transactions)}[/bold] transactions from {input_path.name}")

    # 2. Deduplicate
    new_transactions = [tx for tx in all_transactions if not db.is_processed(tx.reference)]
    skipped = len(all_transactions) - len(new_transactions)
    if skipped:
        console.print(f"[dim]⏭️  {skipped} already processed, skipping.[/dim]")

    if not new_transactions:
        console.print("[green]✅ Nothing new to import.[/green]")
        return

    # 3. Exchange rate
    console.print()
    rate = _resolve_rate(db)

    # 4. Classify + convert + round
    rnd = AccumulativeRounder()
    records = []

    for tx in new_transactions:
        classified = classify(tx, db)

        if classified is None:
            # Unknown merchant — ask user
            result = _handle_unknown_merchant(tx, rate, db)
            if result is None:
                continue
            category, description = result

        elif classified.requires_prompt:
            # Funding event — ask user
            _handle_prompt_transaction(tx, db)
            continue

        else:
            category = classified.category
            description = classified.description

        usd_exact = to_usd(tx.debit, rate)
        usd_rounded = rnd.round(usd_exact)

        records.append({
            "tx": tx,
            "category": category,
            "description": description,
            "date": tx.date,
            "debit": tx.debit,
            "usd_exact": usd_exact,
            "usd_rounded": usd_rounded,
        })

    if not records:
        console.print("[yellow]No transactions to import after classification.[/yellow]")
        return

    # 5. Summary
    console.print()
    _print_summary(records)
    console.print(f"\n[dim]Residual after rounding: ${rnd.residue:.4f}[/dim]")

    if dry_run:
        console.print("\n[yellow]--dry-run mode: skipping web import.[/yellow]")
        return

    # 6. Confirm
    proceed = questionary.confirm(
        f"\nLoad {len(records)} transactions into Daily Expenses 4?",
        default=True,
    ).ask()

    if not proceed:
        console.print("[dim]Cancelled.[/dim]")
        return

    # 7. Web automation
    from importer.web_automator import run_automation

    account = config["accounts"][0]["name"]
    run_automation(records=records, account=account, config=config)

    # 8. Mark as processed
    for r in records:
        try:
            db.mark_processed(
                reference=r["tx"].reference,
                amount_usd=r["usd_rounded"],
                description=r["description"],
            )
        except ValueError:
            pass  # Already marked (edge case with empty references)

    console.print(f"\n[bold green]✅ Import complete! {len(records)} transactions loaded.[/bold green]")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import BNC bank statement transactions into Daily Expenses 4."
    )
    parser.add_argument("--input", required=True, help="Path to the BNC .txt statement file.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview transactions without loading into the web app.",
    )
    args = parser.parse_args()
    run(input_path=Path(args.input), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
