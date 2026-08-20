"""Web automation for loading expenses into Daily Expenses 4.

Uses Playwright to simulate user interaction with the Angular SPA at
https://dailyexpenses4.com.

Angular Components:
  - Account picker:  <app-selector-account>
  - Category picker: <app-selector-category>
  - Date picker:     <app-date-time-picker>
  - Save button:     button.save-movement-button
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from time import sleep

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright
from rich.console import Console

console = Console()

APP_URL = "https://dailyexpenses4.com/home"
MODAL_ID = "#ModalAddMovements"


def _session_file_path(config: dict) -> Path:
    return Path(config["app"].get("cookies_file", "data/session_cookies.json"))


def _is_logged_in(page: Page) -> bool:
    """Check whether the app is showing the authenticated UI."""
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
        nav_link = page.get_by_role("link", name=re.compile(r"Movimientos|Movements|Inicio|Home", re.IGNORECASE))
        return nav_link.count() > 0
    except Exception:
        return False


def _manual_login(playwright_instance, session_file: Path) -> BrowserContext:
    """Open a headed browser for the user to log in manually.

    Saves full browser context storage state (cookies + localStorage).
    """
    console.print(
        "\n[bold yellow]🔑 First-time login required.[/bold yellow]\n"
        "A browser window will open. Sign in with Google manually.\n"
        "[dim](Your credentials are entered directly in the browser.\n"
        "This program never sees or stores them.)[/dim]\n"
        "Press [bold]Enter[/bold] here once you are logged in and see the app home screen."
    )
    browser = playwright_instance.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(APP_URL)
    input()  # Wait for user to log in

    if not _is_logged_in(page):
        browser.close()
        raise RuntimeError(
            "Could not confirm login. Make sure you are on the app home screen before pressing Enter."
        )

    session_file.parent.mkdir(parents=True, exist_ok=True)
    context.storage_state(path=str(session_file))
    console.print("[green]✅ Session saved — future runs will be headless.[/green]")
    return context


def get_authenticated_context(playwright_instance, session_file: Path) -> tuple[object, BrowserContext]:
    """Return (browser, context) with an active authenticated session."""
    if session_file.exists():
        try:
            content = session_file.read_text(encoding="utf-8").strip()
            if content and content != "[]":
                browser = playwright_instance.chromium.launch(headless=True)
                context = browser.new_context(storage_state=str(session_file))
                page = context.new_page()
                page.goto(APP_URL)
                if _is_logged_in(page):
                    console.print("[dim]✅ Session restored successfully.[/dim]")
                    page.close()
                    return browser, context
                console.print("[yellow]Session expired — need to log in again.[/yellow]")
                browser.close()
        except Exception:
            pass

    context = _manual_login(playwright_instance, session_file)
    return context.browser, context


# ---------------------------------------------------------------------------
# Expense loading — one expense per call
# ---------------------------------------------------------------------------

def load_expense(
    page: Page,
    *,
    amount_usd: int,
    description: str,
    category: str,
    account: str,
    expense_date: date,
) -> None:
    """Load a single expense into Daily Expenses 4."""
    modal = page.locator(MODAL_ID)

    # 1. Navigate to Movements / Movimientos
    movimientos_link = page.get_by_role("link", name=re.compile(r"Movimientos|Movements", re.IGNORECASE))
    if movimientos_link.count() > 0:
        movimientos_link.first.click()
        page.wait_for_load_state("networkidle")

    # 2. Open new expense modal via FAB (+) button
    page.get_by_role("button").filter(
        has_text=re.compile(r"^\s*$")
    ).last.click()
    modal.wait_for(state="visible", timeout=8_000)

    # 3. Amount input
    amount_field = modal.locator("input.quantity, input[type='number']").first
    amount_field.click()
    amount_field.fill(str(amount_usd))

    # 4. Account selector via <app-selector-account>
    modal.locator("app-selector-account button").click()
    page.wait_for_timeout(300)
    account_item = modal.locator("app-selector-account .dropdown-menu .item-list").filter(has_text=account).first
    if account_item.count() > 0:
        account_item.click()
    else:
        # Fallback to text inside modal
        modal.get_by_text(account, exact=True).first.click()
    page.wait_for_timeout(300)

    # 5. Category selector via <app-selector-category>
    modal.locator("app-selector-category button").click()
    page.wait_for_timeout(300)
    category_item = modal.locator("app-selector-category .dropdown-menu .item-list").filter(has_text=category).first
    if category_item.count() > 0:
        category_item.click()
    else:
        modal.get_by_text(category, exact=True).first.click()
    page.wait_for_timeout(300)

    # 6. Description
    modal.locator("textarea").fill(description)

    # 7. Date picker via <app-date-time-picker>
    date_btn = modal.locator("app-date-time-picker button.btn")
    if date_btn.count() > 0:
        date_btn.first.click()
        page.wait_for_timeout(300)

        # Select the day number in calendar
        day_cell = page.locator("mat-calendar button.mat-calendar-body-cell").filter(
            has_text=re.compile(rf"^\s*{expense_date.day}\s*$")
        ).first
        if day_cell.count() > 0:
            day_cell.click()
            page.wait_for_timeout(200)

        # Confirm date
        ok_btn = page.locator("app-date-time-picker button").filter(has_text=re.compile(r"Ok|Aceptar", re.IGNORECASE))
        if ok_btn.count() > 0:
            ok_btn.first.click()
            page.wait_for_timeout(200)

    # 8. Save button
    modal.locator("button.save-movement-button").click()
    page.wait_for_load_state("networkidle")
    sleep(0.8)


# ---------------------------------------------------------------------------
# Main automation entry point
# ---------------------------------------------------------------------------

def run_automation(records: list[dict], account: str, config: dict) -> None:
    """Load all classified records into Daily Expenses 4.

    Args:
        records: List of dicts with keys: tx, category, description, date, usd_rounded.
        account: Account name in the app (e.g. "Binance").
        config: Loaded config.toml dict.
    """
    session_file = _session_file_path(config)

    with sync_playwright() as pw:
        browser, context = get_authenticated_context(pw, session_file)
        page = context.new_page()
        page.goto(APP_URL)
        page.wait_for_load_state("networkidle")

        for i, record in enumerate(records, 1):
            desc = record["description"]
            amt = record["usd_rounded"]
            cat = record.get("category", "Otros")
            tx_date = record.get("date", date.today())

            console.print(
                f"   [dim]→ {i}/{len(records)}[/dim] {desc} [bold]${amt}[/bold] ({cat})...",
                end=" ",
            )
            try:
                load_expense(
                    page,
                    amount_usd=amt,
                    description=desc,
                    category=cat,
                    account=account,
                    expense_date=tx_date,
                )
                console.print("[green]✅[/green]")
            except Exception as exc:
                console.print(f"[red]❌ {exc}[/red]")

        browser.close()
