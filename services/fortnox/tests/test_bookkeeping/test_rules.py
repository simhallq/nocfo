"""Tests for YAML-based transaction categorization rules."""

from decimal import Decimal
from pathlib import Path

import pytest

from fortnox.bookkeeping.rules import (
    CategorizedTransaction,
    RuleEngine,
    UncategorizedTransaction,
)


@pytest.fixture
def engine():
    rules_path = Path(__file__).parent.parent.parent / "rules.yaml"
    engine = RuleEngine(rules_path=rules_path)
    engine.load()
    return engine


class TestRuleEngine:
    def test_salary_match(self, engine):
        result = engine.categorize("LÖNEUTBETALNING DEC", Decimal("-35000"))
        assert isinstance(result, CategorizedTransaction)
        assert result.rule_name == "salary_payment"
        assert result.debit_account == 7210
        assert result.credit_account == 1930

    def test_bank_fees_match(self, engine):
        result = engine.categorize("MÅNADSAVGIFT FÖRETAGSKONTO", Decimal("-150"))
        assert isinstance(result, CategorizedTransaction)
        assert result.rule_name == "bank_fees"
        assert result.debit_account == 6570

    def test_software_subscription(self, engine):
        result = engine.categorize("GITHUB TEAM SUBSCRIPTION", Decimal("-400"))
        assert isinstance(result, CategorizedTransaction)
        assert result.rule_name == "software_subscription"
        assert result.debit_account == 5420

    def test_customer_payment(self, engine):
        result = engine.categorize("INBETALNING OCR 12345", Decimal("10000"))
        assert isinstance(result, CategorizedTransaction)
        assert result.rule_name == "customer_payment"

    def test_no_match(self, engine):
        result = engine.categorize("RANDOM UNKNOWN TRANSACTION", Decimal("-100"))
        assert isinstance(result, UncategorizedTransaction)
        assert result.reason == "no_matching_rule"

    def test_case_insensitive(self, engine):
        result = engine.categorize("lön december", Decimal("-35000"))
        assert isinstance(result, CategorizedTransaction)
        assert result.rule_name == "salary_payment"
