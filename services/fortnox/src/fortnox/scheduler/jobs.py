"""Scheduled job definitions."""

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logger = structlog.get_logger()


async def token_refresh_job() -> None:
    """Proactively refresh OAuth tokens."""
    from fortnox.fortnox.api.auth import TokenManager

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
    """Fetch Svea Bank transactions and auto-journal high-confidence matches."""
    logger.info("job_started", job="daily_voucher_sync")
    try:
        from fortnox.fortnox.api.auth import TokenManager
        from fortnox.fortnox.api.client import FortnoxClient
        from fortnox.storage.database import Database
        from fortnox.svea.api.auth import SveaTokenManager
        from fortnox.svea.api.client import SveaClient
        from fortnox.svea.api.transactions import SveaTransactionService
        from fortnox.svea.reconcile import SveaReconciliationService
        from fortnox.svea.sync import TransactionSyncService

        svea_manager = SveaTokenManager()
        await svea_manager.initialize()
        if not svea_manager.is_authenticated:
            logger.warning("job_skipped", job="daily_voucher_sync", reason="svea_not_authenticated")
            return

        fortnox_manager = TokenManager()
        await fortnox_manager.initialize()

        db = Database()
        conn = await db.connect()

        try:
            async with SveaClient(token_manager=svea_manager) as svea_client:
                # Sync transactions (incremental from last cursor)
                txn_service = SveaTransactionService(svea_client)
                accounts = await txn_service.list_accounts()
                if not accounts:
                    logger.warning("job_skipped", job="daily_voucher_sync", reason="no_accounts")
                    return

                sync_service = TransactionSyncService(conn, svea_client)
                sync_result = await sync_service.sync_transactions(accounts[0].account_id)
                logger.info("voucher_sync_fetched", new=sync_result.new)

                if sync_result.new == 0:
                    logger.info("job_completed", job="daily_voucher_sync", note="no_new_transactions")
                    return

                # Run reconciliation with auto-journal for confident matches
                from datetime import date, timedelta

                async with FortnoxClient(token_manager=fortnox_manager) as fortnox_client:
                    recon_service = SveaReconciliationService(
                        db=conn,
                        sync_service=sync_service,
                        fortnox_client=fortnox_client,
                    )
                    today = date.today()
                    report = await recon_service.run(
                        from_date=today - timedelta(days=7),
                        to_date=today,
                        dry_run=False,
                    )
                    logger.info(
                        "job_completed",
                        job="daily_voucher_sync",
                        auto_journaled=report.auto_journaled,
                        pending_review=report.pending_review,
                    )
        finally:
            await db.close()

    except Exception as e:
        logger.error("job_failed", job="daily_voucher_sync", error=str(e))


async def daily_invoice_check_job() -> None:
    """Check for overdue customer invoices."""
    logger.info("job_started", job="daily_invoice_check")
    try:
        from fortnox.fortnox.api.auth import TokenManager
        from fortnox.fortnox.api.client import FortnoxClient
        from fortnox.fortnox.api.invoices import InvoiceService

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
    """Run full Svea Bank reconciliation against Fortnox GL."""
    logger.info("job_started", job="weekly_reconciliation")
    try:
        from datetime import date, timedelta

        from fortnox.fortnox.api.auth import TokenManager
        from fortnox.fortnox.api.client import FortnoxClient
        from fortnox.storage.database import Database
        from fortnox.svea.api.auth import SveaTokenManager
        from fortnox.svea.api.client import SveaClient
        from fortnox.svea.reconcile import SveaReconciliationService
        from fortnox.svea.sync import TransactionSyncService

        svea_manager = SveaTokenManager()
        await svea_manager.initialize()
        if not svea_manager.is_authenticated:
            logger.warning("job_skipped", job="weekly_reconciliation", reason="svea_not_authenticated")
            return

        fortnox_manager = TokenManager()
        await fortnox_manager.initialize()

        db = Database()
        conn = await db.connect()

        try:
            async with SveaClient(token_manager=svea_manager) as svea_client:
                async with FortnoxClient(token_manager=fortnox_manager) as fortnox_client:
                    sync_service = TransactionSyncService(conn, svea_client)
                    recon_service = SveaReconciliationService(
                        db=conn,
                        sync_service=sync_service,
                        fortnox_client=fortnox_client,
                    )
                    today = date.today()
                    report = await recon_service.run(
                        from_date=today - timedelta(days=30),
                        to_date=today,
                        dry_run=False,
                    )
                    logger.info(
                        "job_completed",
                        job="weekly_reconciliation",
                        matches=len(report.reconciliation.matches),
                        match_rate=round(report.reconciliation.match_rate, 2),
                        auto_journaled=report.auto_journaled,
                        pending_review=report.pending_review,
                    )
        finally:
            await db.close()

    except Exception as e:
        logger.error("job_failed", job="weekly_reconciliation", error=str(e))


async def svea_token_refresh_job() -> None:
    """Proactively refresh Svea Bank OAuth tokens."""
    from fortnox.svea.api.auth import SveaTokenManager

    logger.info("job_started", job="svea_token_refresh")
    try:
        manager = SveaTokenManager()
        await manager.initialize()
        if manager.is_authenticated:
            await manager.get_access_token()
            logger.info("job_completed", job="svea_token_refresh")
    except Exception as e:
        logger.error("job_failed", job="svea_token_refresh", error=str(e))


async def monthly_closing_check_job() -> None:
    """Check if the previous month can be closed."""
    logger.info("job_started", job="monthly_closing_check")
    try:
        from datetime import date, timedelta

        from fortnox.bookkeeping.closing import ClosingService
        from fortnox.fortnox.api.auth import TokenManager
        from fortnox.fortnox.api.client import FortnoxClient

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

    # Svea Bank token refresh every 45 minutes
    scheduler.add_job(
        svea_token_refresh_job,
        "interval",
        minutes=45,
        id="svea_token_refresh",
        name="Svea Bank Token Refresh",
    )

    logger.info("all_jobs_registered")
