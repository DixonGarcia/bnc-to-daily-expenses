# Module Spec: `web_automator.py`

## Responsibility

Automates loading classified, converted, and rounded expenses into **Gastos Diarios 4** (`https://dailyexpenses4.com/home`) using Playwright.

---

## Authentication & Session Management

- **Zero Credentials in Git**: Passwords and emails are never entered into configuration files or scripts.
- **First Run**: Launches a headed Chromium browser. The user signs in with Google OAuth directly in the browser.
- **Session Persistence**: Saves the complete browser context storage state (Firebase cookies + `localStorage` auth tokens) to `data/session_cookies.json` (gitignored).
- **Subsequent Runs**: Launches headless Chromium using `context(storage_state=session_cookies.json)`, restoring the active session instantly without prompts.

---

## Angular DOM Components & Selectors

The modal dialog is `#ModalAddMovements`:

| UI Action | Target Component / Selector | Strategy |
|---|---|---|
| Open Modal | `button:has-text("Nuevo movimiento"), button:has-text("New movement")` | Click button or floating action button |
| Amount Input | `#amount` | `fill(str(usd_amount))` |
| Account Picker | `app-selector-account button` | Click dropdown trigger → Select item matching account name (e.g. `Binance`) |
| Category Picker | `app-selector-category button` | Click dropdown trigger → Select item matching category (e.g. `Comida`, `Salud`) |
| Description Input | `#description` | `fill(description)` |
| Date Picker | `app-date-time-picker button.btn` | Click trigger → select day in `mat-calendar button.mat-calendar-body-cell` → confirm with `Aceptar`/`Ok` |
| Save Movement | `button.save-movement-button` | Click save → wait for modal to close / movement to appear |

---

## Public Interface

```python
def run_automation(records: list[dict], account: str, config: dict) -> None:
    """Load a batch of expense records into Daily Expenses 4.

    Args:
        records: List of classified expense dictionaries with date, description, category, usd_rounded.
        account: Target account name (e.g. "Binance").
        config: Application configuration dictionary.
    """
```
