"""Web automation for loading expenses into Daily Expenses 4.

Uses Playwright to simulate user interaction with the Angular SPA at
https://dailyexpenses4.com.

Authentication strategy:
  - First run: a headed browser window opens. The user logs in manually
    with Google. Full storage state (cookies + localStorage) is saved to
    data/session_cookies.json (gitignored) for future headless runs.
  - Subsequent runs: headless, session restored via storage_state.

UI Elements (supports both Spanish and English UI):
  - Nav: Movimientos / Movements
  - FAB: '+' button
  - Amount: spinbutton input
  - Account button -> dropdown list -> account name
  - Category button -> dropdown list -> category name
  - Description: textarea
  - Date: date picker -> confirm
  - Save button: Guardar / Save
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

_MONTH_NAMES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}

_MONTH_NAMES_EN = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


# ---------------------------------------------------------------------------
# Session management (cookies + localStorage via Playwright storage_state)
# ---------------------------------------------------------------------------

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
            # Check if file has valid JSON
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
    amount_field = modal.locator("input[type='number'], [role='spinbutton']").first
    amount_field.click()
    amount_field.fill(str(amount_usd))

    # 4. Account selector
    _select_account(page, modal, account)

    # 5. Category selector
    _select_category(page, modal, category)

    # 6. Description
    modal.locator("textarea").fill(description)

    # 7. Date picker
    _set_date(page, modal, expense_date)

    # 8. Save button (Guardar / Save)
    save_btn = modal.get_by_role("button", name=re.compile(r"Guardar|Save", re.IGNORECASE))
    save_btn.click()
    page.wait_for_load_state("networkidle")
    sleep(0.8)


def _select_account(page: Page, modal, account: str) -> None:
    """Open the account dropdown and select the account by name."""
    # The account button is located right after the amount input, before the category button
    # In DOM, it's typically the first dropdown button in the form body
    account_btn = modal.locator(".dropdown-toggle, button.btn-account, .col-12 button, button").filter(
        has_not_text=re.compile(r"Gastos|Ingresos|Transferencia|Guardar|Save|Cancel|Elige|Choose", re.IGNORECASE)
    ).first
    
    account_btn.click()
    page.wait_for_timeout(300)

    # Select the account option from the dropdown menu
    dropdown = page.locator(".dropdown-menu, .size-menu, #ModalAddMovements .dropdown-menu")
    option = dropdown.get_by_text(account, exact=True).first
    if option.count() == 0:
        # Fallback to general text match inside modal
        option = modal.get_by_text(account, exact=True).first
    
    option.click()
    page.wait_for_timeout(300)


def _select_category(page: Page, modal, category: str) -> None:
    """Open the category dropdown and select the category by name."""
    category_btn = modal.get_by_role(
        "button", name=re.compile(r"Elige una categoría|Choose a category|Categoría|Category", re.IGNORECASE)
    )
    if category_btn.count() == 0:
        # If a category was already selected or button has different text
        category_btn = modal.locator("button").filter(
            has=page.locator("i.fa-question-circle, i.bi-question-circle, img")
        ).first

    category_btn.click()
    page.wait_for_timeout(300)

    # Click the category item
    dropdown = page.locator(".dropdown-menu, .size-menu, #ModalAddMovements")
    dropdown.get_by_text(category, exact=True).first.click()
    page.wait_for_timeout(300)


def _set_date(page: Page, modal, expense_date: date) -> None:
    """Open the date picker, select day, and confirm."""
    # Date button contains date format dd/mmm/yyyy or dd/mm/yyyy
    date_btn = modal.get_by_role("button", name=re.compile(r"\d+/\w+/\d{4}|\w+/\d{4}"))
    if date_btn.count() == 0:
        date_btn = modal.locator("button").filter(has_text=re.compile(r"/\d{4}"))

    if date_btn.count() > 0:
        date_btn.first.click()
        page.wait_for_timeout(300)

        # Select the day in calendar
        month_es = _MONTH_NAMES_ES[expense_date.month]
        month_en = _MONTH_NAMES_EN[expense_date.month]
        
        day_btn = page.get_by_role("button", name=re.compile(
            rf"({month_es}|{month_en})\s+{expense_date.day}[,\s]", re.IGNORECASE
        ))
        
        if day_btn.count() > 0:
            day_btn.first.click()

        # Confirm date dialog (Ok / Aceptar)
        ok_btn = page.get_by_role("button", name=re.compile(r"Ok|Aceptar", re.IGNORECASE))
        if ok_btn.count() > 0:
            ok_btn.first.click()
            page.wait_for_timeout(200)


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
