"""Web automation for loading expenses into Daily Expenses 4.

Uses Playwright to simulate user interaction with the Angular SPA at
https://dailyexpenses4.com.

Angular Components:
  - Account picker:  <app-selector-account>
  - Category picker: <app-selector-category>
  - Date & Time picker: <app-date-time-picker> (mat-calendar + ngb-timepicker)
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

_ALL_MONTHS = {
    # Spanish
    "ENE": 1, "ENERO": 1,
    "FEB": 2, "FEBRERO": 2,
    "MAR": 3, "MARZO": 3,
    "ABR": 4, "ABRIL": 4,
    "MAY": 5, "MAYO": 5,
    "JUN": 6, "JUNIO": 6,
    "JUL": 7, "JULIO": 7,
    "AGO": 8, "AGOSTO": 8,
    "SEP": 9, "SEPTIEMBRE": 9,
    "OCT": 10, "OCTUBRE": 10,
    "NOV": 11, "NOVIEMBRE": 11,
    "DIC": 12, "DICIEMBRE": 12,
    # English
    "JAN": 1, "JANUARY": 1,
    "FEBRUARY": 2,
    "MARCH": 3,
    "APR": 4, "APRIL": 4,
    "JUNE": 6,
    "JULY": 7,
    "AUG": 8, "AUGUST": 8,
    "SEPTEMBER": 9,
    "OCTOBER": 10,
    "NOVEMBER": 11,
    "DEC": 12, "DECEMBER": 12,
}


def _session_file_path(config: dict) -> Path:
    return Path(config["app"].get("cookies_file", "data/session_cookies.json"))


def _is_logged_in(page: Page) -> bool:
    """Check whether the app is showing the authenticated UI."""
    try:
        page.wait_for_selector("app-navbar, [routerlink='/movements'], a[href*='movements'], a[href*='home'], .navbar", timeout=6_000)
        return True
    except Exception:
        nav_link = page.get_by_role("link", name=re.compile(r"Movimientos|Movements|Inicio|Home", re.IGNORECASE))
        return nav_link.count() > 0


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
    page.goto(APP_URL, wait_until="domcontentloaded", timeout=30_000)
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


def get_authenticated_context(
    playwright_instance,
    session_file: Path,
    headless: bool = True,
    slow_mo: int = 0,
) -> tuple[object, BrowserContext]:
    """Return (browser, context) with an active authenticated session."""
    if session_file.exists():
        try:
            content = session_file.read_text(encoding="utf-8").strip()
            if content and content != "[]":
                browser = playwright_instance.chromium.launch(headless=headless, slow_mo=slow_mo)
                context = browser.new_context(storage_state=str(session_file))
                page = context.new_page()
                page.goto(APP_URL, wait_until="domcontentloaded", timeout=20_000)
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
# Date & Time Picker Helpers
# ---------------------------------------------------------------------------

def _parse_calendar_header(text: str) -> tuple[int, int] | None:
    """Extract (year, month_number) from mat-calendar header text (e.g. 'AGO 2026', 'AUG 2026', 'JULIO 2026')."""
    if not text:
        return None
    upper = text.strip().upper()
    match = re.search(r"\b(20\d\d)\b", upper)
    year = int(match.group(1)) if match else date.today().year

    for name, month_num in sorted(_ALL_MONTHS.items(), key=lambda x: len(x[0]), reverse=True):
        if name in upper:
            return (year, month_num)
    return None


def _parse_time_12h(time_str: str) -> tuple[int, int, str]:
    """Parse a time string (e.g. '18:14:47.155' or '08:35') into (hour_12, minute, meridian)."""
    if not time_str:
        return (12, 0, "AM")
    try:
        parts = time_str.strip().split(":")
        hour_24 = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        is_pm = hour_24 >= 12
        hour_12 = hour_24 % 12
        if hour_12 == 0:
            hour_12 = 12
        meridian = "PM" if is_pm else "AM"
        return (hour_12, minute, meridian)
    except Exception:
        return (12, 0, "AM")


def _set_date_and_time(modal, expense_date: date, expense_time: str = "") -> None:
    """Set the exact date and time in the <app-date-time-picker> component."""
    date_btn = modal.locator("app-date-time-picker button.btn, app-date-time-picker button[data-bs-toggle='dropdown']")
    if date_btn.count() == 0:
        return

    date_btn.first.click()
    modal.page.wait_for_timeout(300)

    # 1. Navigate Calendar Month & Year
    target_year = expense_date.year
    target_month = expense_date.month

    for _ in range(24):  # safety max 24 months navigation
        header_btn = modal.locator("mat-calendar button.mat-calendar-period-button")
        if header_btn.count() == 0:
            break
        header_text = header_btn.first.inner_text()
        current = _parse_calendar_header(header_text)
        if not current:
            break

        curr_year, curr_month = current
        if (curr_year, curr_month) == (target_year, target_month):
            break

        if (curr_year, curr_month) > (target_year, target_month):
            prev_btn = modal.locator("mat-calendar button.mat-calendar-previous-button, mat-calendar button[aria-label*='Previous'], mat-calendar button[aria-label*='Anterior']")
            if prev_btn.count() > 0:
                prev_btn.first.click()
                modal.page.wait_for_timeout(150)
        else:
            next_btn = modal.locator("mat-calendar button.mat-calendar-next-button, mat-calendar button[aria-label*='Next'], mat-calendar button[aria-label*='Siguiente']")
            if next_btn.count() > 0:
                next_btn.first.click()
                modal.page.wait_for_timeout(150)

    # 2. Select the specific Day in the month
    day_cell = modal.locator("mat-calendar button.mat-calendar-body-cell").filter(
        has_text=re.compile(rf"^\s*{expense_date.day}\s*$")
    ).or_(
        modal.locator(f"mat-calendar button[aria-label*='{expense_date.day} ']")
    ).or_(
        modal.locator(f"mat-calendar button[aria-label*=' {expense_date.day},']")
    ).first

    if day_cell.count() > 0:
        day_cell.click()
        modal.page.wait_for_timeout(200)

    # 3. Set Time in ngb-timepicker
    hour_12, minute, target_meridian = _parse_time_12h(expense_time)

    hour_input = modal.locator("ngb-timepicker input[aria-label*='Hour'], ngb-timepicker input[aria-label*='Hora'], ngb-timepicker .ngb-tp-hour input, ngb-timepicker input[placeholder='HH']")
    if hour_input.count() > 0:
        hour_input.first.click()
        hour_input.first.fill(f"{hour_12:02d}")

    minute_input = modal.locator("ngb-timepicker input[aria-label*='Minute'], ngb-timepicker input[aria-label*='Minuto'], ngb-timepicker .ngb-tp-minute input, ngb-timepicker input[placeholder='MM']")
    if minute_input.count() > 0:
        minute_input.first.click()
        minute_input.first.fill(f"{minute:02d}")

    meridian_btn = modal.locator("ngb-timepicker .ngb-tp-meridian button")
    if meridian_btn.count() > 0:
        current_meridian = meridian_btn.first.inner_text().strip().upper()
        if target_meridian in ("AM", "PM") and current_meridian != target_meridian:
            meridian_btn.first.click()

    modal.page.wait_for_timeout(200)

    # 4. Confirm by clicking 'Aceptar' / 'Ok'
    ok_btn = modal.locator("app-date-time-picker button").filter(has_text=re.compile(r"Aceptar|Ok|Confirm", re.IGNORECASE))
    if ok_btn.count() > 0:
        ok_btn.first.click()
        modal.page.wait_for_timeout(200)


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
    expense_time: str = "",
) -> None:
    """Load a single expense into Daily Expenses 4."""
    modal = page.locator(MODAL_ID)

    # 1. If modal is not already open, ensure we are on movements and open modal
    if not modal.is_visible():
        if "/movements" not in page.url:
            movimientos_link = page.get_by_role("link", name=re.compile(r"Movimientos|Movements", re.IGNORECASE))
            if movimientos_link.count() > 0:
                movimientos_link.first.click()
                page.wait_for_load_state("networkidle")

        fab_btn = page.locator("button.btn-floating, button.floating-action-button").or_(
            page.get_by_role("button").filter(has_text=re.compile(r"^\s*$"))
        )
        if fab_btn.count() > 0:
            fab_btn.last.click()
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

    # 7. Date & Time picker via <app-date-time-picker>
    _set_date_and_time(modal, expense_date=expense_date, expense_time=expense_time)

    # 8. Save button
    save_btn = modal.locator("button.save-movement-button").or_(
        page.get_by_role("button", name=re.compile(r"Save|Guardar", re.IGNORECASE))
    )
    save_btn.first.click()
    page.wait_for_load_state("networkidle")
    try:
        modal.wait_for(state="hidden", timeout=6_000)
    except Exception:
        pass
    sleep(0.5)


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
            tx_time = record.get("time", "") or getattr(record.get("tx"), "time", "")

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
                    expense_time=tx_time,
                )
                console.print("[green]✅[/green]")
            except Exception as exc:
                console.print(f"[red]❌ {exc}[/red]")

        browser.close()
