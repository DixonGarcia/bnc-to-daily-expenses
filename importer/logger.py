"""Logging system for BNC to Daily Expenses importer.

Writes complete execution logs to tmp/importer.log for auditing, debugging,
and tracking synced vs skipped vs failed transactions.
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

_LOG_DIR = Path("tmp")
_LOG_FILE = _LOG_DIR / "importer.log"

logger = logging.getLogger("bnc_importer")


def setup_logger(log_to_console: bool = False) -> logging.Logger:
    """Initialize and configure the importer file logger."""
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

    # File handler (overwrite or append per run)
    fh = logging.FileHandler(str(_LOG_FILE), mode="a", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    if log_to_console:
        ch = logging.StreamHandler()
        ch.setLevel(logging.INFO)
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    return logger


def log_session_start(statement_path: str | Path, dry_run: bool) -> None:
    """Log the start of an import session."""
    setup_logger()
    logger.info("=" * 80)
    mode = "DRY-RUN" if dry_run else "LIVE IMPORT"
    logger.info("STARTING BNC IMPORTER SESSION [%s]", mode)
    logger.info("Statement file: %s", statement_path)
    logger.info("Timestamp: %s", datetime.now().isoformat())
    logger.info("=" * 80)


def log_tx_decision(
    idx: int,
    total: int,
    ref: str,
    action: str,
    raw_desc: str,
    cat: str = "",
    app_desc: str = "",
    amount_bs: str = "",
    amount_usd: int | str = "",
    rate: str = "",
    rule_saved: bool = False,
) -> None:
    """Log classification decision for a single transaction."""
    logger.info(
        "TX [%d/%d] Ref: %s | Action: %s | Bs: %s | USD: $%s (@%s) | "
        "App: [%s] %s | Rule Saved: %s | Raw: %s",
        idx,
        total,
        ref,
        action.upper(),
        amount_bs,
        str(amount_usd),
        rate,
        cat,
        app_desc,
        rule_saved,
        raw_desc,
    )


def log_sync_attempt(
    ref: str,
    desc: str,
    cat: str,
    amt: int,
    date_str: str,
    time_str: str,
) -> None:
    """Log the start of web sync for a transaction."""
    logger.info(
        "SYNC ATTEMPT -> Ref: %s | [%s] %s | $%d | Date: %s %s",
        ref,
        cat,
        desc,
        amt,
        date_str,
        time_str,
    )


def log_sync_success(ref: str, desc: str, amt: int) -> None:
    """Log successful web sync."""
    logger.info("SYNC SUCCESS -> Ref: %s | %s | $%d", ref, desc, amt)


def log_sync_error(ref: str, desc: str, error: Exception | str) -> None:
    """Log failed web sync with error message."""
    logger.error("SYNC FAILED  -> Ref: %s | %s | Error: %s", ref, desc, str(error))


def log_session_end(
    total_parsed: int,
    synced_count: int,
    skipped_count: int,
    failed_count: int,
) -> None:
    """Log the summary of the completed import session."""
    logger.info("-" * 80)
    logger.info(
        "SESSION SUMMARY -> Parsed: %d | Synced: %d | Skipped: %d | Failed: %d",
        total_parsed,
        synced_count,
        skipped_count,
        failed_count,
    )
    logger.info("=" * 80 + "\n")
