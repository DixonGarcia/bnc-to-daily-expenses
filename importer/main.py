"""CLI entry point for the BNC to Daily Expenses importer.

Orchestrates the full import pipeline:
  1. Parse the BNC statement file & sort chronologically
  2. Filter already-processed transactions (deduplication)
  3. Prompt for initial exchange rate (displaying exact registered transaction date)
  4. Classify each transaction (rules DB or interactive prompt)
     - Any income / credit prompts if it defines a new rate or should be omitted
     - Dynamic rate changes update conversion rate for all following expenses
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
import re
import sys
import tomllib
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

# Ensure repo root is on sys.path for direct execution
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import questionary
from rich.console import Console
from rich.table import Table

from importer.classifier import classify
from importer.converter import to_usd
from importer.db import Database, MerchantRule
from importer.logger import (
    log_session_end,
    log_session_start,
    log_tx_decision,
)
from importer.parser import parse
from importer.rounder import AccumulativeRounder

console = Console()

_DB_PATH = Path("data/importer.db")
_CONFIG_PATH = Path("data/config.toml")


def extract_rule_pattern(raw_description: str) -> str:
    """Extract clean merchant/beneficiary pattern from raw BNC description."""
    desc = raw_description.strip()

    # 1. Match "TRANSFERENCIA A FAVOR DE: <merchant>" or "TRANSF... DE: <merchant>"
    match_favor = re.search(r"(?:TRANSFERENCIA\s+)?A\s+FAVOR\s+DE:\s*(.*)", desc, re.IGNORECASE)
    if match_favor:
        target = match_favor.group(1).strip()
        if target:
            return target[:25].strip()

    # 2. Match "TRANSFERENCIA ... A NOMBRE DE: <name>"
    match_nombre = re.search(r"A\s+NOMBRE\s+DE:\s*(.*)", desc, re.IGNORECASE)
    if match_nombre:
        target = match_nombre.group(1).strip()
        if target:
            return target[:25].strip()

    # 3. Match Pago Móvil / Instant Transfer: "TELF:... CED:... CTA:... BANCO:... <Concept/Name>"
    match_pm = re.sub(
        r"^(?:TELF\.?:\s*\S+\s+)?(?:CED\.?:\s*\S+\s+)?(?:CTA\.?:\s*\S+\s+)?(?:BANCO:\s*\S+\s+)?",
        "",
        desc,
        flags=re.IGNORECASE,
    )
    if match_pm and match_pm != desc:
        clean_pm = match_pm.strip()
        if clean_pm:
            return clean_pm[:25].strip()

    # 4. Standard POS / Biopago: strip terminal parameters
    clean_pos = re.sub(r"\s+VEN\s+ZONA=.*", "", desc, flags=re.IGNORECASE)
    clean_pos = re.sub(r"\s+BANCO:\s*\S+.*", "", clean_pos, flags=re.IGNORECASE)
    return clean_pos[:25].strip()

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


def _format_date(iso_date_str: str) -> str:
    """Format an ISO date or datetime string as DD/MM/YYYY."""
    raw = iso_date_str[:10]
    try:
        d = date.fromisoformat(raw)
        return d.strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _resolve_rate(db: Database, initial_date: date | None = None) -> Decimal:
    """Ask the user whether to use the current rate or register a new one."""
    active = db.get_active_rate()

    if active:
        date_display = _format_date(active.registered_at)
        use_existing = questionary.confirm(
            f"Tasa activa: {active.rate} Bs/USD (del {date_display}). ¿Usarla?",
            default=True,
        ).ask()
        if use_existing:
            return Decimal(str(active.rate))

    rate_str = questionary.text(
        "Ingresa la tasa de cambio inicial (Bs por USD, ej: 818.80):"
    ).ask()
    notes = questionary.text("Notas (opcional, ej: '100 USDT → BNC'):").ask() or ""
    rate = Decimal(rate_str.replace(",", "."))
    
    rate_date = initial_date.isoformat() if initial_date else datetime.now(timezone.utc).date().isoformat()
    db.add_rate(float(rate), notes=notes, registered_at=rate_date)
    console.print(f"[green]✅ Tasa guardada:[/green] {rate} Bs/USD (fecha: {_format_date(rate_date)})")
    return rate


def _handle_income_or_prompt_transaction(
    tx, db: Database, can_go_back: bool = False
) -> tuple[str, Decimal | None]:
    """Ask the user what to do with an incoming credit / transfer.

    Returns (action, new_rate):
      action: 'rate', 'skip', 'back', or 'exit'
      new_rate: Decimal rate if action == 'rate', else None
    """
    console.print("\n" + "=" * 80)
    console.print(f"[bold cyan]Ingreso detectado[/bold cyan] — [bold]{tx.date.strftime('%d/%m/%Y')} {tx.time}[/bold]")
    console.print(f"  [dim]Tipo:[/dim] {tx.tx_type}")
    console.print(f"  [dim]Descripción:[/dim] [white]{tx.description}[/white]")
    if tx.credit > 0:
        console.print(f"  [dim]Monto abonado:[/dim] [bold green]+{tx.credit:,.2f} Bs[/bold green]")
    else:
        console.print(f"  [dim]Monto débito:[/dim] [bold yellow]-{tx.debit:,.2f} Bs[/bold yellow]")
    console.print("=" * 80)

    choices = [
        "💱 Sí, registrar nueva tasa de cambio (Binance → BNC)",
        "⏭️  No, omitir este ingreso",
    ]
    if can_go_back:
        choices.append("⬅️  Volver a la transacción anterior")
    choices.append("❌ Salir / Cancelar")

    action = questionary.select(
        "¿Este ingreso representa un fondeo con nueva tasa de cambio?",
        choices=choices,
    ).ask()

    if action == "⬅️  Volver a la transacción anterior":
        return "back", None
    if action == "❌ Salir / Cancelar":
        return "exit", None
    if "No, omitir" in action:
        return "skip", None

    rate_str = questionary.text("Tasa de cambio para este ingreso (Bs por USD, ej: 818.80):").ask()
    notes = questionary.text("Notas (opcional, ej: '100 USDT → BNC'):").ask() or ""
    rate = Decimal(rate_str.replace(",", "."))
    
    # Save rate with the transaction's actual date (e.g. "2026-07-24")
    tx_date_str = tx.date.isoformat()
    db.add_rate(float(rate), notes=notes, registered_at=tx_date_str)
    console.print(f"[green]✅ Nueva tasa activa guardada:[/green] {rate} Bs/USD (fecha efectiva: {tx.date.strftime('%d/%m/%Y')})")
    return "rate", rate


def _handle_transaction_classification(
    tx,
    rate: Decimal,
    db: Database,
    suggested_rule: MerchantRule | None = None,
    saved_classification: dict | None = None,
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
    console.print(f"  [dim]Monto:[/dim] [bold yellow]Bs {tx.debit:,.2f}[/bold yellow]  →  [bold green]~${usd:.2f} USD[/bold green] [dim]@{rate} Bs/$[/dim]")
    console.print("=" * 80)

    if saved_classification:
        saved_cat = saved_classification.get("category", "")
        saved_desc = saved_classification.get("description", "")
        saved_amt = saved_classification.get("amount_usd", "")
        console.print(
            f"🔄 [bold yellow]Datos clasificados previamente:[/bold yellow] "
            f"Categoría: [cyan]{saved_cat}[/cyan] | "
            f"Descripción: [white]{saved_desc}[/white] | "
            f"Monto guardado: [bold green]${saved_amt} USD[/bold green]\n"
        )
        choices = [
            f"✅ Aceptar datos previos ({saved_cat} / {saved_desc})",
            "✏️  Modificar descripción o categoría",
            "⏭️  Omitir esta transacción",
        ]
    elif suggested_rule:
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

    if saved_classification and action.startswith("✅ Aceptar datos previos"):
        return "classify", (saved_cat, saved_desc)

    if suggested_rule and action.startswith("✅ Aceptar sugerencia"):
        return "classify", (suggested_rule.category, suggested_rule.description)

    # Classify or Edit
    cat_choices = (categories or DEFAULT_CATEGORIES) + ["(Escribir otra...)"]
    if saved_classification and saved_classification.get("category") in cat_choices:
        default_cat = saved_classification.get("category")
    elif suggested_rule and suggested_rule.category in cat_choices:
        default_cat = suggested_rule.category
    else:
        default_cat = "Comida"

    if saved_classification:
        default_desc = saved_classification.get("description", "")
    elif suggested_rule:
        default_desc = suggested_rule.description
    else:
        default_desc = ""

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
            suggested_pattern = extract_rule_pattern(tx.description)
            pattern = questionary.text(
                "Patrón a identificar en compras futuras (Cédula/RIF o nombre):",
                default=suggested_pattern,
            ).ask()
            if pattern:
                pattern = pattern.strip()
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
    table.add_column("Type", style="dim")
    table.add_column("Description", style="white")
    table.add_column("Category", style="magenta")
    table.add_column("Amount (Bs)", justify="right", style="yellow")
    table.add_column("Rate", justify="right", style="dim")
    table.add_column("USD Exact", justify="right", style="dim")
    table.add_column("USD", justify="right", style="bold green")

    total_bs = Decimal("0")
    total_usd = 0

    for i, r in enumerate(records, 1):
        tx = r["tx"]
        table.add_row(
            str(i),
            tx.date.strftime("%d/%m/%Y"),
            tx.tx_type[:15],
            r["description"][:30],
            r["category"],
            f"{tx.debit:,.2f}",
            f"{r['rate']:.2f}",
            f"${r['usd_exact']:.4f}",
            f"${r['usd_rounded']}",
        )
        total_bs += tx.debit
        total_usd += r["usd_rounded"]

    table.add_section()
    table.add_row(
        "",
        "TOTAL",
        "",
        f"{len(records)} transactions",
        "",
        f"Bs {total_bs:,.2f}",
        "",
        "",
        f"${total_usd}",
        style="bold",
    )
    console.print(table)


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def run(input_path: Path, dry_run: bool = False, headless: bool = True) -> None:
    """Run the full import pipeline.

    Args:
        input_path: Path to the BNC .txt statement file.
        dry_run: If True, show summary without loading into the web app.
        headless: If False, show the browser window during web automation.
    """
    log_session_start(input_path, dry_run=dry_run)
    console.rule("[bold blue]🏦 BNC → Daily Expenses 4 Importer[/bold blue]")

    db = Database(_DB_PATH)
    config = _load_config()

    # 1. Parse & sort chronologically (oldest to newest)
    content = input_path.read_text(encoding="utf-8")
    all_transactions = sorted(parse(content), key=lambda tx: (tx.date, tx.time))
    console.print(f"\n📄 Parsed [bold]{len(all_transactions)}[/bold] transactions from {input_path.name} (chronological order)")

    # 2. Check for previously failed transactions from this statement
    failed_in_db = {r["reference"]: r for r in db.list_processed(status="failed")}
    matching_failed = [tx for tx in all_transactions if _tx_key(tx) in failed_in_db]

    if matching_failed:
        console.print(
            f"\n[bold yellow]⚠️ Se encontraron {len(matching_failed)} transacciones previamente clasificadas "
            f"que fallaron al sincronizar con Daily Expenses 4.[/bold yellow]"
        )
        retry_choice = questionary.select(
            "¿Qué deseas hacer con estas transacciones pendientes?",
            choices=[
                f"🚀 Sincronizar directamente las {len(matching_failed)} transacciones a Daily Expenses 4 (usar datos guardados)",
                "📝 Revisar una a una en el flujo interactivo",
                "🔄 Re-clasificar desde cero",
                "⏭️  Omitir transacciones pendientes por ahora",
            ],
        ).ask()

        if retry_choice and retry_choice.startswith("🚀"):
            retry_records = []
            for tx in matching_failed:
                saved = failed_in_db[_tx_key(tx)]
                retry_records.append({
                    "tx": tx,
                    "category": saved["category"],
                    "description": saved["description"],
                    "date": tx.date,
                    "debit": tx.debit,
                    "rate": Decimal("0"),
                    "usd_exact": Decimal(str(saved["amount_usd"])),
                    "usd_rounded": saved["amount_usd"],
                })
            console.print()
            _print_summary(retry_records)
            if not dry_run:
                proceed = questionary.confirm(
                    f"\n¿Cargar estas {len(retry_records)} transacciones en Daily Expenses 4 ahora?",
                    default=True,
                ).ask()
                if proceed:
                    from importer.web_automator import run_automation
                    account = config["accounts"][0]["name"]
                    results = run_automation(records=retry_records, account=account, config=config, headless=headless)
                    synced_r = results.get("synced", [])
                    failed_r = results.get("failed", [])
                    zero_r = results.get("skipped_zero", [])
                    for r in synced_r:
                        db.mark_processed(_tx_key(r["tx"]), r["usd_rounded"], r["description"], r["category"], status="synced", overwrite=True)
                    for r in failed_r:
                        db.mark_processed(_tx_key(r["tx"]), r["usd_rounded"], r["description"], r["category"], status="failed", overwrite=True)
                    for r in zero_r:
                        db.mark_processed(_tx_key(r["tx"]), 0, r["description"], r["category"], status="skipped", overwrite=True)
                    console.print(f"\n[bold green]✅ Reintento completado: {len(synced_r)} sincronizadas con éxito.[/bold green]")
        elif retry_choice and retry_choice.startswith("🔄"):
            with db._connection:
                for tx in matching_failed:
                    db._connection.execute("DELETE FROM processed_transactions WHERE reference = ?", (_tx_key(tx),))

    # 3. Deduplicate
    new_transactions = [tx for tx in all_transactions if not db.is_processed(_tx_key(tx))]
    skipped = len(all_transactions) - len(new_transactions)
    if skipped:
        console.print(f"[dim]⏭️  {skipped} already processed, skipping.[/dim]")

    if not new_transactions:
        console.print("[green]✅ Nothing new to import.[/green]")
        log_session_end(total_parsed=len(all_transactions), synced_count=0, skipped_count=skipped, failed_count=0)
        return

    # 4. Exchange rate (use first transaction date as default context date)
    console.print()
    first_tx_date = new_transactions[0].date if new_transactions else None
    current_rate = _resolve_rate(db, initial_date=first_tx_date)

    # 5. Interactive classification loop with suggestions, Undo/Back, and Exit options
    categories = config.get("categories", DEFAULT_CATEGORIES)
    step_results: dict[int, dict | None] = {}  # idx -> classified dict or None (skipped)
    step_rates: dict[int, Decimal] = {}        # idx -> rate active at this step
    idx = 0

    try:
        while idx < len(new_transactions):
            tx = new_transactions[idx]
            step_rates[idx] = current_rate
            console.print(f"\n[dim]Transacción [{idx + 1}/{len(new_transactions)}][/dim]")

            # Check if this is an incoming transfer / credit (funding event)
            if tx.credit > 0 or tx.tx_type == "Credito Inmediato Recibido":
                prompt_action, new_rate = _handle_income_or_prompt_transaction(
                    tx, db, can_go_back=(idx > 0)
                )
                if prompt_action == "back":
                    if idx > 0:
                        idx -= 1
                        step_results.pop(idx, None)
                        current_rate = step_rates.get(idx, current_rate)
                    continue
                if prompt_action == "exit":
                    current_records = [v for v in step_results.values() if v is not None and not v.get("skipped")]
                    exit_action = _handle_exit_flow(current_records)
                    if exit_action == "save_and_process":
                        break
                    elif exit_action == "resume":
                        continue
                    else:
                        console.print("[dim]Ejecución cancelada. No se guardaron cambios.[/dim]")
                        return

                if prompt_action == "rate" and new_rate is not None:
                    current_rate = new_rate
                    log_tx_decision(idx + 1, len(new_transactions), _tx_key(tx), "NEW_RATE", tx.description, amount_bs=f"+{tx.credit}", rate=str(current_rate))
                else:
                    log_tx_decision(idx + 1, len(new_transactions), _tx_key(tx), "INCOME_SKIPPED", tx.description, amount_bs=f"+{tx.credit}")

                step_results[idx] = {"skipped": True, "tx": tx}
                idx += 1
                continue

            # Check if rule exists in DB for suggestion
            suggested_rule = db.find_rule(tx.description)
            saved_classification = failed_in_db.get(_tx_key(tx))

            action, data = _handle_transaction_classification(
                tx,
                rate=current_rate,
                db=db,
                suggested_rule=suggested_rule,
                saved_classification=saved_classification,
                can_go_back=(idx > 0),
                categories=categories,
            )

            if action == "back":
                if idx > 0:
                    idx -= 1
                    step_results.pop(idx, None)
                    current_rate = step_rates.get(idx, current_rate)
                continue

            if action == "exit":
                current_records = [v for v in step_results.values() if v is not None and not v.get("skipped")]
                exit_action = _handle_exit_flow(current_records)
                if exit_action == "save_and_process":
                    break
                elif exit_action == "resume":
                    continue
                else:
                    console.print("[dim]Ejecución cancelada. No se guardaron cambios.[/dim]")
                    return

            if action == "skip":
                log_tx_decision(idx + 1, len(new_transactions), _tx_key(tx), "SKIPPED", tx.description, amount_bs=f"-{tx.debit}", rate=str(current_rate))
                step_results[idx] = {"skipped": True, "tx": tx}
                idx += 1
                continue

            if action == "classify" and data:
                cat, desc = data
                log_tx_decision(idx + 1, len(new_transactions), _tx_key(tx), "CLASSIFIED", tx.description, cat=cat, app_desc=desc, amount_bs=f"-{tx.debit}", rate=str(current_rate))
                step_results[idx] = {
                    "tx": tx,
                    "category": cat,
                    "description": desc,
                    "date": tx.date,
                    "debit": tx.debit,
                    "rate": current_rate,
                }
                idx += 1

            # If all transactions have been reviewed, offer final check / undo before proceeding
            if idx >= len(new_transactions):
                valid_count = len([v for v in step_results.values() if v is not None and not v.get("skipped")])
                console.print("\n" + "=" * 80)
                console.print(f"🎉 [bold green]Se han revisado todos los movimientos ({valid_count} listos para importar)[/bold green]")
                console.print("=" * 80)

                choices = [
                    f"🚀 Continuar a la carga en Daily Expenses ({valid_count} transacciones)",
                    "✏️  Modificar la última transacción clasificada (⬅️ Volver)",
                    "❌ Cancelar y salir sin guardar nada",
                ]
                final_action = questionary.select(
                    "¿Qué deseas hacer?",
                    choices=choices,
                ).ask()

                if final_action and final_action.startswith("✏️"):
                    if idx > 0:
                        idx -= 1
                        step_results.pop(idx, None)
                        current_rate = step_rates.get(idx, current_rate)
                    continue
                elif final_action and final_action.startswith("❌"):
                    console.print("[dim]Ejecución cancelada. No se guardaron cambios.[/dim]")
                    return
                else:
                    break

    except KeyboardInterrupt:
        current_records = [v for v in step_results.values() if v is not None and not v.get("skipped")]
        exit_action = _handle_exit_flow(current_records)
        if exit_action != "save_and_process":
            console.print("\n[dim]Ejecución interrumpida. No se guardaron cambios.[/dim]")
            return

    # Compute USD conversion and rounding in chronological sequence
    valid_steps = [v for v in step_results.values() if v is not None and not v.get("skipped")]
    if not valid_steps:
        console.print("[yellow]No transactions to import after classification.[/yellow]")
        return

    rnd = AccumulativeRounder()
    records = []
    for step in valid_steps:
        rate_for_step = step["rate"]
        usd_exact = to_usd(step["debit"], rate_for_step)
        usd_rounded = rnd.round(usd_exact)
        records.append({
            "tx": step["tx"],
            "category": step["category"],
            "description": step["description"],
            "date": step["date"],
            "debit": step["debit"],
            "rate": rate_for_step,
            "usd_exact": usd_exact,
            "usd_rounded": usd_rounded,
        })

    # 5. Summary
    console.print()
    _print_summary(records)
    console.print(f"\n[dim]Residual after rounding: ${rnd.residue:.4f}[/dim]")

    if dry_run:
        console.print("\n[yellow]--dry-run mode: skipping web import.[/yellow]")
        log_session_end(total_parsed=len(all_transactions), synced_count=0, skipped_count=len(all_transactions) - len(records), failed_count=0)
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
    results = run_automation(records=records, account=account, config=config, headless=headless)

    # 8. Mark as processed in database with exact status
    synced_records = results.get("synced", [])
    failed_records = results.get("failed", [])
    zero_records = results.get("skipped_zero", [])

    for r in synced_records:
        try:
            db.mark_processed(
                reference=_tx_key(r["tx"]),
                amount_usd=r["usd_rounded"],
                description=r["description"],
                category=r["category"],
                status="synced",
                overwrite=True,
            )
        except Exception:
            pass

    for r in failed_records:
        try:
            db.mark_processed(
                reference=_tx_key(r["tx"]),
                amount_usd=r["usd_rounded"],
                description=r["description"],
                category=r["category"],
                status="failed",
                overwrite=True,
            )
        except Exception:
            pass

    for r in zero_records:
        try:
            db.mark_processed(
                reference=_tx_key(r["tx"]),
                amount_usd=0,
                description=r["description"],
                category=r["category"],
                status="skipped",
                overwrite=True,
            )
        except Exception:
            pass

    # Mark user-skipped transactions in DB
    for idx_k, res_val in step_results.items():
        if res_val is None or (isinstance(res_val, dict) and res_val.get("skipped")):
            skipped_tx = new_transactions[idx_k]
            try:
                db.mark_processed(
                    reference=_tx_key(skipped_tx),
                    amount_usd=0,
                    description=skipped_tx.description[:40],
                    category="",
                    status="skipped",
                    overwrite=True,
                )
            except Exception:
                pass

    skipped_total = len(zero_records) + sum(1 for v in step_results.values() if v is None or (isinstance(v, dict) and v.get("skipped")))
    log_session_end(
        total_parsed=len(all_transactions),
        synced_count=len(synced_records),
        skipped_count=skipped_total,
        failed_count=len(failed_records),
    )

    if failed_records:
        console.print(f"\n[bold yellow]⚠️ Importación finalizada: {len(synced_records)} sincronizados, {len(failed_records)} fallidos.[/bold yellow]")
        console.print("[dim]Revisa el archivo de log en tmp/importer.log para ver los detalles de los errores.[/dim]")
    else:
        console.print(f"\n[bold green]✅ Import complete! {len(synced_records)} transactions loaded.[/bold green]")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Import BNC bank statement transactions into Daily Expenses 4."
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to the BNC .txt statement file.",
    )
    parser.add_argument(
        "-d",
        "--dry-run",
        action="store_true",
        help="Preview transactions without loading into the web app.",
    )
    parser.add_argument(
        "-v",
        "--visible",
        "--show-browser",
        "--gui",
        "--headed",
        dest="visible",
        action="store_true",
        help="Open visible browser window to watch the automation in real-time.",
    )
    args = parser.parse_args()
    run(input_path=Path(args.input), dry_run=args.dry_run, headless=not args.visible)


if __name__ == "__main__":
    main()
