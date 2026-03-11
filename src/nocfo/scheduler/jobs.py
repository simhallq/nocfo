"""Scheduled job definitions."""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger()


async def token_refresh_job() -> None:
    """Proactively refresh OAuth tokens."""
    from nocfo.fortnox.auth import TokenManager

    logger.info("job_started", job="token_refresh")
    try:
        manager = TokenManager()
        await manager.initialize()
        if manager.is_authenticated:
            # Force refresh by getting token (auto-refreshes if near expiry)
            await manager.get_access_token()
            logger.info("job_completed", job="token_refresh")
    except Exception as e:
        logger.error("job_failed", job="token_refresh", error=str(e))


async def daily_voucher_sync_job() -> None:
    """Fetch bank transactions, categorize, and create vouchers."""
    logger.info("job_started", job="daily_voucher_sync")
    # TODO: Implement bank transaction fetching and auto-journaling
    logger.info("job_completed", job="daily_voucher_sync", note="not_yet_implemented")


async def daily_invoice_check_job() -> None:
    """Check for overdue customer invoices."""
    logger.info("job_started", job="daily_invoice_check")
    try:
        from nocfo.fortnox.auth import TokenManager
        from nocfo.fortnox.client import FortnoxClient
        from nocfo.fortnox.invoices import InvoiceService

        token_manager = TokenManager()
        await token_manager.initialize()

        async with FortnoxClient(token_manager=token_manager) as client:
            invoice_service = InvoiceService(client)
            overdue = await invoice_service.list(filter_type="unpaidoverdue")
            if overdue:
                logger.warning(
                    "overdue_invoices_found",
                    count=len(overdue),
                    total_amount=sum(float(inv.balance) for inv in overdue),
                )
            else:
                logger.info("no_overdue_invoices")

        logger.info("job_completed", job="daily_invoice_check")
    except Exception as e:
        logger.error("job_failed", job="daily_invoice_check", error=str(e))


async def weekly_reconciliation_job() -> None:
    """Run bank reconciliation via web agent."""
    logger.info("job_started", job="weekly_reconciliation")
    # TODO: Implement full reconciliation pipeline
    logger.info("job_completed", job="weekly_reconciliation", note="not_yet_implemented")


async def monthly_closing_check_job() -> None:
    """Check if the previous month can be closed."""
    logger.info("job_started", job="monthly_closing_check")
    try:
        from datetime import date, timedelta

        from nocfo.bookkeeping.closing import ClosingService
        from nocfo.fortnox.auth import TokenManager
        from nocfo.fortnox.client import FortnoxClient

        # Previous month's last day
        today = date.today()
        first_of_month = today.replace(day=1)
        period_end = first_of_month - timedelta(days=1)

        token_manager = TokenManager()
        await token_manager.initialize()

        async with FortnoxClient(token_manager=token_manager) as client:
            closing = ClosingService(client)
            check = await closing.check_period(period_end)

            if check.is_ready:
                logger.info(
                    "period_ready_for_closing",
                    period_end=period_end.isoformat(),
                )
            else:
                logger.warning(
                    "period_not_ready",
                    period_end=period_end.isoformat(),
                    issues=check.issues,
                )

        logger.info("job_completed", job="monthly_closing_check")
    except Exception as e:
        logger.error("job_failed", job="monthly_closing_check", error=str(e))


async def monthly_period_close_job() -> None:
    """Execute period closing (requires prior approval)."""
    logger.info("job_started", job="monthly_period_close")
    # TODO: Check for approval before executing
    logger.info(
        "job_completed",
        job="monthly_period_close",
        note="requires_approval_not_yet_implemented",
    )


def register_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register all scheduled jobs."""
    # Token refresh every 45 minutes
    scheduler.add_job(
        token_refresh_job,
        "interval",
        minutes=45,
        id="token_refresh",
        name="OAuth Token Refresh",
    )

    # Daily voucher sync at 07:00
    scheduler.add_job(
        daily_voucher_sync_job,
        "cron",
        hour=7,
        minute=0,
        id="daily_voucher_sync",
        name="Daily Voucher Sync",
    )

    # Daily invoice check at 08:00
    scheduler.add_job(
        daily_invoice_check_job,
        "cron",
        hour=8,
        minute=0,
        id="daily_invoice_check",
        name="Daily Invoice Check",
    )

    # Weekly reconciliation on Mondays at 06:00
    scheduler.add_job(
        weekly_reconciliation_job,
        "cron",
        day_of_week="mon",
        hour=6,
        minute=0,
        id="weekly_reconciliation",
        name="Weekly Bank Reconciliation",
    )

    # Monthly closing check on the 1st at 09:00
    scheduler.add_job(
        monthly_closing_check_job,
        "cron",
        day=1,
        hour=9,
        minute=0,
        id="monthly_closing_check",
        name="Monthly Closing Check",
    )

    # Monthly period close on the 5th at 09:00
    scheduler.add_job(
        monthly_period_close_job,
        "cron",
        day=5,
        hour=9,
        minute=0,
        id="monthly_period_close",
        name="Monthly Period Close",
    )

    logger.info("all_jobs_registered")
