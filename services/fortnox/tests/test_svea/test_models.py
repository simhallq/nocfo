"""Tests for Svea Bank Pydantic models."""

from datetime import date
from decimal import Decimal

import pytest

from fortnox.svea.api.models import (
    SveaAccount,
    SveaPaymentBatch,
    SveaPaymentOrder,
    SveaTransaction,
)


class TestSveaAccount:
    def test_basic_creation(self):
        acc = SveaAccount(
            account_id="abc-123",
            account_number="9960-1234567",
            name="Företagskonto",
            balance=Decimal("50000.00"),
            available_balance=Decimal("48000.00"),
        )
        assert acc.account_id == "abc-123"
        assert acc.balance == Decimal("50000.00")
        assert acc.currency == "SEK"

    def test_decimal_coercion_from_float(self):
        acc = SveaAccount(
            account_id="x",
            account_number="1234",
            name="Test",
            balance=50000.50,
            available_balance=48000,
        )
        assert acc.balance == Decimal("50000.5")

    def test_none_balance_defaults_to_zero(self):
        acc = SveaAccount(
            account_id="x",
            account_number="1234",
            name="Test",
            balance=None,
            available_balance=None,
        )
        assert acc.balance == Decimal("0")
        assert acc.available_balance == Decimal("0")


class TestSveaTransaction:
    def test_basic_creation(self):
        txn = SveaTransaction(
            transaction_id="txn-001",
            booking_date=date(2026, 3, 15),
            amount=Decimal("-1500.00"),
            description="Bankgiro 123-4567",
        )
        assert txn.transaction_id == "txn-001"
        assert txn.amount == Decimal("-1500.00")
        assert txn.value_date is None
        assert txn.reference == ""

    def test_full_fields(self):
        txn = SveaTransaction(
            transaction_id="txn-002",
            booking_date=date(2026, 3, 15),
            value_date=date(2026, 3, 16),
            amount=Decimal("25000"),
            balance_after=Decimal("75000"),
            description="Inbetalning OCR 12345",
            reference="12345",
            counterparty="Kund AB",
            transaction_type="bankGiroCreditTransaction",
        )
        assert txn.value_date == date(2026, 3, 16)
        assert txn.balance_after == Decimal("75000")
        assert txn.counterparty == "Kund AB"

    def test_amount_coercion(self):
        txn = SveaTransaction(
            transaction_id="x",
            booking_date=date(2026, 1, 1),
            amount=-1500.50,
            description="test",
        )
        assert txn.amount == Decimal("-1500.5")

    def test_none_balance_after(self):
        txn = SveaTransaction(
            transaction_id="x",
            booking_date=date(2026, 1, 1),
            amount=100,
            balance_after=None,
            description="test",
        )
        assert txn.balance_after is None


class TestSveaPaymentOrder:
    def test_bankgiro_payment(self):
        payment = SveaPaymentOrder(
            recipient_name="Leverantör AB",
            recipient_account="123-4567",
            account_type="bankgiro",
            amount=Decimal("15000.00"),
            reference="OCR123456",
        )
        assert payment.account_type == "bankgiro"
        assert payment.currency == "SEK"
        assert payment.execution_date is None

    def test_domestic_payment(self):
        payment = SveaPaymentOrder(
            recipient_name="Test AB",
            recipient_account="6789-1234567",
            account_type="domestic",
            amount=5000,
            execution_date=date(2026, 4, 1),
        )
        assert payment.amount == Decimal("5000")
        assert payment.execution_date == date(2026, 4, 1)


class TestSveaPaymentBatch:
    def test_batch_creation(self):
        payments = [
            SveaPaymentOrder(
                recipient_name="A", recipient_account="123", account_type="bankgiro", amount=1000
            ),
            SveaPaymentOrder(
                recipient_name="B", recipient_account="456", account_type="plusgiro", amount=2000
            ),
        ]
        batch = SveaPaymentBatch(
            batch_id="batch-001",
            payments=payments,
            total_amount=Decimal("3000"),
        )
        assert len(batch.payments) == 2
        assert batch.status == "pending"
        assert batch.total_amount == Decimal("3000")
