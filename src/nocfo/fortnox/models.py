"""Pydantic models for Fortnox API entities."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator, model_validator


class VoucherRow(BaseModel):
    """A single row in a voucher (journal entry line)."""

    account: int
    debit: Decimal = Decimal("0")
    credit: Decimal = Decimal("0")
    transaction_information: str = ""

    @field_validator("debit", "credit", mode="before")
    @classmethod
    def coerce_decimal(cls, v: object) -> Decimal:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))


class Voucher(BaseModel):
    """A voucher (verifikation) in Fortnox."""

    description: str
    voucher_series: str = "A"
    transaction_date: date
    rows: list[VoucherRow]

    # Read-only fields from API responses
    voucher_number: int | None = None
    year: int | None = None
    reference_number: str = ""

    @model_validator(mode="after")
    def validate_balance(self) -> "Voucher":
        """Ensure total debits equal total credits."""
        total_debit = sum(r.debit for r in self.rows)
        total_credit = sum(r.credit for r in self.rows)
        if total_debit != total_credit:
            raise ValueError(f"Voucher is unbalanced: debits={total_debit}, credits={total_credit}")
        return self


class Account(BaseModel):
    """A chart of accounts entry."""

    number: int
    description: str
    active: bool = True
    balance_brought_forward: Decimal = Decimal("0")
    sru: int | None = None
    year: int | None = None


class Invoice(BaseModel):
    """A customer invoice."""

    document_number: int | None = None
    customer_number: str
    invoice_date: date | None = None
    due_date: date | None = None
    total: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    booked: bool = False
    cancelled: bool = False
    currency: str = "SEK"
    invoice_rows: list[dict] = []
    ocr: str = ""


class SupplierInvoice(BaseModel):
    """A supplier invoice."""

    given_number: int | None = None
    supplier_number: str
    invoice_number: str = ""
    invoice_date: date | None = None
    due_date: date | None = None
    total: Decimal = Decimal("0")
    balance: Decimal = Decimal("0")
    booked: bool = False
    cancelled: bool = False
    currency: str = "SEK"


class InvoicePayment(BaseModel):
    """A payment against a customer invoice."""

    number: int | None = None
    invoice_number: int
    amount: Decimal
    payment_date: date
    mode_of_payment: str = ""
    source: str = "manual"


class SupplierInvoicePayment(BaseModel):
    """A payment against a supplier invoice."""

    number: int | None = None
    invoice_number: int
    amount: Decimal
    payment_date: date
    mode_of_payment: str = ""


class FinancialYear(BaseModel):
    """A financial year in Fortnox."""

    id: int | None = None
    from_date: date
    to_date: date
    accounting_method: str = "ACCRUAL"


class LockedPeriod(BaseModel):
    """A locked accounting period."""

    end_date: date
