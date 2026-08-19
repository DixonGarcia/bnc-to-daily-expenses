# Coding Conventions & Rules

Rules every AI agent must follow when working on this codebase.

---

## 🐍 Python Style

- **Python version**: 3.12+. Use modern features freely (`tomllib`, `match`, `X | Y` union types).
- **Formatter**: Follow PEP 8. Line length max 100 chars.
- **Type hints**: Always annotate public function signatures. Use `from __future__ import annotations` at the top of each file.
- **Decimal arithmetic**: Always use `decimal.Decimal` for monetary amounts — never `float`.
- **Dataclasses**: Prefer `@dataclass` for data-holding objects (e.g. `BNCTransaction`, `ClassifiedTransaction`).
- **Pathlib**: Use `pathlib.Path` instead of `os.path` for all file operations.
- **f-strings**: Preferred over `.format()` or `%`.

---

## 📝 Docstrings

Use Google-style docstrings for all public classes and functions:

```python
def to_usd(amount_bsf: Decimal, rate: Decimal) -> Decimal:
    """Convert bolivares to USD using the active exchange rate.

    Args:
        amount_bsf: Amount in Venezuelan Bolivares (positive).
        rate: Exchange rate in Bs per USD (e.g. Decimal("845.88")).

    Returns:
        Amount in USD rounded to 2 decimal places.

    Raises:
        ValueError: If rate is zero or negative.
    """
```

---

## 🧪 Testing Conventions

### Framework
- **pytest** — no unittest, no nose.
- **pytest-asyncio** for any async tests (Playwright).

### File naming
- Test files: `tests/test_<module>.py` (mirrors `importer/<module>.py`)
- Shared fixtures: `tests/conftest.py`

### Test structure — descriptive class grouping

```python
class TestBNCParser:
    """Tests for the BNC TSV parser."""

    class WhenInputIsValid:
        def test_returns_list_of_transactions(self, sample_statement):
            ...

        def test_filters_out_commissions(self, sample_statement):
            ...

    class WhenInputIsEmpty:
        def test_returns_empty_list(self):
            ...
```

### Fixture conventions (`conftest.py`)

```python
@pytest.fixture
def db(tmp_path):
    """Fresh in-memory SQLite DB for each test."""
    return Database(tmp_path / "test.db")

@pytest.fixture
def sample_statement():
    """Raw content of the BNC example input file."""
    return Path("input example.txt").read_text(encoding="utf-8")

@pytest.fixture
def active_rate():
    """Standard exchange rate used across tests."""
    return Decimal("845.88")
```

### Assertion style
- Use plain `assert` — never `assertEqual` / `assertTrue`.
- One logical assertion per test when possible.
- Use descriptive variable names, not `result` alone:

```python
# ✅ Good
transactions = parse(sample_statement)
assert len(transactions) == 5

# ❌ Avoid
r = parse(s)
assert len(r) == 5
```

### Running tests
```bash
pytest tests/ -v --tb=short        # all tests
pytest tests/test_parser.py -v     # single module
pytest -k "test_filters" -v        # by name pattern
```

---

## 🗄️ Database Conventions

- Always use `with db.connection:` context manager for write transactions.
- Raw SQL only — no ORM. Keep queries in `db.py`, not scattered across modules.
- Table and column names: `snake_case`.
- Boolean columns: stored as `INTEGER` (0/1), not `BOOLEAN`.

---

## 🖥️ CLI Conventions

- Use **Rich** for all output (tables, progress, colored status).
- Use **Questionary** for all interactive prompts (select, confirm, text).
- Always support `--dry-run` flag — preview without side effects.
- Print a summary table before asking "Proceed?" — never auto-proceed silently.
- Status icons convention:
  - `✅` success / processed
  - `⚠️` warning / ambiguous / needs input
  - `⏭️` skipped / already processed
  - `❌` error

---

## 🌿 Git Conventions

### Commit message format (Conventional Commits)
```
<type>: <short description>

[optional body]
```

Types:
| Type | When |
|---|---|
| `feat` | New feature or module |
| `test` | Adding or updating tests |
| `fix` | Bug fix |
| `refactor` | Code change without behavior change |
| `chore` | Tooling, config, deps |
| `docs` | README, AGENTS.md, comments |

### Branch + PR Workflow

Every module follows this branch lifecycle:

```
main
 └── module/<name>        ← agent works here
      ├── commit: docs: add _product/<name>.md spec
      ├── commit: test: add <name> specs          ← RED
      └── commit: feat: implement <name>          ← GREEN
           └── Pull Request → reviewed by user → merge to main
```

**Branch naming**: `module/<module-name>`
Examples: `module/db`, `module/parser`, `module/classifier`

**Step-by-step:**

```bash
# 1. Always branch from a fresh main
git checkout main && git pull
git checkout -b module/<name>

# 2. Write spec doc + tests, commit as RED
git add _product/<name>.md tests/test_<name>.py
git commit -m "test: add <name> specs"
git push -u origin module/<name>

# 3. Open PR immediately (draft) so user can track progress
gh pr create --draft --title "module: <name>" --body "Spec and tests for <name> module."

# 4. Implement until GREEN, commit
git add importer/<name>.py
git commit -m "feat: implement <name>"
git push

# 5. Mark PR as ready for review
gh pr ready

# 6. User reviews, approves, and merges via GitHub UI
```

### Commit order within a module branch
1. `docs: add _product/<name>.md spec`
2. `test: add <name> specs` — failing tests (RED)
3. `feat: implement <name>` — passing implementation (GREEN)
4. `refactor: <what changed>` — optional cleanup

---

## 🔒 Security Rules

- **Never commit** `data/config.toml` (real config with account names).
- **Never commit** `data/session_cookies.json` (web session).
- **Never commit** `data/importer.db` (contains personal transaction history).
- All three are already in `.gitignore` — double-check before every push.
- Do not log or print raw bank statement content in production output.
