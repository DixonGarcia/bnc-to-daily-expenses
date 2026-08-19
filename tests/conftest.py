"""Shared pytest fixtures for the BNC importer test suite."""
from __future__ import annotations

import pytest

from importer.db import Database


@pytest.fixture
def db(tmp_path):
    """Fresh Database instance backed by a temp file for each test."""
    return Database(tmp_path / "test.db")
