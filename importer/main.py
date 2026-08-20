"""CLI entry point for the BNC to Daily Expenses importer.

Orchestrates the full import pipeline:
  1. Parse the BNC statement file
  2. Filter already-processed transactions (deduplication)
  3. Prompt for exchange rate
  4. Classify each transaction (rules DB or interactive prompt)
     - Rules are presented as suggestions (can accept or edit)
     - Visual separation lines between transaction output and choices
     - Interactive undo (go back to previous transaction)
     - Cancel & exit with save/discard options
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
from importer.db import Database, MerchantRule
from importer.parser import parse
from importer.rounder import AccumulativeRounder

console = Console()

_DB_PATH = Path("data/importer.db")
_CONFIG_PATH = Path("data/config.toml")

DEFAULT_CATEGORIES = [
    "Autopista",
    "Bebidas",
    "Comida",
    "Diversión",
    "Educación",
    "Gasolina",
    "Hijo",
    "Hogar",
    "Hotel",
    "Mascota",
    "Mercancía",
    "Negocio",
    "Otros",
    "Personales",
    "Préstamo",
    "Propinas",
    "Restaurante",
    "Ropa",
    "Salud",
    "Tecnología",
    "Transporte",
]


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        console.print(
            f"[red]Config file not found:[/red] {_CONFIG_PATH}\n"
            "Copy data/config.toml.example → data/config.toml and fill in your values."
        )
        sys.exit(1)
    with open(_CONFIG_PATH, "rb") as f:
        return tomllib.load(f)


def _tx_key(tx) -> str:
    """Generate a unique deduplication key for a transaction."""
    return tx.reference if tx.reference else f"{tx.date}_{tx.time}_{tx.debit}_{tx.description[:25]}"


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


def _handle_prompt_transaction(tx, db: Database, can_go_back: bool = False) -> str:
    """Ask the user what to do with a special transaction (e.g. Credito Inmediato).

    Returns 'rate', 'skip', 'back', or 'exit'.
    """
    console.print("\n" + "=" * 80)
    console.print(f"[bold cyan]Transacción Especial[/bold cyan] — [bold]{tx.date.strftime('%d/%m/%Y')} {tx.time}[/bold]")
    console.print(f"  [dim]Tipo:[/dim] {tx.tx_type}")
    console.print(f"  [dim]Descripción:[/dim] [white]{tx.description}[/white]")
    console.print(f"  [dim]Monto:[/dim] [bold yellow]{'+' if tx.credit else '-'}{tx.credit or tx.debit:,.2f} Bs[/bold yellow]")
    console.print("=" * 80)

    choices = [
        "Registrar nueva tasa de cambio (Binance → BNC)",
        "⏭️  Ignorar esta transacción",
    ]
    if can_go_back:
        choices.append("⬅️  Volver a la transacción anterior")
    choices.append("❌ Salir / Cancelar")

    action = questionary.select(
        "¿Qué deseas hacer con este movimiento?",
        choices=choices,
    ).ask()

    if action == "⬅️  Volver a la transacción anterior":
        return "back"
    if action == "❌ Salir / Cancelar":
        return "exit"
    if action == "⏭️  Ignorar esta transacción":
        return "skip"

    rate_str = questionary.text("Tasa de cambio para esta transferencia (Bs por USD):").ask()
    notes = questionary.text("Notas (opcional, ej: '100 USDT → BNC'):").ask() or ""
    rate = Decimal(rate_str.replace(",", "."))
    db.add_rate(float(rate), notes=notes)
    console.print(f"[green]✅ Tasa guardada:[/green] {rate} Bs/USD")
    return "rate"


def _handle_transaction_classification(
    tx,
    rate: Decimal,
    db: Database,
    suggested_rule: MerchantRule | None = None,
    can_go_back: bool = False,
    categories: list[str] | None = None,
) -> tuple[str, tuple[str, str] | None]:
    """Present transaction details and let user accept rule suggestion, edit, or classify.

    Returns (action, data):
      action: 'classify', 'skip', 'back', or 'exit'
      data: (category, description) when action is 'classify', else None
    """
    usd = to_usd(tx.debit, rate)

    console.print("\n" + "=" * 80)
    console.print(f"[bold cyan]Transacción[/bold cyan] — [bold]{tx.date.strftime('%d/%m/%Y')} {tx.time}[/bold]")
    console.print(f"  [dim]Tipo:[/dim] {tx.tx_type}")
    console.print(f"  [dim]Descripción BNC:[/dim] [white]{tx.description}[/white]")
    console.print(f"  [dim]Monto:[/dim] [bold yellow]Bs {tx.debit:,.2f}[/bold yellow]  →  [bold green]~${usd:.2f} USD[/bold green]")
    console.print("=" * 80)

    if suggested_rule:
        console.print(
            f"💡 [bold green]Regla sugerida:[/bold green] "
            f"Categoría: [cyan]{suggested_rule.category}[/cyan] | "
            f"Descripción: [white]{suggested_rule.description}[/white]\n"
        )
        choices = [
            f"✅ Aceptar sugerencia ({suggested_rule.category} / {suggested_rule.description})",
            "✏️  Modificar descripción o categoría",
            "⏭️  Omitir esta transacción",
        ]
    else:
        console.print("[yellow]⚠️  Comercio nuevo (sin regla previa)[/yellow]\n")
        choices = [
            "📝 Clasificar transacción",
            "⏭️  Omitir esta transacción",
        ]

    if can_go_back:
        choices.append("⬅️  Volver a la transacción anterior")
    choices.append("❌ Salir / Cancelar")

    action = questionary.select(
        "Selecciona una opción:",
        choices=choices,
    ).ask()

    if action == "⬅️  Volver a la transacción anterior":
        return "back", None

    if action == "❌ Salir / Cancelar":
        return "exit", None

    if action == "⏭️  Omitir esta transacción":
        return "skip", None

    if suggested_rule and action.startswith("✅ Aceptar sugerencia"):
        return "classify", (suggested_rule.category, suggested_rule.description)

    # Classify or Edit
    cat_choices = (categories or DEFAULT_CATEGORIES) + ["(Escribir otra...)"]
    default_cat = suggested_rule.category if (suggested_rule and suggested_rule.category in cat_choices) else "Comida"
    default_desc = suggested_rule.description if suggested_rule else ""

    selected_cat = questionary.select(
        "Categoría:",
        choices=cat_choices,
        default=default_cat,
    ).ask()

    if selected_cat == "(Escribir otra...)":
        category = questionary.text("Nombre de la categoría:").ask()
    else:
        category = selected_cat

    description = questionary.text(
        "Descripción para la app:",
        default=default_desc,
    ).ask()

    # Save rule if it's new or modified
    if not suggested_rule or description != suggested_rule.description or category != suggested_rule.category:
        save = questionary.confirm("¿Guardar/actualizar esta regla para compras futuras?", default=True).ask()
        if save:
            pattern = tx.description[:20].strip()
            try:
                db.add_rule(pattern, category, description)
                console.print(f"[green]✅ Regla guardada:[/green] '{pattern}' → {category} / {description}")
            except ValueError:
                with db._connection:
                    db._connection.execute(
                        "UPDATE merchant_rules SET category = ?, description = ? WHERE pattern = ?",
                        (category, description, pattern),
                    )
                console.print(f"[green]✅ Regla actualizada:[/green] '{pattern}' → {category} / {description}")

    return "classify", (category, description)


def _handle_exit_flow(classified_records: list[dict]) -> str:
    """Prompt the user on how to exit when aborting.

    Returns:
      'save_and_process': continue importing what was classified so far
      'discard': exit immediately without saving or importing anything
      'resume': cancel exit and continue classifying
    """
    count = len(classified_records)
    console.print(f"\n[bold yellow]Se han clasificado {count} transacciones hasta el momento.[/bold yellow]")

    choices = []
    if count > 0:
        choices.append(f"Procesar e importar lo clasificado hasta ahora ({count} transacciones)")
    choices.append("Descartar todo y salir sin guardar nada")
    choices.append("Continuar clasificando")

    choice = questionary.select("¿Qué deseas hacer?", choices=choices).ask()

    if choice and "Procesar e importar" in choice:
        return "save_and_process"
    if choice == "Continuar clasificando":
        return "resume"
    return "discard"


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

    # 1. Parse & sort chronologically (oldest to newest)
    content = input_path.read_text(encoding="utf-8")
    all_transactions = sorted(parse(content), key=lambda tx: (tx.date, tx.time))
    console.print(f"\n📄 Parsed [bold]{len(all_transactions)}[/bold] transactions from {input_path.name} (chronological order)")

    # 2. Deduplicate
    new_transactions = [tx for tx in all_transactions if not db.is_processed(_tx_key(tx))]
    skipped = len(all_transactions) - len(new_transactions)
    if skipped:
        console.print(f"[dim]⏭️  {skipped} already processed, skipping.[/dim]")

    if not new_transactions:
        console.print("[green]✅ Nothing new to import.[/green]")
        return

    # 3. Exchange rate
    console.print()
    rate = _resolve_rate(db)

    # 4. Interactive classification loop with suggestions, Undo/Back, and Exit options
    categories = config.get("categories", DEFAULT_CATEGORIES)
    step_results: dict[int, dict | None] = {}  # idx -> classified dict or None (skipped)
    idx = 0

    try:
        while idx < len(new_transactions):
            tx = new_transactions[idx]
            console.print(f"\n[dim]Transacción [{idx + 1}/{len(new_transactions)}][/dim]")

            # Check if this is a special prompt transaction (funding/transfer)
            if tx.tx_type in {"Credito Inmediato Recibido", "Crédito Inmediato Emitido"}:
                prompt_action = _handle_prompt_transaction(tx, db, can_go_back=(idx > 0))
                if prompt_action == "back":
                    if idx > 0:
                        idx -= 1
                        step_results.pop(idx, None)
                    continue
                if prompt_action == "exit":
                    current_records = [v for v in step_results.values() if v is not None]
                    exit_action = _handle_exit_flow(current_records)
                    if exit_action == "save_and_process":
                        break
                    elif exit_action == "resume":
                        continue
                    else:
                        console.print("[dim]Ejecución cancelada. No se guardaron cambios.[/dim]")
                        return

                step_results[idx] = None
                idx += 1
                continue

            # Check if rule exists in DB for suggestion
            suggested_rule = db.find_rule(tx.description)

            action, data = _handle_transaction_classification(
                tx,
                rate=rate,
                db=db,
                suggested_rule=suggested_rule,
                can_go_back=(idx > 0),
                categories=categories,
            )

            if action == "back":
                if idx > 0:
                    idx -= 1
                    step_results.pop(idx, None)
                continue

            if action == "exit":
                current_records = [v for v in step_results.values() if v is not None]
                exit_action = _handle_exit_flow(current_records)
                if exit_action == "save_and_process":
                    break
                elif exit_action == "resume":
                    continue
                else:
                    console.print("[dim]Ejecución cancelada. No se guardaron cambios.[/dim]")
                    return

            if action == "skip":
                step_results[idx] = None
                idx += 1
                continue

            if action == "classify" and data:
                cat, desc = data
                step_results[idx] = {
                    "tx": tx,
                    "category": cat,
                    "description": desc,
                    "date": tx.date,
                    "debit": tx.debit,
                }
                idx += 1

    except KeyboardInterrupt:
        current_records = [v for v in step_results.values() if v is not None]
        exit_action = _handle_exit_flow(current_records)
        if exit_action != "save_and_process":
            console.print("\n[dim]Ejecución interrumpida. No se guardaron cambios.[/dim]")
            return

    # Compute USD conversion and rounding in chronological sequence
    valid_steps = [v for v in step_results.values() if v is not None]
    if not valid_steps:
        console.print("[yellow]No transactions to import after classification.[/yellow]")
        return

    rnd = AccumulativeRounder()
    records = []
    for step in valid_steps:
        usd_exact = to_usd(step["debit"], rate)
        usd_rounded = rnd.round(usd_exact)
        records.append({
            "tx": step["tx"],
            "category": step["category"],
            "description": step["description"],
            "date": step["date"],
            "debit": step["debit"],
            "usd_exact": usd_exact,
            "usd_rounded": usd_rounded,
        })

    # 5. Summary
    console.print()
    _print_summary(records)
    console.print(f"\n[dim]Residual after rounding: ${rnd.residue:.4f}[/dim]")

    if dry_run:
        console.print("\n[yellow]--dry-run mode: skipping web import.[/yellow]")
        return

    # 6. Confirm before web automation
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
                reference=_tx_key(r["tx"]),
                amount_usd=r["usd_rounded"],
                description=r["description"],
            )
        except ValueError:
            pass

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
