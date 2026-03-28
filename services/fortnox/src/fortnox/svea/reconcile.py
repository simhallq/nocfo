"""Svea Bank reconciliation pipeline.

Connects Svea Bank transactions to the existing ReconciliationEngine
and auto-journals matched transactions via the RuleEngine + JournalService.

Pipeline:
1. Fetch bank transactions from local DB (or sync first)
2. Fetch ledger entries from Fortnox account 1930
3. Run ReconciliationEngine.reconcile()
4. For unmatched bank transactions: categorize via RuleEngine
5. For categorized (confidence 1.0): create journal entries
6. For uncategorized: mark as pending_review
"""

import asyncio
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import aiosqlite
import structlog

from fortnox.bookkeeping.reconciliation import (
    BankTransaction,
    LedgerEntry,
    ReconciliationEngine,
    ReconciliationResult,
)
from fortnox.bookkeeping.rules import CategorizedTransaction, RuleEngine
from fortnox.fortnox.api.client import FortnoxClient
from fortnox.fortnox.api.models import VoucherRow
from fortnox.svea.sync import TransactionSyncService

logger = structlog.get_logger()

BANK_ACCOUNT = 1930


@dataclass
class ReconciliationReport:
    """Summary of a reconciliation run."""

    reconciliation: ReconciliationResult
    auto_journaled: int = 0
    pending_review: int = 0
    vouchers_created: list[dict] = field(default_factory=list)
    review_items: list[dict] = field(default_factory=list)

    @property
    def summary(self) -> str:
        r = self.reconciliation
        lines = [
            f"Reconciliation: {len(r.matches)} matched, "
            f"{len(r.unmatched_bank)} unmatched bank, "
            f"{len(r.unmatched_ledger)} unmatched ledger",
            f"Match rate: {r.match_rate:.0%}",
            f"Auto-journaled: {self.auto_journaled}",
            f"Pending review: {self.pending_review}",
        ]
        return "\n".join(lines)


class SveaReconciliationService:
    """Runs the full reconciliation pipeline for Svea Bank."""

    def __init__(
        self,
        db: aiosqlite.Connection,
        sync_service: TransactionSyncService,
        fortnox_client: FortnoxClient,
        rule_engine: RuleEngine | None = None,
    ) -> None:
        self._db = db
        self._sync = sync_service
        self._fortnox = fortnox_client
        self._rule_engine = rule_engine or RuleEngine()
        self._reconciliation_engine = ReconciliationEngine()

    async def run(
        self,
        from_date: date,
        to_date: date,
        account_number: str | None = None,
        dry_run: bool = True,
    ) -> ReconciliationReport:
        """Run the full reconciliation pipeline."""
        bank_txns, ledger_entries = await asyncio.gather(
            self._sync.get_bank_transactions(from_date, to_date, account_number),
            self._fetch_ledger_entries(from_date, to_date),
        )
        logger.info("reconcile_data_loaded", bank=len(bank_txns), ledger=len(ledger_entries))

        result = self._reconciliation_engine.reconcile(bank_txns, ledger_entries)
        report = ReconciliationReport(reconciliation=result)

        if result.unmatched_bank:
            self._rule_engine.load()

            from fortnox.bookkeeping.journal import JournalService
            from fortnox.storage.idempotency import IdempotencyStore

            idempotency = IdempotencyStore(self._db)
            journal = JournalService(self._fortnox, idempotency)

            for bt in result.unmatched_bank:
                categorized = self._rule_engine.categorize(bt.description, bt.amount)

                if isinstance(categorized, CategorizedTransaction):
                    if not dry_run:
                        voucher_info = await self._auto_journal(bt, categorized, journal)
                        if voucher_info:
                            report.vouchers_created.append(voucher_info)
                    report.auto_journaled += 1
                else:
                    report.review_items.append({
                        "transaction_id": bt.id,
                        "date": bt.date.isoformat(),
                        "amount": str(bt.amount),
                        "description": bt.description,
                    })
                    report.pending_review += 1

        if not dry_run:
            matched_ids = [
                bt.id for m in result.matches for bt in m.bank_transactions
            ]
            if matched_ids:
                await self._sync.mark_reconciled(matched_ids)

        logger.info(
            "reconcile_complete",
            matches=len(result.matches),
            auto_journaled=report.auto_journaled,
            pending_review=report.pending_review,
            dry_run=dry_run,
        )
        return report

    async def _fetch_ledger_entries(
        self,
        from_date: date,
        to_date: date,
    ) -> list[LedgerEntry]:
        """Fetch voucher rows for account 1930 from Fortnox."""
        from fortnox.fortnox.api.vouchers import VoucherService

        voucher_service = VoucherService(self._fortnox)
        vouchers = await voucher_service.list(voucher_series="A")

        entries = []
        for v in vouchers:
            if v.transaction_date and from_date <= v.transaction_date <= to_date:
                for row in v.rows:
                    if row.account == BANK_ACCOUNT:
                        amount = row.debit - row.credit
                        entries.append(
                            LedgerEntry(
                                voucher_series=v.voucher_series,
                                voucher_number=v.voucher_number or 0,
                                date=v.transaction_date,
                                amount=amount,
                                description=v.description,
                                account=row.account,
                            )
                        )
        return entries

    async def _auto_journal(
        self,
        bank_txn: BankTransaction,
        categorized: CategorizedTransaction,
        journal: object,
    ) -> dict | None:
        """Create a journal entry for a categorized bank transaction."""
        rows = [
            VoucherRow(
                account=categorized.debit_account,
                debit=abs(bank_txn.amount) if bank_txn.amount >= 0 else Decimal("0"),
                credit=abs(bank_txn.amount) if bank_txn.amount < 0 else Decimal("0"),
                transaction_information=bank_txn.description[:100],
            ),
            VoucherRow(
                account=categorized.credit_account,
                debit=abs(bank_txn.amount) if bank_txn.amount < 0 else Decimal("0"),
                credit=abs(bank_txn.amount) if bank_txn.amount >= 0 else Decimal("0"),
                transaction_information=bank_txn.description[:100],
            ),
        ]

        result = await journal.create_entry(
            transaction_date=bank_txn.date,
            description=f"Auto: {bank_txn.description[:80]}",
            rows=rows,
        )

        if result:
            return {
                "voucher_series": result.voucher_series,
                "voucher_number": result.voucher_number,
                "date": bank_txn.date.isoformat(),
                "amount": str(bank_txn.amount),
                "rule": categorized.rule_name,
            }
        return None
