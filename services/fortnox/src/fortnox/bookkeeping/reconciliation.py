"""Bank-to-ledger reconciliation matching algorithm."""

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import Enum

import structlog

logger = structlog.get_logger()


class MatchType(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    ONE_TO_MANY = "one_to_many"
    UNMATCHED = "unmatched"


@dataclass
class BankTransaction:
    """A transaction from the bank statement."""

    id: str
    date: date
    amount: Decimal
    description: str
    reference: str = ""


@dataclass
class LedgerEntry:
    """A ledger entry (voucher row) from Fortnox."""

    voucher_series: str
    voucher_number: int
    date: date
    amount: Decimal
    description: str
    account: int
    matched: bool = False


@dataclass
class ReconciliationMatch:
    """A match between bank transaction(s) and ledger entry(ies)."""

    bank_transactions: list[BankTransaction]
    ledger_entries: list[LedgerEntry]
    match_type: MatchType
    confidence: float
    difference: Decimal = Decimal("0")


@dataclass
class ReconciliationResult:
    """Complete reconciliation result."""

    matches: list[ReconciliationMatch] = field(default_factory=list)
    unmatched_bank: list[BankTransaction] = field(default_factory=list)
    unmatched_ledger: list[LedgerEntry] = field(default_factory=list)

    @property
    def is_fully_reconciled(self) -> bool:
        return len(self.unmatched_bank) == 0 and len(self.unmatched_ledger) == 0

    @property
    def match_rate(self) -> float:
        total = len(self.matches) + len(self.unmatched_bank)
        return len(self.matches) / total if total > 0 else 1.0


class ReconciliationEngine:
    """Matches bank transactions against ledger entries."""

    def __init__(self, date_tolerance_days: int = 3) -> None:
        self._date_tolerance = timedelta(days=date_tolerance_days)

    def reconcile(
        self,
        bank_transactions: list[BankTransaction],
        ledger_entries: list[LedgerEntry],
    ) -> ReconciliationResult:
        """Run the reconciliation algorithm.

        Strategy:
        1. Exact match: same amount + same date
        2. Fuzzy match: same amount + date within tolerance
        3. One-to-many: one bank txn matches sum of multiple ledger entries
        4. Remaining: flagged as unmatched
        """
        result = ReconciliationResult()

        # Work with copies to track matching state
        remaining_bank = list(bank_transactions)
        remaining_ledger = list(ledger_entries)

        # Pass 1: Exact matches
        remaining_bank, remaining_ledger = self._exact_match(
            remaining_bank, remaining_ledger, result
        )

        # Pass 2: Fuzzy matches (date tolerance)
        remaining_bank, remaining_ledger = self._fuzzy_match(
            remaining_bank, remaining_ledger, result
        )

        # Pass 3: One-to-many matches
        remaining_bank, remaining_ledger = self._one_to_many_match(
            remaining_bank, remaining_ledger, result
        )

        # Remaining are unmatched
        result.unmatched_bank = remaining_bank
        result.unmatched_ledger = remaining_ledger

        logger.info(
            "reconciliation_complete",
            matches=len(result.matches),
            unmatched_bank=len(result.unmatched_bank),
            unmatched_ledger=len(result.unmatched_ledger),
            match_rate=round(result.match_rate, 2),
        )
        return result

    def _exact_match(
        self,
        bank: list[BankTransaction],
        ledger: list[LedgerEntry],
        result: ReconciliationResult,
    ) -> tuple[list[BankTransaction], list[LedgerEntry]]:
        """Match transactions with identical amount and date."""
        unmatched_bank = []

        for bt in bank:
            match_found = False
            for le in ledger:
                if le.matched:
                    continue
                if bt.amount == le.amount and bt.date == le.date:
                    result.matches.append(
                        ReconciliationMatch(
                            bank_transactions=[bt],
                            ledger_entries=[le],
                            match_type=MatchType.EXACT,
                            confidence=1.0,
                        )
                    )
                    le.matched = True
                    match_found = True
                    break

            if not match_found:
                unmatched_bank.append(bt)

        remaining_ledger = [le for le in ledger if not le.matched]
        return unmatched_bank, remaining_ledger

    def _fuzzy_match(
        self,
        bank: list[BankTransaction],
        ledger: list[LedgerEntry],
        result: ReconciliationResult,
    ) -> tuple[list[BankTransaction], list[LedgerEntry]]:
        """Match transactions with same amount but date within tolerance."""
        unmatched_bank = []

        for bt in bank:
            match_found = False
            for le in ledger:
                if le.matched:
                    continue
                if bt.amount == le.amount and abs(bt.date - le.date) <= self._date_tolerance:
                    days_diff = abs((bt.date - le.date).days)
                    confidence = max(0.7, 1.0 - (days_diff * 0.1))
                    result.matches.append(
                        ReconciliationMatch(
                            bank_transactions=[bt],
                            ledger_entries=[le],
                            match_type=MatchType.FUZZY,
                            confidence=confidence,
                        )
                    )
                    le.matched = True
                    match_found = True
                    break

            if not match_found:
                unmatched_bank.append(bt)

        remaining_ledger = [le for le in ledger if not le.matched]
        return unmatched_bank, remaining_ledger

    def _one_to_many_match(
        self,
        bank: list[BankTransaction],
        ledger: list[LedgerEntry],
        result: ReconciliationResult,
    ) -> tuple[list[BankTransaction], list[LedgerEntry]]:
        """Match one bank transaction to multiple ledger entries that sum to the same amount."""
        unmatched_bank = []

        for bt in bank:
            # Find ledger entries within date range
            candidates = [
                le
                for le in ledger
                if not le.matched and abs(bt.date - le.date) <= self._date_tolerance
            ]

            match = self._find_subset_sum(bt.amount, candidates)
            if match:
                for le in match:
                    le.matched = True
                result.matches.append(
                    ReconciliationMatch(
                        bank_transactions=[bt],
                        ledger_entries=match,
                        match_type=MatchType.ONE_TO_MANY,
                        confidence=0.8,
                    )
                )
            else:
                unmatched_bank.append(bt)

        remaining_ledger = [le for le in ledger if not le.matched]
        return unmatched_bank, remaining_ledger

    @staticmethod
    def _find_subset_sum(
        target: Decimal,
        candidates: list[LedgerEntry],
        max_entries: int = 5,
    ) -> list[LedgerEntry] | None:
        """Find a subset of ledger entries that sum to the target amount.

        Uses a simple iterative approach limited to small subsets.
        """
        if len(candidates) < 2:
            return None

        # Try pairs first (most common case)
        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                if a.amount + b.amount == target:
                    return [a, b]

        # Try triples
        if len(candidates) >= 3 and max_entries >= 3:
            for i, a in enumerate(candidates):
                for j, b in enumerate(candidates[i + 1 :], i + 1):
                    for c in candidates[j + 1 :]:
                        if a.amount + b.amount + c.amount == target:
                            return [a, b, c]

        return None
