"""Tests for importer/web_automator.py — spec: _product/web-automator.md"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from importer.web_automator import (
    _parse_calendar_header,
    _parse_time_12h,
    _select_account,
    _select_category,
)


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


class TestSelectAccount:

    class WhenUsingNewModalSelector:
        def test_opens_modal_and_clicks_matching_account_row(self):
            modal = MagicMock()
            legacy_locator = MagicMock()
            legacy_locator.count.return_value = 0

            acc_btn = MagicMock()
            acc_trigger = MagicMock()
            acc_trigger.or_.return_value.first = acc_btn
            modal.locator.side_effect = lambda sel, *args, **kwargs: (
                legacy_locator if "app-selector-account" in sel else acc_trigger
            )

            acc_modal = MagicMock()
            modal.page.locator.return_value = acc_modal

            row_item = MagicMock()
            row_item.count.return_value = 1
            filtered_locator = MagicMock()
            filtered_locator.first = row_item
            acc_modal.locator.return_value.filter.return_value = filtered_locator
            acc_modal.is_visible.return_value = False

            _select_account(modal, "Binance")

            acc_btn.click.assert_called()
            acc_modal.wait_for.assert_called_with(state="visible", timeout=6000)
            row_item.click.assert_called()

    class WhenUsingLegacySelector:
        def test_clicks_legacy_dropdown_and_item(self):
            modal = MagicMock()
            legacy_locator = MagicMock()
            legacy_locator.count.return_value = 1
            legacy_btn = MagicMock()
            legacy_locator.first = legacy_btn

            dropdown_item = MagicMock()
            dropdown_item.count.return_value = 1

            item_locator = MagicMock()
            item_locator.filter.return_value.first = dropdown_item

            def modal_locator_mock(sel, *args, **kwargs):
                if "app-selector-account button" in sel:
                    return legacy_locator
                if "dropdown-menu" in sel:
                    return item_locator
                return MagicMock()

            modal.locator.side_effect = modal_locator_mock

            _select_account(modal, "Binance")

            legacy_btn.click.assert_called()
            dropdown_item.click.assert_called()


class TestSelectCategory:

    class WhenUsingNewModalSelector:
        def test_opens_modal_and_clicks_matching_category_row(self):
            modal = MagicMock()
            legacy_locator = MagicMock()
            legacy_locator.count.return_value = 0

            cat_btn = MagicMock()
            cat_trigger = MagicMock()
            cat_trigger.or_.return_value.first = cat_btn
            modal.locator.side_effect = lambda sel, *args, **kwargs: (
                legacy_locator if "app-selector-category" in sel else cat_trigger
            )

            cat_modal = MagicMock()
            modal.page.locator.return_value = cat_modal

            row_item = MagicMock()
            row_item.count.return_value = 1
            filtered_locator = MagicMock()
            filtered_locator.first = row_item
            cat_modal.locator.return_value.filter.return_value = filtered_locator
            cat_modal.is_visible.return_value = False

            _select_category(modal, "Comida")

            cat_btn.click.assert_called()
            cat_modal.wait_for.assert_called_with(state="visible", timeout=6000)
            row_item.click.assert_called()

    class WhenUsingLegacySelector:
        def test_clicks_legacy_dropdown_and_item(self):
            modal = MagicMock()
            legacy_locator = MagicMock()
            legacy_locator.count.return_value = 1
            legacy_btn = MagicMock()
            legacy_locator.first = legacy_btn

            dropdown_item = MagicMock()
            dropdown_item.count.return_value = 1

            item_locator = MagicMock()
            item_locator.filter.return_value.first = dropdown_item

            def modal_locator_mock(sel, *args, **kwargs):
                if "app-selector-category button" in sel:
                    return legacy_locator
                if "dropdown-menu" in sel:
                    return item_locator
                return MagicMock()

            modal.locator.side_effect = modal_locator_mock

            _select_category(modal, "Comida")

            legacy_btn.click.assert_called()
            dropdown_item.click.assert_called()

