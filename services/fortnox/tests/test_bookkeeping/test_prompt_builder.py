"""Tests for AccountingPromptBuilder — YAML loading, threshold logic, prompt assembly."""

from pathlib import Path

import pytest

from fortnox.bookkeeping.prompt_builder import AccountingPromptBuilder


@pytest.fixture
def builder():
    """Builder using the real accounting_rules.yaml."""
    return AccountingPromptBuilder()


@pytest.fixture
def builder_from_custom(tmp_path):
    """Create a builder from a custom YAML config."""
    def _make(yaml_content: str) -> AccountingPromptBuilder:
        config = tmp_path / "rules.yaml"
        config.write_text(yaml_content)
        return AccountingPromptBuilder(config_path=config)
    return _make


class TestYAMLLoading:
    def test_loads_default_config(self, builder):
        assert builder._config is not None
        assert "thresholds" in builder._config
        assert "vat_rules" in builder._config
        assert "account_guidance" in builder._config

    def test_missing_config_falls_back_gracefully(self, tmp_path):
        builder = AccountingPromptBuilder(config_path=tmp_path / "nonexistent.yaml")
        assert builder._config == {}
        # Should still build a prompt without crashing
        prompt = builder.build_system_prompt(transaction_year=2026)
        assert "bookkeeping" in prompt.lower()

    def test_invalid_yaml_falls_back(self, tmp_path):
        bad = tmp_path / "bad.yaml"
        bad.write_text(": : : not valid yaml [[[")
        builder = AccountingPromptBuilder(config_path=bad)
        assert builder._config == {}


class TestThresholdComputation:
    def test_2026_threshold(self, builder):
        # 59200 / 2 = 29600
        assert builder.get_threshold(2026) == 29600

    def test_2025_threshold(self, builder):
        # 58800 / 2 = 29400
        assert builder.get_threshold(2025) == 29400

    def test_2024_threshold(self, builder):
        # 57300 / 2 = 28650
        assert builder.get_threshold(2024) == 28650

    def test_missing_year_falls_back_to_most_recent(self, builder):
        # 2030 not in config, should fall back to 2026 (most recent)
        threshold = builder.get_threshold(2030)
        assert threshold == 29600  # Same as 2026

    def test_custom_threshold(self, builder_from_custom):
        builder = builder_from_custom("""
thresholds:
  prisbasbelopp:
    2026: 60000
""")
        assert builder.get_threshold(2026) == 30000

    def test_empty_config_uses_default(self):
        builder = AccountingPromptBuilder.__new__(AccountingPromptBuilder)
        builder._config = {}
        assert builder.get_threshold(2026) == 29600  # hardcoded fallback


class TestPromptAssembly:
    def test_contains_threshold_value(self, builder):
        prompt = builder.build_system_prompt(transaction_year=2026)
        assert "29,600" in prompt or "29600" in prompt

    def test_contains_vat_rules(self, builder):
        prompt = builder.build_system_prompt(transaction_year=2026)
        assert "25%" in prompt
        assert "12%" in prompt
        assert "6%" in prompt

    def test_contains_account_guidance(self, builder):
        prompt = builder.build_system_prompt(transaction_year=2026)
        assert "5410" in prompt
        assert "1250" in prompt
        assert "Förbrukningsinventarier" in prompt

    def test_contains_json_schema(self, builder):
        prompt = builder.build_system_prompt(transaction_year=2026)
        assert "suggested_account" in prompt
        assert "account_reasoning" in prompt

    def test_company_context_included(self, builder):
        prompt = builder.build_system_prompt(
            transaction_year=2026,
            customer_id="hem-atelier-styrman",
        )
        assert "Hem Atelier Styrmans AB" in prompt
        assert "1291" in prompt or "Konst" in prompt.lower()

    def test_company_context_excluded_when_no_id(self, builder):
        prompt = builder.build_system_prompt(transaction_year=2026)
        assert "Hem Atelier Styrmans AB" not in prompt

    def test_unknown_company_excluded(self, builder):
        prompt = builder.build_system_prompt(
            transaction_year=2026,
            customer_id="unknown-company",
        )
        assert "Company Context" not in prompt

    def test_supplier_history_included(self, builder):
        history = [
            {"date": "2026-01-15", "description": "INET AB", "accounts": "5410(D 21590)", "amount": "21590"},
        ]
        prompt = builder.build_system_prompt(
            transaction_year=2026,
            supplier_history=history,
        )
        assert "INET AB" in prompt
        assert "Recent Voucher History" in prompt

    def test_supplier_history_excluded_when_empty(self, builder):
        prompt = builder.build_system_prompt(transaction_year=2026, supplier_history=None)
        assert "Recent Voucher History" not in prompt

    def test_supplier_history_capped_at_20(self, builder):
        history = [
            {"date": f"2026-01-{i:02d}", "description": f"Vendor {i}", "accounts": "5410", "amount": "100"}
            for i in range(1, 31)  # 30 items
        ]
        prompt = builder.build_system_prompt(transaction_year=2026, supplier_history=history)
        # Should only contain 20 vendor entries
        assert "Vendor 20" in prompt
        assert "Vendor 21" not in prompt

    def test_threshold_exception_for_art(self, builder):
        prompt = builder.build_system_prompt(
            transaction_year=2026,
            customer_id="hem-atelier-styrman",
        )
        # Should mention art exception somewhere
        assert "konst" in prompt.lower() or "1291" in prompt
