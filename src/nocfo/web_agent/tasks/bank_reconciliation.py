"""Bank reconciliation via Fortnox web UI."""

import structlog
from playwright.async_api import Page

from nocfo.bookkeeping.reconciliation import ReconciliationMatch, ReconciliationResult
from nocfo.web_agent.agent import WebAgent
from nocfo.web_agent.prompts import BANK_RECONCILIATION_PROMPT

logger = structlog.get_logger()


async def run_bank_reconciliation(
    page: Page,
    reconciliation_result: ReconciliationResult,
) -> dict:
    """Apply reconciliation matches via the Fortnox web UI.

    The web agent navigates the reconciliation screen and applies
    the pre-computed matches from the reconciliation engine.
    """
    matches_text = _format_matches(reconciliation_result.matches)
    prompt = BANK_RECONCILIATION_PROMPT.format(matches=matches_text)

    agent = WebAgent(page=page, system_prompt=prompt)
    result = await agent.run()

    logger.info(
        "bank_reconciliation_task_complete",
        status=result["status"],
        iterations=result["iterations"],
    )
    return result


def _format_matches(matches: list[ReconciliationMatch]) -> str:
    """Format matches for the agent prompt."""
    lines = []
    for i, m in enumerate(matches, 1):
        bank_txns = ", ".join(
            f"{bt.date} {bt.amount} {bt.description}" for bt in m.bank_transactions
        )
        ledger_entries = ", ".join(
            f"V{le.voucher_series}{le.voucher_number} {le.amount}" for le in m.ledger_entries
        )
        lines.append(f"{i}. [{m.match_type.value}] Bank: {bank_txns} <-> Ledger: {ledger_entries}")
    return "\n".join(lines) if lines else "No matches to apply."
