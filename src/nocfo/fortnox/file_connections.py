"""Fortnox File Connections API — link uploaded files to vouchers."""

import structlog

from nocfo.fortnox.client import FortnoxClient

logger = structlog.get_logger()


class FileConnectionService:
    """Connect uploaded files to Fortnox entities (vouchers, invoices, etc.)."""

    def __init__(self, client: FortnoxClient) -> None:
        self._client = client

    async def connect_to_voucher(
        self,
        file_id: str,
        voucher_series: str,
        voucher_number: int,
        voucher_year: int | None = None,
    ) -> None:
        """Connect an uploaded file to a voucher as evidence."""
        payload = {
            "FileConnection": {
                "FileId": file_id,
                "EntityType": "voucher",
                "EntityId": f"{voucher_series}{voucher_number}",
            }
        }
        if voucher_year:
            payload["FileConnection"]["FinancialYearId"] = voucher_year

        await self._client.post("/fileconnections", json_data=payload)
        logger.info(
            "file_connected_to_voucher",
            file_id=file_id,
            voucher=f"{voucher_series}{voucher_number}",
        )
