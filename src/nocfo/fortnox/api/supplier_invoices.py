"""Supplier invoice API operations."""

from typing import Any

import structlog

from nocfo.fortnox.api.client import FortnoxClient
from nocfo.fortnox.api.models import SupplierInvoice

logger = structlog.get_logger()


class SupplierInvoiceService:
    """CRUD operations for supplier invoices."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(self, filter_type: str | None = None) -> list[SupplierInvoice]:
        """List supplier invoices."""
        params: dict[str, Any] = {}
        if filter_type:
            params["filter"] = filter_type

        items = await self._client.get_all_pages(
            "/supplierinvoices", "SupplierInvoices", params=params
        )
        return [self._parse(item) for item in items]

    async def get(self, given_number: int) -> SupplierInvoice:
        """Get a single supplier invoice."""
        data = await self._client.get(f"/supplierinvoices/{given_number}")
        return self._parse(data["SupplierInvoice"])

    async def create(self, invoice: SupplierInvoice) -> SupplierInvoice:
        """Create a new supplier invoice."""
        payload = {
            "SupplierInvoice": {
                "SupplierNumber": invoice.supplier_number,
                "Total": str(invoice.total),
            }
        }
        if invoice.invoice_number:
            payload["SupplierInvoice"]["InvoiceNumber"] = invoice.invoice_number
        if invoice.invoice_date:
            payload["SupplierInvoice"]["InvoiceDate"] = invoice.invoice_date.isoformat()
        if invoice.due_date:
            payload["SupplierInvoice"]["DueDate"] = invoice.due_date.isoformat()

        data = await self._client.post("/supplierinvoices/", json_data=payload)
        result = self._parse(data["SupplierInvoice"])
        logger.info("supplier_invoice_created", given_number=result.given_number)
        return result

    @staticmethod
    def _parse(data: dict[str, Any]) -> SupplierInvoice:
        return SupplierInvoice(
            given_number=data.get("GivenNumber"),
            supplier_number=str(data.get("SupplierNumber", "")),
            invoice_number=data.get("InvoiceNumber", ""),
            invoice_date=data.get("InvoiceDate"),
            due_date=data.get("DueDate"),
            total=data.get("Total", 0),
            balance=data.get("Balance", 0),
            booked=data.get("Booked", False),
            cancelled=data.get("Cancelled", False),
            currency=data.get("Currency", "SEK"),
        )
