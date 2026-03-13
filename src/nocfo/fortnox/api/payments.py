"""Invoice and supplier invoice payment API operations."""

from typing import Any

import structlog

from nocfo.fortnox.api.client import FortnoxClient
from nocfo.fortnox.api.models import InvoicePayment, SupplierInvoicePayment

logger = structlog.get_logger()


class InvoicePaymentService:
    """Operations for customer invoice payments."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(self) -> list[InvoicePayment]:
        """List all invoice payments."""
        items = await self._client.get_all_pages("/invoicepayments", "InvoicePayments")
        return [self._parse(item) for item in items]

    async def get(self, number: int) -> InvoicePayment:
        """Get a single payment."""
        data = await self._client.get(f"/invoicepayments/{number}")
        return self._parse(data["InvoicePayment"])

    async def create(self, payment: InvoicePayment) -> InvoicePayment:
        """Register a payment against an invoice."""
        payload = {
            "InvoicePayment": {
                "InvoiceNumber": payment.invoice_number,
                "Amount": str(payment.amount),
                "PaymentDate": payment.payment_date.isoformat(),
            }
        }
        if payment.mode_of_payment:
            payload["InvoicePayment"]["ModeOfPayment"] = payment.mode_of_payment

        data = await self._client.post("/invoicepayments/", json_data=payload)
        result = self._parse(data["InvoicePayment"])
        logger.info("invoice_payment_created", number=result.number)
        return result

    @staticmethod
    def _parse(data: dict[str, Any]) -> InvoicePayment:
        return InvoicePayment(
            number=data.get("Number"),
            invoice_number=data["InvoiceNumber"],
            amount=data.get("Amount", 0),
            payment_date=data["PaymentDate"],
            mode_of_payment=data.get("ModeOfPayment", ""),
            source=data.get("Source", "manual"),
        )


class SupplierInvoicePaymentService:
    """Operations for supplier invoice payments."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(self) -> list[SupplierInvoicePayment]:
        """List all supplier invoice payments."""
        items = await self._client.get_all_pages(
            "/supplierinvoicepayments", "SupplierInvoicePayments"
        )
        return [self._parse(item) for item in items]

    async def create(self, payment: SupplierInvoicePayment) -> SupplierInvoicePayment:
        """Register a payment against a supplier invoice."""
        payload = {
            "SupplierInvoicePayment": {
                "InvoiceNumber": payment.invoice_number,
                "Amount": str(payment.amount),
                "PaymentDate": payment.payment_date.isoformat(),
            }
        }
        if payment.mode_of_payment:
            payload["SupplierInvoicePayment"]["ModeOfPayment"] = payment.mode_of_payment

        data = await self._client.post("/supplierinvoicepayments/", json_data=payload)
        result = self._parse(data["SupplierInvoicePayment"])
        logger.info("supplier_payment_created", number=result.number)
        return result

    @staticmethod
    def _parse(data: dict[str, Any]) -> SupplierInvoicePayment:
        return SupplierInvoicePayment(
            number=data.get("Number"),
            invoice_number=data["InvoiceNumber"],
            amount=data.get("Amount", 0),
            payment_date=data["PaymentDate"],
            mode_of_payment=data.get("ModeOfPayment", ""),
        )
