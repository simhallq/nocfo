"""Journal entry creation, validation, and posting."""

import asyncio
from datetime import date
from decimal import Decimal
from pathlib import Path

import structlog

from fortnox.api.accounts import AccountService
from fortnox.api.client import FortnoxClient
from fortnox.api.financial_years import FinancialYearService
from fortnox.api.models import Voucher, VoucherRow
from fortnox.api.vouchers import VoucherService
from fortnox.storage.idempotency import IdempotencyStore, compute_idempotency_key

logger = structlog.get_logger()


class VoucherValidationError(Exception):
    """Raised when pre-write validation fails."""


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
        self._client = client
        self._voucher_service = VoucherService(client)
        self._account_service = AccountService(client)
        self._financial_year_service = FinancialYearService(client)
        self._idempotency = idempotency_store
        self._inbox_service = None  # Lazy import to avoid circular deps
        self._file_connection_service = None

    async def validate_voucher_context(
        self,
        transaction_date: date,
        rows: list[VoucherRow],
    ) -> None:
        """Validate that the Fortnox context allows posting this voucher.

        Checks run concurrently:
        1. Financial year exists for the transaction date
        2. Transaction date is not in a locked period
        3. All accounts in voucher rows are active

        Raises VoucherValidationError on failure.
        """
        # Use a list to preserve order for matching gather results
        account_numbers = sorted({r.account for r in rows})

        # Run financial year + locked period checks concurrently
        fy_task = self._financial_year_service.get_by_date(transaction_date)
        locked_task = self._financial_year_service.get_locked_period()

        # Fetch all accounts to check active status
        accounts_task = asyncio.gather(
            *[self._account_service.get(num) for num in account_numbers],
            return_exceptions=True,
        )

        financial_year, locked_period, account_results = await asyncio.gather(
            fy_task, locked_task, accounts_task, return_exceptions=False,
        )

        errors: list[str] = []

        # Check financial year
        if financial_year is None:
            errors.append(
                f"No financial year found for date {transaction_date.isoformat()}"
            )

        # Check locked period
        if locked_period and transaction_date <= locked_period.end_date:
            errors.append(
                f"Transaction date {transaction_date.isoformat()} is in locked "
                f"period (locked through {locked_period.end_date.isoformat()})"
            )

        # Check accounts — account_numbers is a sorted list matching gather order
        for acct_num, result in zip(account_numbers, account_results):
            if isinstance(result, Exception):
                errors.append(f"Account {acct_num} not found in chart of accounts")
            elif not result.active:
                errors.append(f"Account {acct_num} ({result.description}) is inactive")

        if errors:
            raise VoucherValidationError(
                "Voucher validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            )

        logger.debug(
            "voucher_context_validated",
            transaction_date=transaction_date.isoformat(),
            accounts=sorted(account_numbers),
        )

    async def create_entry(
        self,
        transaction_date: date,
        description: str,
        rows: list[VoucherRow],
        voucher_series: str = "A",
        reference_number: str = "",
        evidence_file: Path | None = None,
    ) -> Voucher | None:
        """Create and post a journal entry, skipping if already posted.

        Args:
            transaction_date: Date of the journal entry.
            description: Voucher description.
            rows: Voucher debit/credit rows.
            voucher_series: Fortnox voucher series (default "A").
            reference_number: Optional external reference.
            evidence_file: Optional path to source document to attach.

        Returns the created Voucher, or None if it was a duplicate.
        """
        # Compute idempotency key and atomically claim it
        account_pairs = [(r.account, r.debit, r.credit) for r in rows]
        key = compute_idempotency_key(transaction_date, account_pairs, description)

        if not await self._idempotency.try_claim(key):
            logger.info("duplicate_voucher_skipped", key=key[:8], description=description)
            return None

        # Validate context before posting
        await self.validate_voucher_context(transaction_date, rows)

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

        # Attach evidence if provided
        if evidence_file:
            await self._attach_evidence(result, evidence_file)

        return result

    async def _attach_evidence(self, voucher: Voucher, file_path: Path) -> None:
        """Upload evidence file and connect it to the voucher.

        Logs a warning on failure but does not raise — the voucher is already posted.
        """
        try:
            from fortnox.api.file_connections import FileConnectionService
            from fortnox.api.inbox import InboxService

            if self._inbox_service is None:
                self._inbox_service = InboxService(self._client)
            if self._file_connection_service is None:
                self._file_connection_service = FileConnectionService(self._client)

            file_id = await self._inbox_service.upload(file_path)
            await self._file_connection_service.connect_to_voucher(
                file_id=file_id,
                voucher_series=voucher.voucher_series,
                voucher_number=voucher.voucher_number or 0,
                voucher_year=voucher.year,
            )
            logger.info(
                "evidence_attached",
                voucher_number=voucher.voucher_number,
                file=file_path.name,
            )
        except Exception:
            logger.warning(
                "evidence_attachment_failed",
                voucher_number=voucher.voucher_number,
                file=str(file_path),
                exc_info=True,
            )

    async def create_from_template(
        self,
        template_name: str,
        transaction_date: date,
        amount: Decimal,
        description: str,
        reference_number: str = "",
        evidence_file: Path | None = None,
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
            evidence_file=evidence_file,
        )
