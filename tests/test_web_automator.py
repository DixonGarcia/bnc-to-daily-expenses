"""Tests for importer/web_automator.py — spec: _product/web-automator.md"""
from __future__ import annotations

import pytest

from importer.web_automator import _parse_calendar_header, _parse_time_12h


class TestParseCalendarHeader:

    class WhenGivenSpanishMonthAndYear:
        def test_parses_julio(self):
            assert _parse_calendar_header("JUL 2026") == (2026, 7)

        def test_parses_agosto(self):
            assert _parse_calendar_header("AGO 2026") == (2026, 8)

        def test_parses_full_month_name(self):
            assert _parse_calendar_header("AGOSTO 2026") == (2026, 8)

        def test_parses_diciembre(self):
            assert _parse_calendar_header("DIC 2025") == (2025, 12)

        def test_parses_enero(self):
            assert _parse_calendar_header("ENE 2027") == (2027, 1)

    class WhenGivenInvalidHeader:
        def test_returns_none_for_empty_string(self):
            assert _parse_calendar_header("") is None

        def test_returns_none_for_unrecognized_month(self):
            assert _parse_calendar_header("UNKNOWN 2026") is None


class TestParseTime12h:

    class WhenGiven24HourTimeString:
        def test_parses_morning_time(self):
            assert _parse_time_12h("08:35:15.850") == (8, 35, "AM")

        def test_parses_afternoon_time(self):
            assert _parse_time_12h("18:14:47.155") == (6, 14, "PM")

        def test_parses_noon(self):
            assert _parse_time_12h("12:00:00") == (12, 0, "PM")

        def test_parses_midnight(self):
            assert _parse_time_12h("00:30:00") == (12, 30, "AM")

        def test_parses_evening(self):
            assert _parse_time_12h("23:59:00") == (11, 59, "PM")

    class WhenGivenInvalidOrEmptyString:
        def test_returns_default_for_empty(self):
            assert _parse_time_12h("") == (12, 0, "AM")
