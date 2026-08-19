"""Tests for importer/db.py — spec: _product/db.md"""
from __future__ import annotations

import pytest

from importer.db import Database, ExchangeRate, MerchantRule


class TestDatabaseInitialization:
    """Database is created automatically when the file does not exist."""

    def test_creates_db_file_if_missing(self, tmp_path):
        db_path = tmp_path / "new.db"
        assert not db_path.exists()
        Database(db_path)
        assert db_path.exists()

    def test_creates_tables_on_init(self, db):
        # If tables don't exist, subsequent operations would raise errors.
        # A successful init means all three tables are present.
        assert db.all_rules() == []
        assert db.get_active_rate() is None
        assert db.is_processed("any-ref") is False

    def test_init_is_idempotent(self, tmp_path):
        """Calling Database twice on same file does not destroy data."""
        db_path = tmp_path / "idempotent.db"
        db1 = Database(db_path)
        db1.add_rule("KEYLA", "Comida", "Charcutería")
        db2 = Database(db_path)
        assert len(db2.all_rules()) == 1


class TestMerchantRules:

    class WhenAddingARule:
        def test_returns_merchant_rule_dataclass(self, db):
            rule = db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
            assert isinstance(rule, MerchantRule)
            assert rule.pattern == "KEYLA PATRICIA"
            assert rule.category == "Comida"
            assert rule.description == "Charcutería"
            assert rule.is_regex is False

        def test_persists_rule_to_db(self, db):
            db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
            rules = db.all_rules()
            assert len(rules) == 1
            assert rules[0].pattern == "KEYLA PATRICIA"

        def test_can_add_regex_rule(self, db):
            rule = db.add_rule(r"FARM\w+", "Salud", "Farmacia", is_regex=True)
            assert rule.is_regex is True

        def test_raises_on_duplicate_pattern(self, db):
            db.add_rule("KEYLA", "Comida", "Charcutería")
            with pytest.raises(ValueError, match="already exists"):
                db.add_rule("KEYLA", "Otro", "Otro")

    class WhenFindingARule:
        def test_returns_none_when_no_rules_exist(self, db):
            result = db.find_rule("KEYLA PATRICIA SANTAMA COJEDES")
            assert result is None

        def test_finds_literal_match_case_insensitive(self, db):
            db.add_rule("KEYLA PATRICIA", "Comida", "Charcutería")
            result = db.find_rule("keyla patricia santama cojedes")
            assert result is not None
            assert result.description == "Charcutería"

        def test_finds_partial_match_within_description(self, db):
            db.add_rule("FARMAIGNACIO", "Salud", "Farmacia Ignacio")
            result = db.find_rule("FARMAIGNACIO TINAQUILL CCS NOROESTE VEN ZONA=")
            assert result is not None
            assert result.description == "Farmacia Ignacio"

        def test_returns_none_when_no_pattern_matches(self, db):
            db.add_rule("KEYLA", "Comida", "Charcutería")
            result = db.find_rule("MULTIMARCAS 2022 C A SAN CARLOS")
            assert result is None

        def test_finds_regex_rule(self, db):
            db.add_rule(r"FARM\w+", "Salud", "Farmacia", is_regex=True)
            result = db.find_rule("FARMATODO SAN CARLOS")
            assert result is not None
            assert result.description == "Farmacia"

        def test_prefers_literal_over_regex_when_both_match(self, db):
            db.add_rule(r"FARM\w+", "Salud", "Farmacia genérica", is_regex=True)
            db.add_rule("FARMAIGNACIO", "Salud", "Farmacia Ignacio")
            result = db.find_rule("FARMAIGNACIO TINAQUILL")
            assert result.description == "Farmacia Ignacio"

    class WhenListingAllRules:
        def test_returns_empty_list_when_no_rules(self, db):
            assert db.all_rules() == []

        def test_returns_all_rules_ordered_by_id(self, db):
            db.add_rule("AAA", "Comida", "Primero")
            db.add_rule("BBB", "Salud", "Segundo")
            rules = db.all_rules()
            assert len(rules) == 2
            assert rules[0].description == "Primero"
            assert rules[1].description == "Segundo"


class TestProcessedTransactions:

    class WhenCheckingIfProcessed:
        def test_returns_false_for_unknown_reference(self, db):
            assert db.is_processed("819155311") is False

        def test_returns_true_after_marking_as_processed(self, db):
            db.mark_processed("819155311", amount_usd=10, description="Charcutería")
            assert db.is_processed("819155311") is True

    class WhenMarkingAsProcessed:
        def test_stores_reference_with_metadata(self, db):
            db.mark_processed("819155311", amount_usd=10, description="Charcutería")
            assert db.is_processed("819155311") is True

        def test_raises_on_duplicate_reference(self, db):
            db.mark_processed("819155311", amount_usd=10, description="Charcutería")
            with pytest.raises(ValueError, match="already processed"):
                db.mark_processed("819155311", amount_usd=10, description="Charcutería")


class TestExchangeRates:

    class WhenNoRatesExist:
        def test_get_active_rate_returns_none(self, db):
            assert db.get_active_rate() is None

    class WhenAddingARate:
        def test_returns_exchange_rate_dataclass(self, db):
            rate = db.add_rate(845.88, notes="100 USDT → BNC")
            assert isinstance(rate, ExchangeRate)
            assert rate.rate == 845.88
            assert rate.notes == "100 USDT → BNC"

        def test_registered_at_is_set_automatically(self, db):
            rate = db.add_rate(845.88)
            assert rate.registered_at is not None
            assert len(rate.registered_at) > 0

        def test_notes_defaults_to_empty_string(self, db):
            rate = db.add_rate(845.88)
            assert rate.notes == ""

        def test_raises_when_rate_is_zero(self, db):
            with pytest.raises(ValueError, match="positive"):
                db.add_rate(0)

        def test_raises_when_rate_is_negative(self, db):
            with pytest.raises(ValueError, match="positive"):
                db.add_rate(-100.0)

    class WhenGettingActiveRate:
        def test_returns_most_recently_added_rate(self, db):
            db.add_rate(800.00, notes="first")
            db.add_rate(845.88, notes="second")
            active = db.get_active_rate()
            assert active.rate == 845.88
            assert active.notes == "second"

        def test_returns_exchange_rate_dataclass(self, db):
            db.add_rate(845.88)
            active = db.get_active_rate()
            assert isinstance(active, ExchangeRate)
