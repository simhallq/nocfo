"""Pydantic models for Svea Bank API entities."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator


class SveaAccount(BaseModel):
    """A bank account at Svea Bank."""

    account_id: str
    account_number: str
    name: str
    balance: Decimal = Decimal("0")
    available_balance: Decimal = Decimal("0")
    currency: str = "SEK"
    account_type: str = ""

    @field_validator("balance", "available_balance", mode="before")
    @classmethod
    def coerce_decimal(cls, v: object) -> Decimal:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))


class SveaTransaction(BaseModel):
    """A bank transaction from Svea Bank."""

    transaction_id: str
    booking_date: date
    value_date: date | None = None
    amount: Decimal
    balance_after: Decimal | None = None
    description: str
    reference: str = ""
    counterparty: str = ""
    transaction_type: str = ""

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v: object) -> Decimal:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))

    @field_validator("balance_after", mode="before")
    @classmethod
    def coerce_balance(cls, v: object) -> Decimal | None:
        if v is None:
            return None
        return Decimal(str(v))


class SveaPaymentOrder(BaseModel):
    """A payment order to be sent via Svea Bank."""

    recipient_name: str
    recipient_account: str
    account_type: str  # 'bankgiro', 'plusgiro', 'domestic', 'sepa'
    amount: Decimal
    currency: str = "SEK"
    reference: str = ""
    message: str = ""
    execution_date: date | None = None

    @field_validator("amount", mode="before")
    @classmethod
    def coerce_amount(cls, v: object) -> Decimal:
        return Decimal(str(v))


class SveaPaymentBatch(BaseModel):
    """A batch of payment orders grouped for a single BankID signing."""

    batch_id: str
    payments: list[SveaPaymentOrder]
    status: str = "pending"  # pending, signing, signed, executed, failed
    total_amount: Decimal = Decimal("0")
    currency: str = "SEK"

    @field_validator("total_amount", mode="before")
    @classmethod
    def coerce_total(cls, v: object) -> Decimal:
        if v is None:
            return Decimal("0")
        return Decimal(str(v))
