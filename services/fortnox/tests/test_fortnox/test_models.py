"""Tests for Fortnox Pydantic models."""

from datetime import date
from decimal import Decimal

import pytest

from fortnox.api.models import Account, Invoice, Voucher, VoucherRow


class TestVoucherRow:
    def test_default_values(self):
        row = VoucherRow(account=1930)
        assert row.debit == Decimal("0")
        assert row.credit == Decimal("0")

    def test_decimal_coercion(self):
        row = VoucherRow(account=1930, debit=100.50)
        assert row.debit == Decimal("100.5")

    def test_none_coercion(self):
        row = VoucherRow(account=1930, debit=None, credit=None)
        assert row.debit == Decimal("0")
        assert row.credit == Decimal("0")


class TestVoucher:
    def test_balanced_voucher(self):
        voucher = Voucher(
            description="Test",
            transaction_date=date(2024, 12, 1),
            rows=[
                VoucherRow(account=7210, debit=Decimal("1000")),
                VoucherRow(account=1930, credit=Decimal("1000")),
            ],
        )
        assert voucher.description == "Test"
        assert len(voucher.rows) == 2

    def test_unbalanced_voucher_raises(self):
        with pytest.raises(ValueError, match="unbalanced"):
            Voucher(
                description="Unbalanced",
                transaction_date=date(2024, 12, 1),
                rows=[
                    VoucherRow(account=7210, debit=Decimal("1000")),
                    VoucherRow(account=1930, credit=Decimal("999")),
                ],
            )

    def test_default_series(self):
        voucher = Voucher(
            description="Test",
            transaction_date=date(2024, 12, 1),
            rows=[
                VoucherRow(account=7210, debit=Decimal("100")),
                VoucherRow(account=1930, credit=Decimal("100")),
            ],
        )
        assert voucher.voucher_series == "A"

    def test_zero_amount_voucher(self):
        voucher = Voucher(
            description="Zero",
            transaction_date=date(2024, 12, 1),
            rows=[
                VoucherRow(account=7210, debit=Decimal("0")),
                VoucherRow(account=1930, credit=Decimal("0")),
            ],
        )
        assert voucher is not None


class TestAccount:
    def test_account_creation(self):
        account = Account(number=1930, description="Företagskonto")
        assert account.number == 1930
        assert account.active is True

    def test_account_with_balance(self):
        account = Account(
            number=1930,
            description="Företagskonto",
            balance_brought_forward=Decimal("50000"),
        )
        assert account.balance_brought_forward == Decimal("50000")


class TestInvoice:
    def test_invoice_defaults(self):
        invoice = Invoice(customer_number="100")
        assert invoice.total == Decimal("0")
        assert invoice.booked is False
        assert invoice.currency == "SEK"
