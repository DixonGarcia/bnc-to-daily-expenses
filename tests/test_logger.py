"""Tests for importer/logger.py"""
from __future__ import annotations

from pathlib import Path
from importer.logger import (
    log_session_start,
    log_tx_decision,
    log_sync_attempt,
    log_sync_success,
    log_sync_error,
    log_session_end,
    _LOG_FILE,
)


class TestLogger:

    def test_logger_creates_log_file_and_writes_entries(self):
        log_session_start("tmp/sample.txt", dry_run=True)
        assert _LOG_FILE.exists()

        log_tx_decision(
            idx=1,
            total=5,
            ref="123456",
            action="CLASSIFIED",
            raw_desc="FARMAIGNACIO",
            cat="Salud",
            app_desc="Farmacia",
            amount_bs="-6000",
            amount_usd=7,
            rate="850",
            rule_saved=True,
        )
        log_sync_attempt("123456", "Farmacia", "Salud", 7, "25/08/2026", "11:00:00")
        log_sync_success("123456", "Farmacia", 7)
        log_sync_error("999", "Failed Tx", "Timeout Error")
        log_session_end(5, 1, 3, 1)

        content = _LOG_FILE.read_text(encoding="utf-8")
        assert "STARTING BNC IMPORTER SESSION" in content
        assert "FARMAIGNACIO" in content
        assert "Farmacia" in content
        assert "SYNC SUCCESS" in content
        assert "SYNC FAILED" in content
        assert "SESSION SUMMARY" in content
