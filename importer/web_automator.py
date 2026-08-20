"""Web automation for loading expenses into Daily Expenses 4.

Uses Playwright to simulate user interaction with the Angular SPA at
https://dailyexpenses4.com.

Authentication strategy (NO credentials are ever stored):
  - First run: a headed browser window opens. The user logs in manually
    with Google. Session cookies are saved to data/session_cookies.json
    (gitignored) for future headless runs.
  - Subsequent runs: headless, cookies restored from file.

Flow per expense (discovered with playwright codegen):
  1. Navigate to Movements section
  2. Click the FAB (floating action button, no visible text)
  3. Fill amount (spinbutton)
  4. Select account from modal
  5. Select category from modal
  6. Fill description (textarea)
  7. Set date via date picker
  8. Click Save
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

_MONTH_NAMES = {
    1: "January", 2: "February", 3: "March", 4: "April",
    5: "May", 6: "June", 7: "July", 8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


# ---------------------------------------------------------------------------
# Session management — credentials are NEVER stored, only session cookies
# ---------------------------------------------------------------------------

def _cookies_path(config: dict) -> Path:
    return Path(config["app"]["cookies_file"])


def _load_cookies(context: BrowserContext, cookies_file: Path) -> bool:
    """Restore session cookies into the browser context.

    Returns True if the file existed and cookies were loaded.
    """
    if not cookies_file.exists():
        return False
    cookies = json.loads(cookies_file.read_text(encoding="utf-8"))
    context.add_cookies(cookies)
    return True


def _save_cookies(context: BrowserContext, cookies_file: Path) -> None:
    """Persist current session cookies to disk for future headless runs."""
    cookies_file.parent.mkdir(parents=True, exist_ok=True)
    cookies_file.write_text(
        json.dumps(context.cookies(), indent=2), encoding="utf-8"
    )


def _is_logged_in(page: Page) -> bool:
    """Check whether the app is showing the authenticated UI."""
    try:
        page.wait_for_load_state("networkidle", timeout=12_000)
        return page.get_by_role("link", name="Movements").count() > 0
    except Exception:
        return False


def _manual_login(playwright_instance, cookies_file: Path) -> BrowserContext:
    """Open a headed browser for the user to log in manually with Google.

    Credentials are typed by the user directly in the browser — they are
    never captured, stored, or transmitted by this program.

    Returns a BrowserContext with an active authenticated session.
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

    _save_cookies(context, cookies_file)
    console.print("[green]✅ Session saved — future runs will be headless.[/green]")
    return context


def get_authenticated_context(playwright_instance, cookies_file: Path) -> tuple[object, BrowserContext]:
    """Return (browser, context) with an active authenticated session.

    Tries cookie-based restore first. Falls back to manual headed login.
    """
    browser = playwright_instance.chromium.launch(headless=True)
    context = browser.new_context()

    if _load_cookies(context, cookies_file):
        page = context.new_page()
        page.goto(APP_URL)
        if _is_logged_in(page):
            console.print("[dim]✅ Session restored from cookies.[/dim]")
            page.close()
            return browser, context
        console.print("[yellow]Cookies expired — need to log in again.[/yellow]")

    browser.close()
    context = _manual_login(playwright_instance, cookies_file)
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
    """Load a single expense into Daily Expenses 4.

    Args:
        page: Authenticated Playwright page already on the app.
        amount_usd: Whole-dollar amount to record (e.g. 10).
        description: Expense description shown in the app.
        category: Category name exactly as it appears in the app dropdown.
        account: Account name exactly as it appears in the app (e.g. "Binance").
        expense_date: Date of the expense.

    Raises:
        Exception: If any step fails (caller logs the error and continues).
    """
    modal = page.locator(MODAL_ID)

    # 1. Navigate to Movements
    page.get_by_role("link", name="Movements").click()
    page.wait_for_load_state("networkidle")

    # 2. Open new expense modal via FAB (button with no visible text)
    page.get_by_role("button").filter(
        has_text=re.compile(r"^\s*$")
    ).last.click()
    modal.wait_for(state="visible", timeout=8_000)

    # 3. Amount
    amount_field = page.get_by_role("spinbutton", name="0")
    amount_field.click()
    amount_field.fill(str(amount_usd))

    # 4. Account selector
    #    The button shows the currently selected account name (dynamic).
    #    We click it, then pick our target account from the list.
    _select_account(page, modal, account)

    # 5. Category
    page.get_by_role("button", name="Choose a category").click()
    modal.get_by_text(category, exact=True).click()

    # 6. Description
    page.locator("textarea").fill(description)

    # 7. Date picker
    _set_date(page, modal, expense_date)

    # 8. Save
    page.get_by_role("button", name="Save").click()
    page.wait_for_load_state("networkidle")
    sleep(0.8)


def _select_account(page: Page, modal, account: str) -> None:
    """Click the account selector button and pick the target account.

    The button label changes dynamically (it shows the currently selected
    account name), so we identify it by excluding known static button labels.
    """
    # The account button is the one that's neither "Choose a category",
    # "Save", nor the FAB. It shows the currently active account name.
    account_btn = modal.get_by_role("button").filter(
        has_not_text=re.compile(r"Choose a category|Save|Cancel", re.IGNORECASE)
    ).first
    account_btn.click()
    modal.get_by_text(account, exact=True).click()


def _set_date(page: Page, modal, expense_date: date) -> None:
    """Open the date picker, navigate to the correct day, and confirm.

    The date button shows the currently selected date/time as dynamic text
    (e.g. "19/Aug/2026 11:05 am"), so we match it with a regex.
    """
    # Open date picker — button label contains month abbreviation and year
    modal.get_by_role("button", name=re.compile(r"\w+/\d{4}")).click()

    # Select the correct day
    month_name = _MONTH_NAMES[expense_date.month]
    page.get_by_role("button", name=re.compile(
        rf"{month_name}\s+{expense_date.day}[,\s]"
    )).click()

    # Set time to noon (time is irrelevant for expense tracking)
    hours = page.get_by_role("textbox", name="Hours")
    hours.triple_click()
    hours.fill("12")

    minutes = page.get_by_role("textbox", name="Minutes")
    minutes.triple_click()
    minutes.fill("00")

    page.get_by_role("button", name="Ok").click()


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
    cookies_file = _cookies_path(config)

    with sync_playwright() as pw:
        browser, context = get_authenticated_context(pw, cookies_file)
        page = context.new_page()
        page.goto(APP_URL)
        page.wait_for_load_state("networkidle")

        for i, record in enumerate(records, 1):
            desc = record["description"]
            amt = record["usd_rounded"]
            console.print(
                f"   [dim]→ {i}/{len(records)}[/dim] {desc} [bold]${amt}[/bold]...",
                end=" ",
            )
            try:
                load_expense(
                    page,
                    amount_usd=amt,
                    description=desc,
                    category=record["category"],
                    account=account,
                    expense_date=record["date"],
                )
                console.print("[green]✅[/green]")
            except Exception as exc:
                console.print(f"[red]❌ {exc}[/red]")

        browser.close()
