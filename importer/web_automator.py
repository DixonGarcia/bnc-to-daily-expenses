"""Web automation for loading expenses into Daily Expenses 4.

Uses Playwright to simulate user interaction with the Angular SPA at
https://dailyexpenses4.com. Authentication is via Google Sign-In (OAuth).

Session strategy:
- First run: headed browser for manual Google login. Cookies saved to
  data/session_cookies.json (gitignored).
- Subsequent runs: headless, cookies restored from file.

Selector mapping:
- Selectors were discovered with `playwright codegen https://dailyexpenses4.com/home`
- They are defined as constants at the top of this module for easy maintenance.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from time import sleep

from playwright.sync_api import Browser, Page, sync_playwright
from rich.console import Console

console = Console()

# ---------------------------------------------------------------------------
# App URL
# ---------------------------------------------------------------------------
APP_URL = "https://dailyexpenses4.com/home"

# ---------------------------------------------------------------------------
# Selectors — update here if the app UI changes
# ---------------------------------------------------------------------------
# Button to open the "new expense" form
NEW_EXPENSE_BTN = "button.add-expense-btn, [data-testid='add-expense'], .fab"

# Form fields inside the new expense modal/panel
AMOUNT_INPUT = "input[placeholder*='amount'], input[type='number']"
DESCRIPTION_INPUT = "input[placeholder*='description'], input[placeholder*='descripci']"
DATE_INPUT = "input[type='date']"

# Account selector (dropdown or list)
ACCOUNT_SELECTOR = "mat-select, select[name='account']"

# Category selector
CATEGORY_SELECTOR = "mat-select[formcontrolname='category'], select[name='category']"

# Save / confirm button inside the form
SAVE_BTN = "button[type='submit'], button:has-text('Save'), button:has-text('Guardar')"


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

def _load_cookies(page: Page, cookies_file: Path) -> bool:
    """Load saved session cookies into the page context.

    Returns True if cookies were loaded, False if file does not exist.
    """
    if not cookies_file.exists():
        return False
    cookies = json.loads(cookies_file.read_text())
    page.context.add_cookies(cookies)
    return True


def _save_cookies(page: Page, cookies_file: Path) -> None:
    """Save current page session cookies to disk."""
    cookies_file.parent.mkdir(parents=True, exist_ok=True)
    cookies = page.context.cookies()
    cookies_file.write_text(json.dumps(cookies, indent=2))


def _is_logged_in(page: Page) -> bool:
    """Check if the current page shows the authenticated app UI."""
    page.wait_for_load_state("networkidle", timeout=10_000)
    return "login" not in page.url.lower() and page.locator(NEW_EXPENSE_BTN).count() > 0


def get_authenticated_page(browser: Browser, cookies_file: Path, headless: bool) -> Page:
    """Return an authenticated page, prompting for manual login if needed.

    Args:
        browser: Playwright Browser instance.
        cookies_file: Path to the session cookies JSON file.
        headless: Whether to run headless. First login always runs headed.

    Returns:
        An authenticated Playwright Page ready to interact with the app.
    """
    context = browser.new_context()
    page = context.new_page()

    # Try restoring session from cookies
    if _load_cookies(page, cookies_file):
        page.goto(APP_URL)
        if _is_logged_in(page):
            console.print("[dim]✅ Session restored from cookies.[/dim]")
            return page
        console.print("[yellow]Session expired — need to log in again.[/yellow]")

    # Manual login (always headed)
    console.print(
        "\n[bold yellow]🔑 Manual login required.[/bold yellow]\n"
        "A browser window will open. Sign in with Google, then press Enter here."
    )
    context.close()
    headed_context = browser.new_context()
    page = headed_context.new_page()
    page.goto(APP_URL)

    input("\nPress Enter after you have logged in successfully...")

    if not _is_logged_in(page):
        raise RuntimeError("Login failed or app did not load correctly after login.")

    _save_cookies(page, cookies_file)
    console.print("[green]✅ Session saved.[/green]")
    return page


# ---------------------------------------------------------------------------
# Expense loading
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

    Clicks the new expense button, fills in the form fields, and saves.
    Waits for the form to close before returning.

    Args:
        page: Authenticated Playwright page.
        amount_usd: Whole-dollar amount to record.
        description: Expense description as shown in the app.
        category: Category name as it appears in the app's dropdown.
        account: Account name as it appears in the app.
        expense_date: Date of the expense.
    """
    # Open new expense form
    page.locator(NEW_EXPENSE_BTN).first.click()
    page.wait_for_load_state("networkidle")

    # Fill amount
    page.locator(AMOUNT_INPUT).first.fill(str(amount_usd))

    # Fill description
    page.locator(DESCRIPTION_INPUT).first.fill(description)

    # Fill date (format: YYYY-MM-DD for HTML date input)
    page.locator(DATE_INPUT).first.fill(expense_date.isoformat())

    # Select account
    _select_option(page, ACCOUNT_SELECTOR, account)

    # Select category
    _select_option(page, CATEGORY_SELECTOR, category)

    # Save
    page.locator(SAVE_BTN).first.click()
    page.wait_for_load_state("networkidle")
    sleep(0.5)  # Brief pause between entries


def _select_option(page: Page, selector: str, value: str) -> None:
    """Select an option in a dropdown by visible text.

    Handles both native <select> and Angular Material mat-select.
    """
    element = page.locator(selector).first
    tag = element.evaluate("el => el.tagName.toLowerCase()")

    if tag == "select":
        element.select_option(label=value)
    else:
        # Angular Material mat-select: click to open, then click the option
        element.click()
        page.get_by_role("option", name=value).first.click()


# ---------------------------------------------------------------------------
# Main automation entry point
# ---------------------------------------------------------------------------

def run_automation(records: list[dict], account: str, config: dict) -> None:
    """Load all classified records into Daily Expenses 4.

    Args:
        records: List of dicts with keys: tx, category, description,
                 date, usd_rounded.
        account: Account name in the app (e.g. "Binance").
        config: Loaded config.toml dict.
    """
    cookies_file = Path(config["app"]["cookies_file"])

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = get_authenticated_page(browser, cookies_file, headless=True)

        for i, record in enumerate(records, 1):
            desc = record["description"]
            amt = record["usd_rounded"]
            console.print(f"   → Loading {i}/{len(records)}: {desc} ${amt}...", end=" ")
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
            except Exception as e:
                console.print(f"[red]❌ Failed: {e}[/red]")

        browser.close()
