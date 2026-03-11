"""Journal entry creation, validation, and posting."""

from datetime import date
from decimal import Decimal

import structlog

from nocfo.fortnox.client import FortnoxClient
from nocfo.fortnox.models import Voucher, VoucherRow
from nocfo.fortnox.vouchers import VoucherService
from nocfo.storage.idempotency import IdempotencyStore, compute_idempotency_key

logger = structlog.get_logger()


# Common journal entry templates
TEMPLATES: dict[str, list[dict]] = {
    "salary": [
        {"account": 7210, "side": "debit", "label": "Löner tjänstemän"},
        {"account": 1930, "side": "credit", "label": "Företagskonto"},
    ],
    "employer_tax": [
        {"account": 7510, "side": "debit", "label": "Arbetsgivaravgifter"},
        {"account": 1930, "side": "credit", "label": "Företagskonto"},
    ],
    "vat_payment": [
        {"account": 2650, "side": "debit", "label": "Momsredovisningskonto"},
        {"account": 1930, "side": "credit", "label": "Företagskonto"},
    ],
    "customer_payment": [
        {"account": 1930, "side": "debit", "label": "Företagskonto"},
        {"account": 1510, "side": "credit", "label": "Kundfordringar"},
    ],
    "supplier_payment": [
        {"account": 2440, "side": "debit", "label": "Leverantörsskulder"},
        {"account": 1930, "side": "credit", "label": "Företagskonto"},
    ],
}


class JournalService:
    """Creates and posts journal entries with idempotency protection."""

    def __init__(
        self,
        client: FortnoxClient,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._voucher_service = VoucherService(client)
        self._idempotency = idempotency_store

    async def create_entry(
        self,
        transaction_date: date,
        description: str,
        rows: list[VoucherRow],
        voucher_series: str = "A",
        reference_number: str = "",
    ) -> Voucher | None:
        """Create and post a journal entry, skipping if already posted.

        Returns the created Voucher, or None if it was a duplicate.
        """
        # Compute idempotency key and atomically claim it
        account_pairs = [(r.account, r.debit, r.credit) for r in rows]
        key = compute_idempotency_key(transaction_date, account_pairs, description)

        if not await self._idempotency.try_claim(key):
            logger.info("duplicate_voucher_skipped", key=key[:8], description=description)
            return None

        # Build and validate voucher
        voucher = Voucher(
            description=description,
            voucher_series=voucher_series,
            transaction_date=transaction_date,
            rows=rows,
            reference_number=reference_number,
        )

        # Post to Fortnox
        result = await self._voucher_service.create(voucher)

        # Record in idempotency store
        total = sum(r.debit for r in rows)
        await self._idempotency.record(
            key=key,
            voucher_series=result.voucher_series,
            voucher_number=result.voucher_number or 0,
            transaction_date=transaction_date,
            description=description,
            total_amount=total,
        )

        return result

    async def create_from_template(
        self,
        template_name: str,
        transaction_date: date,
        amount: Decimal,
        description: str,
        reference_number: str = "",
    ) -> Voucher | None:
        """Create a journal entry from a predefined template."""
        template = TEMPLATES.get(template_name)
        if not template:
            raise ValueError(f"Unknown template: {template_name}. Available: {list(TEMPLATES)}")

        rows = []
        for entry in template:
            if entry["side"] == "debit":
                rows.append(VoucherRow(account=entry["account"], debit=amount))
            else:
                rows.append(VoucherRow(account=entry["account"], credit=amount))

        return await self.create_entry(
            transaction_date=transaction_date,
            description=description,
            rows=rows,
            reference_number=reference_number,
        )
