"""Customer invoice API operations."""

from typing import Any

import structlog

from fortnox.api.client import FortnoxClient
from fortnox.api.models import Invoice

logger = structlog.get_logger()


class InvoiceService:
    """CRUD operations for customer invoices."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def list(self, filter_type: str | None = None) -> list[Invoice]:
        """List invoices. filter_type can be: unpaid, unpaidoverdue, unbooked."""
        params: dict[str, Any] = {}
        if filter_type:
            params["filter"] = filter_type

        items = await self._client.get_all_pages("/invoices", "Invoices", params=params)
        return [self._parse_invoice(item) for item in items]

    async def get(self, document_number: int) -> Invoice:
        """Get a single invoice."""
        data = await self._client.get(f"/invoices/{document_number}")
        return self._parse_invoice(data["Invoice"])

    async def create(self, invoice: Invoice) -> Invoice:
        """Create a new invoice."""
        payload = {
            "Invoice": {
                "CustomerNumber": invoice.customer_number,
                "InvoiceRows": invoice.invoice_rows,
            }
        }
        if invoice.invoice_date:
            payload["Invoice"]["InvoiceDate"] = invoice.invoice_date.isoformat()
        if invoice.due_date:
            payload["Invoice"]["DueDate"] = invoice.due_date.isoformat()
        if invoice.ocr:
            payload["Invoice"]["OCR"] = invoice.ocr

        data = await self._client.post("/invoices/", json_data=payload)
        result = self._parse_invoice(data["Invoice"])
        logger.info("invoice_created", document_number=result.document_number)
        return result

    @staticmethod
    def _parse_invoice(data: dict[str, Any]) -> Invoice:
        return Invoice(
            document_number=data.get("DocumentNumber"),
            customer_number=str(data.get("CustomerNumber", "")),
            invoice_date=data.get("InvoiceDate"),
            due_date=data.get("DueDate"),
            total=data.get("Total", 0),
            balance=data.get("Balance", 0),
            booked=data.get("Booked", False),
            cancelled=data.get("Cancelled", False),
            currency=data.get("Currency", "SEK"),
            ocr=data.get("OCR", ""),
        )
