"""NoCFO CLI entry point."""

import asyncio
import sys

import click
import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(structlog, level.upper(), structlog.INFO)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def run_async(coro):
    """Run an async function from synchronous CLI context."""
    return asyncio.run(coro)


def parse_month(month: str):
    """Parse YYYY-MM string to the last date of that month."""
    import calendar
    from datetime import date as date_cls

    try:
        year, mon = map(int, month.split("-"))
        last_day = calendar.monthrange(year, mon)[1]
        return date_cls(year, mon, last_day)
    except (ValueError, IndexError):
        raise click.BadParameter(f"Invalid month format: {month!r}. Use YYYY-MM.")


@click.group()
@click.option(
    "--log-level", default="INFO", type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"])
)
def cli(log_level: str) -> None:
    """NoCFO - Fortnox bookkeeping automation."""
    setup_logging(log_level)


# --- Auth commands ---


@cli.group()
def auth() -> None:
    """Authentication management."""
    pass


@auth.command()
def setup() -> None:
    """Run interactive OAuth setup."""
    from nocfo.config import get_settings
    from nocfo.fortnox.auth import TokenManager, exchange_code_for_token, start_authorization

    settings = get_settings()
    if not settings.validate_fortnox_credentials():
        click.echo("Error: FORTNOX_CLIENT_ID and FORTNOX_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    click.echo("Starting OAuth authorization flow...")
    click.echo("A browser window will open. Please authorize the application.")

    code = start_authorization()
    click.echo("Authorization code received. Exchanging for tokens...")

    async def _exchange():
        token_data = await exchange_code_for_token(code)
        manager = TokenManager()
        await manager.store_tokens(token_data)
        return token_data

    run_async(_exchange())
    click.echo("Authentication successful! Tokens stored securely.")


@auth.command()
@click.option("--health", is_flag=True, help="Run full health check against Fortnox API")
def status(health: bool) -> None:
    """Check authentication status."""
    from nocfo.fortnox.auth import TokenManager

    async def _check():
        manager = TokenManager()
        await manager.initialize()
        return manager.is_authenticated, manager

    is_auth, manager = run_async(_check())
    if is_auth:
        click.echo("Authenticated: Yes")
    else:
        click.echo("Authenticated: No - run 'nocfo auth setup'")
        return

    if health:
        from nocfo.fortnox.client import FortnoxClient
        from nocfo.fortnox.health import HealthCheck

        async def _health():
            async with FortnoxClient(token_manager=manager) as client:
                checker = HealthCheck(client)
                return await checker.run_all()

        click.echo("\nRunning health checks...")
        report = run_async(_health())
        click.echo(report.summary())
        if not report.healthy:
            click.echo(f"\n{len(report.critical_failures)} check(s) failed.")
            sys.exit(1)
        click.echo("\nAll checks passed.")


# --- Voucher commands ---


@cli.group()
def voucher() -> None:
    """Voucher operations."""
    pass


@voucher.command("list")
@click.option("--series", default="A", help="Voucher series")
def voucher_list(series: str) -> None:
    """List vouchers."""
    from nocfo.fortnox.auth import TokenManager
    from nocfo.fortnox.client import FortnoxClient
    from nocfo.fortnox.vouchers import VoucherService

    async def _list():
        manager = TokenManager()
        await manager.initialize()
        async with FortnoxClient(token_manager=manager) as client:
            service = VoucherService(client)
            vouchers = await service.list(voucher_series=series)
            return vouchers

    vouchers = run_async(_list())
    for v in vouchers:
        click.echo(
            f"  {v.voucher_series}{v.voucher_number:>5}  {v.transaction_date}  {v.description}"
        )
    click.echo(f"\nTotal: {len(vouchers)} vouchers")


@voucher.command("create")
@click.option("--template", required=True, help="Template name (salary, vat_payment, etc.)")
@click.option("--amount", required=True, type=float, help="Amount")
@click.option("--date", "txn_date", required=True, help="Transaction date (YYYY-MM-DD)")
@click.option("--description", required=True, help="Description")
def voucher_create(template: str, amount: float, txn_date: str, description: str) -> None:
    """Create a voucher from a template."""
    from datetime import date as date_cls
    from decimal import Decimal

    from nocfo.bookkeeping.journal import JournalService
    from nocfo.fortnox.auth import TokenManager
    from nocfo.fortnox.client import FortnoxClient
    from nocfo.storage.database import Database
    from nocfo.storage.idempotency import IdempotencyStore

    async def _create():
        manager = TokenManager()
        await manager.initialize()
        db = Database()
        conn = await db.connect()

        try:
            async with FortnoxClient(token_manager=manager) as client:
                idempotency = IdempotencyStore(conn)
                journal = JournalService(client, idempotency)
                result = await journal.create_from_template(
                    template_name=template,
                    transaction_date=date_cls.fromisoformat(txn_date),
                    amount=Decimal(str(amount)),
                    description=description,
                )
                return result
        finally:
            await db.close()

    result = run_async(_create())
    if result:
        click.echo(
            f"Voucher created: {result.voucher_series}{result.voucher_number} "
            f"on {result.transaction_date}"
        )
    else:
        click.echo("Voucher already exists (duplicate detected)")


# --- Reconciliation commands ---


@cli.group()
def reconcile() -> None:
    """Bank reconciliation."""
    pass


@reconcile.command("run")
@click.option("--headed", is_flag=True, help="Run with visible browser")
def reconcile_run(headed: bool) -> None:
    """Run bank reconciliation."""
    click.echo("Bank reconciliation requires web agent. Starting...")

    async def _reconcile():
        from nocfo.web_agent.browser import BrowserManager

        async with BrowserManager(headless=not headed) as browser:
            await browser.new_page()
            click.echo("Browser started. Reconciliation agent running...")
            # TODO: Full pipeline - fetch transactions, run matching, apply via web agent
            click.echo("Reconciliation pipeline not yet fully connected.")
            return {"status": "not_implemented"}

    result = run_async(_reconcile())
    click.echo(f"Result: {result['status']}")


@reconcile.command("status")
def reconcile_status() -> None:
    """Show reconciliation status."""
    click.echo("Reconciliation status: not yet implemented")


# --- Closing commands ---


@cli.group()
def close() -> None:
    """Period closing."""
    pass


@close.command("check")
@click.argument("month")
def close_check(month: str) -> None:
    """Check if a month can be closed (format: YYYY-MM)."""
    from nocfo.bookkeeping.closing import ClosingService
    from nocfo.fortnox.auth import TokenManager
    from nocfo.fortnox.client import FortnoxClient

    period_end = parse_month(month)

    async def _check():
        manager = TokenManager()
        await manager.initialize()
        async with FortnoxClient(token_manager=manager) as client:
            closing = ClosingService(client)
            return await closing.check_period(period_end)

    result = run_async(_check())
    click.echo(f"Period: {period_end}")
    click.echo(f"Ready: {'Yes' if result.is_ready else 'No'}")
    for name, passed in result.checks.items():
        status = "PASS" if passed else "FAIL"
        click.echo(f"  [{status}] {name}")
    if result.issues:
        click.echo("\nIssues:")
        for issue in result.issues:
            click.echo(f"  - {issue}")


@close.command("run")
@click.argument("month")
@click.option("--headed", is_flag=True, help="Run with visible browser")
def close_run(month: str, headed: bool) -> None:
    """Execute period closing (format: YYYY-MM)."""
    period_end = parse_month(month)

    click.echo(f"Closing period ending {period_end}...")
    click.echo("This requires web agent. Starting browser...")

    async def _close():
        from nocfo.web_agent.browser import BrowserManager
        from nocfo.web_agent.tasks.period_closing import run_period_closing

        async with BrowserManager(headless=not headed) as browser:
            page = await browser.new_page()
            return await run_period_closing(page, period_end)

    result = run_async(_close())
    click.echo(f"Result: {result['status']} - {result['message']}")


# --- Schedule commands ---


@cli.group()
def schedule() -> None:
    """Scheduler management."""
    pass


@schedule.command("start")
def schedule_start() -> None:
    """Start the job scheduler."""
    from nocfo.scheduler.runner import Scheduler

    click.echo("Starting scheduler... (Ctrl+C to stop)")

    async def _start():
        sched = Scheduler()
        try:
            await sched.start()
        except KeyboardInterrupt:
            sched.stop()

    try:
        run_async(_start())
    except KeyboardInterrupt:
        click.echo("\nScheduler stopped.")


@schedule.command("status")
def schedule_status() -> None:
    """Show scheduled jobs."""
    from nocfo.scheduler.runner import Scheduler

    sched = Scheduler()
    sched.setup()
    jobs = sched.list_jobs()

    for job in jobs:
        click.echo(f"  {job['id']:<30} next: {job['next_run']}")


# --- Report commands ---


@cli.command()
@click.argument("report_type", type=click.Choice(["balance", "income"]))
@click.option("--period", required=True, help="Report period (e.g. 2024-01)")
@click.option("--headed", is_flag=True, help="Run with visible browser")
def report(report_type: str, period: str, headed: bool) -> None:
    """Download a financial report."""
    type_map = {
        "balance": "Balansrapport",
        "income": "Resultatrapport",
    }

    async def _download():
        from nocfo.web_agent.browser import BrowserManager
        from nocfo.web_agent.tasks.reports import run_report_download

        async with BrowserManager(headless=not headed) as browser:
            page = await browser.new_page()
            return await run_report_download(page, type_map[report_type], period)

    click.echo(f"Downloading {type_map[report_type]} for {period}...")
    result = run_async(_download())
    click.echo(f"Result: {result['status']} - {result['message']}")


# --- Approve command ---


@cli.command()
@click.argument("job_id")
def approve(job_id: str) -> None:
    """Approve a pending destructive operation."""
    # TODO: Implement approval mechanism
    click.echo(f"Approved job: {job_id}")
    click.echo("Approval mechanism not yet implemented")
