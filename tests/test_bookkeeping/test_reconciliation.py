"""Tests for bank reconciliation matching algorithm."""

from datetime import date
from decimal import Decimal

import pytest

from nocfo.bookkeeping.reconciliation import (
    BankTransaction,
    LedgerEntry,
    MatchType,
    ReconciliationEngine,
)


@pytest.fixture
def engine():
    return ReconciliationEngine(date_tolerance_days=3)


class TestExactMatch:
    def test_same_amount_same_date(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1000"), description="Payment"
            )
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 1),
                amount=Decimal("1000"),
                description="Payment",
                account=1930,
            )
        ]

        result = engine.reconcile(bank, ledger)

        assert len(result.matches) == 1
        assert result.matches[0].match_type == MatchType.EXACT
        assert result.matches[0].confidence == 1.0
        assert len(result.unmatched_bank) == 0
        assert len(result.unmatched_ledger) == 0

    def test_different_amounts_no_match(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1000"), description="Payment"
            )
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 1),
                amount=Decimal("999"),
                description="Payment",
                account=1930,
            )
        ]

        result = engine.reconcile(bank, ledger)

        assert len(result.matches) == 0
        assert len(result.unmatched_bank) == 1
        assert len(result.unmatched_ledger) == 1


class TestFuzzyMatch:
    def test_same_amount_close_date(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1000"), description="Payment"
            )
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 3),
                amount=Decimal("1000"),
                description="Payment",
                account=1930,
            )
        ]

        result = engine.reconcile(bank, ledger)

        assert len(result.matches) == 1
        assert result.matches[0].match_type == MatchType.FUZZY
        assert result.matches[0].confidence < 1.0

    def test_same_amount_beyond_tolerance(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1000"), description="Payment"
            )
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 10),
                amount=Decimal("1000"),
                description="Payment",
                account=1930,
            )
        ]

        result = engine.reconcile(bank, ledger)

        assert len(result.matches) == 0


class TestOneToManyMatch:
    def test_one_bank_two_ledger(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1500"), description="Combined"
            )
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 1),
                amount=Decimal("1000"),
                description="Part 1",
                account=1930,
            ),
            LedgerEntry(
                voucher_series="A",
                voucher_number=2,
                date=date(2024, 12, 1),
                amount=Decimal("500"),
                description="Part 2",
                account=1930,
            ),
        ]

        result = engine.reconcile(bank, ledger)

        assert len(result.matches) == 1
        assert result.matches[0].match_type == MatchType.ONE_TO_MANY
        assert len(result.matches[0].ledger_entries) == 2


class TestReconciliationResult:
    def test_fully_reconciled(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1000"), description="P1"
            )
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 1),
                amount=Decimal("1000"),
                description="P1",
                account=1930,
            )
        ]

        result = engine.reconcile(bank, ledger)
        assert result.is_fully_reconciled
        assert result.match_rate == 1.0

    def test_partial_reconciliation(self, engine):
        bank = [
            BankTransaction(
                id="b1", date=date(2024, 12, 1), amount=Decimal("1000"), description="P1"
            ),
            BankTransaction(
                id="b2", date=date(2024, 12, 2), amount=Decimal("2000"), description="P2"
            ),
        ]
        ledger = [
            LedgerEntry(
                voucher_series="A",
                voucher_number=1,
                date=date(2024, 12, 1),
                amount=Decimal("1000"),
                description="P1",
                account=1930,
            )
        ]

        result = engine.reconcile(bank, ledger)
        assert not result.is_fully_reconciled
        assert result.match_rate == 0.5
