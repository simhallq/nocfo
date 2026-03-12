"""NoCFO CLI entry point."""

import asyncio
import logging
import sys

import click
import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
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


# --- Record commands ---


@cli.group()
def record() -> None:
    """Workflow recording and replay."""
    pass


@record.command("start")
@click.argument("name")
@click.option("--url", default=None, help="Starting URL to navigate to")
@click.option("--enhance", is_flag=True, help="Enhance selectors with Claude vision")
@click.option("--cdp-url", default="http://localhost:9222", help="Chrome DevTools Protocol URL")
def record_start(name: str, url: str | None, enhance: bool, cdp_url: str) -> None:
    """Record a browser workflow. Interact with the page, then Ctrl+C to save."""
    import signal

    from playwright.sync_api import sync_playwright

    from nocfo.config import get_settings
    from nocfo.recorder.recorder import WorkflowRecorder

    settings = get_settings()

    click.echo(f"Connecting to Chrome at {cdp_url}...")
    click.echo("Interact with the browser. Press Ctrl+C to stop and save.\n")

    pw = sync_playwright().start()
    stop_requested = False

    def _request_stop(sig, frame):
        nonlocal stop_requested
        stop_requested = True

    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        if url:
            page.goto(url, wait_until="networkidle", timeout=30000)

        recorder = WorkflowRecorder(
            name=name,
            page=page,
            workflows_dir=settings.workflows_dir,
            screenshots_dir=settings.workflows_dir.parent / "screenshots",
            enhance_with_vision=enhance,
        )
        recorder.start()

        # Handle both Ctrl+C (SIGINT) and SIGTERM for clean shutdown
        signal.signal(signal.SIGTERM, _request_stop)

        try:
            while not stop_requested:
                page.wait_for_timeout(500)
        except KeyboardInterrupt:
            pass

        workflow = recorder.stop()
        click.echo(f"\nRecording saved: {workflow.total_steps} steps")
        click.echo(f"  File: {settings.workflows_dir / name}.yaml")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        pw.stop()


@record.command("replay")
@click.argument("name")
@click.option("--speed", default=1.0, type=float, help="Replay speed multiplier")
@click.option("--strict/--no-strict", default=True, help="Stop on first failure")
@click.option("--cdp-url", default="http://localhost:9222", help="Chrome DevTools Protocol URL")
def record_replay(name: str, speed: float, strict: bool, cdp_url: str) -> None:
    """Replay a recorded workflow."""
    from playwright.sync_api import sync_playwright

    from nocfo.config import get_settings
    from nocfo.recorder.models import Workflow
    from nocfo.recorder.replay import ReplayEngine

    settings = get_settings()
    yaml_path = settings.workflows_dir / f"{name}.yaml"

    if not yaml_path.exists():
        click.echo(f"Workflow not found: {yaml_path}", err=True)
        sys.exit(1)

    workflow = Workflow.from_yaml(yaml_path)
    click.echo(f"Replaying '{name}' ({workflow.total_steps} steps, speed={speed}x)...")

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        engine = ReplayEngine(workflow, page, speed=speed, strict=strict)
        result = engine.run()

        click.echo(f"\nReplay complete: {result.passed}/{result.total_steps} passed")
        if result.failed:
            click.echo(f"  Failed steps: {result.failed}")
            for sr in result.step_results:
                if not sr.success:
                    click.echo(f"    Step {sr.step} ({sr.action}): {sr.error}")
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        pw.stop()


@record.command("list")
def record_list() -> None:
    """List saved workflows."""
    from nocfo.config import get_settings

    settings = get_settings()
    workflows_dir = settings.workflows_dir

    if not workflows_dir.exists():
        click.echo("No workflows directory found.")
        return

    yaml_files = sorted(workflows_dir.glob("*.yaml"))
    if not yaml_files:
        click.echo("No recorded workflows found.")
        return

    from nocfo.recorder.models import Workflow

    for path in yaml_files:
        try:
            wf = Workflow.from_yaml(path)
            click.echo(f"  {wf.name:<30} {wf.total_steps:>3} steps  {wf.start_url}")
        except Exception:
            click.echo(f"  {path.stem:<30} (invalid YAML)")


@record.command("show")
@click.argument("name")
def record_show(name: str) -> None:
    """Show workflow steps summary."""
    from nocfo.config import get_settings
    from nocfo.recorder.models import Workflow

    settings = get_settings()
    yaml_path = settings.workflows_dir / f"{name}.yaml"

    if not yaml_path.exists():
        click.echo(f"Workflow not found: {yaml_path}", err=True)
        sys.exit(1)

    workflow = Workflow.from_yaml(yaml_path)
    click.echo(f"Workflow: {workflow.name}")
    click.echo(f"Recorded: {workflow.recorded_at}")
    click.echo(f"Start URL: {workflow.start_url}")
    click.echo(f"Steps: {workflow.total_steps}\n")

    for step in workflow.steps:
        selector = step.selectors.best() or "(no selector)"
        value_str = f" = {step.value!r}" if step.value else ""
        wait_str = f" (wait {step.wait_before_ms}ms)" if step.wait_before_ms else ""
        click.echo(f"  {step.step:>3}. [{step.action:<6}] {selector}{value_str}{wait_str}")


@record.command("enhance")
@click.argument("name")
def record_enhance(name: str) -> None:
    """Enhance a recorded workflow with Claude vision for better selectors."""
    from nocfo.config import get_settings
    from nocfo.recorder.enhancer import enhance_workflow
    from nocfo.recorder.models import Workflow

    settings = get_settings()
    yaml_path = settings.workflows_dir / f"{name}.yaml"

    if not yaml_path.exists():
        click.echo(f"Workflow not found: {yaml_path}", err=True)
        sys.exit(1)

    if not settings.validate_anthropic_key():
        click.echo("Error: ANTHROPIC_API_KEY must be set for vision enhancement", err=True)
        sys.exit(1)

    workflow = Workflow.from_yaml(yaml_path)
    click.echo(f"Enhancing '{name}' ({workflow.total_steps} steps)...")

    workflow = enhance_workflow(workflow)
    workflow.to_yaml(yaml_path)

    enhanced_count = sum(1 for s in workflow.steps if s.selectors.semantic)
    click.echo(f"Enhanced {enhanced_count}/{workflow.total_steps} steps with semantic selectors.")
