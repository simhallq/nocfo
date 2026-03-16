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
@click.option("--customer", default=None, help="Customer session ID to inject cookies from (e.g. hem-atelier-styrman)")
def setup(customer: str | None) -> None:
    """Run interactive OAuth setup."""
    from nocfo.config import get_settings
    from nocfo.fortnox.api.auth import TokenManager, exchange_code_for_token, start_authorization

    settings = get_settings()
    if not settings.validate_fortnox_credentials():
        click.echo("Error: FORTNOX_CLIENT_ID and FORTNOX_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    click.echo("Starting OAuth authorization flow...")
    if customer:
        click.echo(f"Using stored session for '{customer}'")
    else:
        click.echo("A browser window will open. Please authorize the application.")

    code = start_authorization(customer_id=customer)
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
    from nocfo.fortnox.api.auth import TokenManager

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
        from nocfo.fortnox.api.client import FortnoxClient
        from nocfo.fortnox.api.health import HealthCheck

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


@voucher.command("from-invoice")
@click.argument("pdf_path", type=click.Path(exists=True))
@click.option("--date", "txn_date", default=None, help="Transaction date override (YYYY-MM-DD)")
@click.option("--customer", default=None, help="Customer ID for company-specific rules (e.g. hem-atelier-styrman)")
@click.option("--history", is_flag=True, help="Include recent voucher history for supplier precedent")
@click.option("--post", is_flag=True, help="Actually create the voucher (default is dry-run preview)")
def voucher_from_invoice(pdf_path: str, txn_date: str | None, customer: str | None, history: bool, post: bool) -> None:
    """Analyze a PDF invoice and create a voucher from it."""
    from datetime import date as date_cls
    from pathlib import Path

    from nocfo.bookkeeping.invoice_to_voucher import create_voucher_from_invoice
    from nocfo.config import get_settings
    from nocfo.fortnox.api.auth import TokenManager
    from nocfo.fortnox.api.client import FortnoxClient

    settings = get_settings()
    if not settings.validate_anthropic_key():
        click.echo("Error: ANTHROPIC_API_KEY must be set in .env")
        sys.exit(1)

    override_date = date_cls.fromisoformat(txn_date) if txn_date else None

    async def _run():
        manager = TokenManager()
        await manager.initialize()
        async with FortnoxClient(token_manager=manager) as client:
            return await create_voucher_from_invoice(
                pdf_path=Path(pdf_path),
                client=client,
                anthropic_api_key=settings.anthropic_api_key,
                transaction_date=override_date,
                customer_id=customer,
                fetch_history=history,
                dry_run=not post,
            )

    analysis, voucher = run_async(_run())

    click.echo("\n" + analysis.preview() + "\n")

    if post and voucher:
        click.echo(
            f"Voucher created: {voucher.voucher_series}{voucher.voucher_number} "
            f"on {voucher.transaction_date}"
        )
        click.echo("Invoice PDF uploaded and attached.")
    elif not post:
        click.echo("DRY RUN — no voucher created. Use --post to create it.")


@voucher.command("list")
@click.option("--series", default="A", help="Voucher series")
def voucher_list(series: str) -> None:
    """List vouchers."""
    from nocfo.fortnox.api.auth import TokenManager
    from nocfo.fortnox.api.client import FortnoxClient
    from nocfo.fortnox.api.vouchers import VoucherService

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
    from nocfo.fortnox.api.auth import TokenManager
    from nocfo.fortnox.api.client import FortnoxClient
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
@click.option("--headed", is_flag=True, help="Run with visible browser (legacy web agent)")
@click.option("--browser-api", is_flag=True, default=True, help="Use browser API (default)")
def reconcile_run(headed: bool, browser_api: bool) -> None:
    """Run bank reconciliation."""
    if browser_api:
        from nocfo.browser.client import BrowserApiClient
        from nocfo.config import get_settings

        settings = get_settings()
        click.echo("Running reconciliation via browser API...")
        with BrowserApiClient(
            base_url=settings.browser_api_url,
            token=settings.browser_api_token,
        ) as client:
            result = client.reconcile(account=1930, matches=[])
        click.echo(f"Result: {result.get('status', 'unknown')}")
        if result.get("matched"):
            click.echo(f"  Matched: {result['matched']}/{result['total']}")
    else:
        click.echo("Bank reconciliation requires web agent. Starting...")

        async def _reconcile():
            from nocfo.web_agent.browser import BrowserManager

            async with BrowserManager(headless=not headed) as browser:
                await browser.new_page()
                click.echo("Browser started. Reconciliation agent running...")
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
    from nocfo.fortnox.api.auth import TokenManager
    from nocfo.fortnox.api.client import FortnoxClient

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
@click.option("--headed", is_flag=True, help="Run with visible browser (legacy web agent)")
@click.option("--browser-api", is_flag=True, default=True, help="Use browser API (default)")
def close_run(month: str, headed: bool, browser_api: bool) -> None:
    """Execute period closing (format: YYYY-MM)."""
    period_end = parse_month(month)

    if browser_api:
        from nocfo.browser.client import BrowserApiClient
        from nocfo.config import get_settings

        settings = get_settings()
        click.echo(f"Closing period {month} via browser API...")
        with BrowserApiClient(
            base_url=settings.browser_api_url,
            token=settings.browser_api_token,
        ) as client:
            result = client.close_period(month)
        click.echo(f"Result: {result.get('status', 'unknown')} - {result.get('message', '')}")
    else:
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
@click.option("--headed", is_flag=True, help="Run with visible browser (legacy web agent)")
@click.option("--browser-api", is_flag=True, default=True, help="Use browser API (default)")
def report(report_type: str, period: str, headed: bool, browser_api: bool) -> None:
    """Download a financial report."""
    type_map = {
        "balance": "Balansrapport",
        "income": "Resultatrapport",
    }

    if browser_api:
        from nocfo.browser.client import BrowserApiClient
        from nocfo.config import get_settings

        settings = get_settings()
        click.echo(f"Downloading {type_map[report_type]} for {period} via browser API...")
        with BrowserApiClient(
            base_url=settings.browser_api_url,
            token=settings.browser_api_token,
        ) as client:
            try:
                file_bytes = client.download_report(report_type, period)
                output_path = f"{type_map[report_type]}_{period}.pdf"
                with open(output_path, "wb") as f:
                    f.write(file_bytes)
                click.echo(f"Report saved: {output_path} ({len(file_bytes)} bytes)")
            except Exception as e:
                click.echo(f"Error: {e}")
                sys.exit(1)
    else:
        async def _download():
            from nocfo.web_agent.browser import BrowserManager
            from nocfo.web_agent.tasks.reports import run_report_download

            async with BrowserManager(headless=not headed) as browser:
                page = await browser.new_page()
                return await run_report_download(page, type_map[report_type], period)

        click.echo(f"Downloading {type_map[report_type]} for {period}...")
        result = run_async(_download())
        click.echo(f"Result: {result['status']} - {result['message']}")


# --- Browser commands ---


@cli.group()
def browser() -> None:
    """Browser API management."""
    pass


@browser.command("start")
@click.option("--headless", is_flag=True, help="Run Chrome headless")
def browser_start(headless: bool) -> None:
    """Launch Chrome and start the Browser API server."""
    from nocfo.browser.chrome import is_cdp_reachable, launch_chrome
    from nocfo.browser.server import run_server
    from nocfo.config import get_settings

    settings = get_settings()
    port = int(settings.browser_api_url.split(":")[-1])
    cdp_port = settings.browser_cdp_port

    # Launch Chrome if not already running
    if not is_cdp_reachable(cdp_port):
        click.echo(f"Launching Chrome (CDP port {cdp_port})...")
        launch_chrome(
            port=cdp_port,
            profile_dir=settings.browser_profile_dir,
            headless=headless,
        )
    else:
        click.echo(f"Chrome already running on CDP port {cdp_port}")

    # Start the API server (blocking)
    click.echo(f"Starting Browser API on port {port}...")
    run_server(
        port=port,
        cdp_port=cdp_port,
        auth_token=settings.browser_api_token,
        funnel_base=settings.funnel_base,
        sessions_dir=str(settings.sessions_dir),
    )


@browser.command("status")
def browser_status() -> None:
    """Check if browser API is running and authenticated."""
    from nocfo.browser.client import BrowserApiClient
    from nocfo.config import get_settings

    settings = get_settings()

    try:
        with BrowserApiClient(
            base_url=settings.browser_api_url,
            token=settings.browser_api_token,
        ) as client:
            health = client.health()

        chrome_status = health.get("chrome", {})
        session_status = health.get("session", {})

        click.echo(f"Server: {health.get('status', 'unknown')}")
        click.echo(f"Chrome CDP: {'connected' if chrome_status.get('cdp_reachable') else 'disconnected'}")
        click.echo(f"Session: {'authenticated' if session_status.get('authenticated') else 'not authenticated'}")
    except Exception as e:
        click.echo(f"Browser API not reachable: {e}")
        sys.exit(1)


@browser.command("login")
def browser_login() -> None:
    """Trigger BankID login via the browser API."""
    from nocfo.browser.client import BrowserApiClient
    from nocfo.config import get_settings

    settings = get_settings()

    click.echo("Starting BankID login...")
    click.echo("A QR code will appear in the Chrome window. Scan it with BankID.")

    try:
        with BrowserApiClient(
            base_url=settings.browser_api_url,
            token=settings.browser_api_token,
            timeout=150.0,  # BankID login can take up to 120s
        ) as client:
            result = client.login()

        status = result.get("status", "unknown")
        if status == "authenticated":
            click.echo("Login successful!")
        elif status == "timeout":
            click.echo("Login timed out. Please try again.")
        else:
            click.echo(f"Login result: {status} - {result.get('message', '')}")
    except Exception as e:
        click.echo(f"Login failed: {e}")
        sys.exit(1)


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
            page.goto(url, wait_until="domcontentloaded", timeout=30000)

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

        import time as _time

        try:
            while not stop_requested:
                try:
                    page.wait_for_timeout(500)
                except Exception:
                    _time.sleep(0.5)
                recorder.process_pending()
        except KeyboardInterrupt:
            pass

        # Drain any final events before stopping
        recorder.process_pending()

        workflow = recorder.stop()
        click.echo(f"\nRecording saved: {workflow.total_steps} steps")
        click.echo(f"  File: {settings.workflows_dir / name}.yaml")

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        try:
            pw.stop()
        except Exception:
            pass


@record.command("replay")
@click.argument("name")
@click.option("--speed", default=1.0, type=float, help="Replay speed multiplier")
@click.option("--strict/--no-strict", default=True, help="Stop on first failure")
@click.option("--vision-fallback", is_flag=True, help="Use Claude vision when selectors fail")
@click.option("--cdp-url", default="http://localhost:9222", help="Chrome DevTools Protocol URL")
def record_replay(
    name: str, speed: float, strict: bool, vision_fallback: bool, cdp_url: str
) -> None:
    """Replay a recorded workflow."""
    from playwright.sync_api import sync_playwright

    from nocfo.config import get_settings
    from nocfo.recorder.models import Workflow
    from nocfo.recorder.replay import ReplayEngine

    settings = get_settings()

    if vision_fallback and not settings.validate_anthropic_key():
        click.echo(
            "Error: ANTHROPIC_API_KEY must be set for --vision-fallback", err=True
        )
        sys.exit(1)

    yaml_path = settings.workflows_dir / f"{name}.yaml"

    if not yaml_path.exists():
        click.echo(f"Workflow not found: {yaml_path}", err=True)
        sys.exit(1)

    workflow = Workflow.from_yaml(yaml_path)
    mode = " +vision" if vision_fallback else ""
    click.echo(
        f"Replaying '{name}' ({workflow.total_steps} steps, speed={speed}x{mode})..."
    )

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        engine = ReplayEngine(
            workflow, page, speed=speed, strict=strict, vision_fallback=vision_fallback
        )
        result = engine.run()

        click.echo(f"\nReplay complete: {result.passed}/{result.total_steps} passed")
        for sr in result.step_results:
            if sr.success and sr.fallback_used:
                click.echo(f"  Step {sr.step} [OK via {sr.fallback_used}] {sr.action}")
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


@cli.command("svd-invoice")
@click.option("--speed", default=1.0, type=float, help="Replay speed multiplier")
@click.option("--cdp-url", default="http://localhost:9222", help="Chrome DevTools Protocol URL")
def svd_invoice(speed: float, cdp_url: str) -> None:
    """Download the latest invoice from SvD (replays recorded workflow)."""
    from playwright.sync_api import sync_playwright

    from nocfo.config import get_settings
    from nocfo.recorder.models import Workflow
    from nocfo.recorder.replay import ReplayEngine

    settings = get_settings()
    yaml_path = settings.workflows_dir / "get_svd_invoice.yaml"

    if not yaml_path.exists():
        click.echo(
            f"Workflow not found: {yaml_path}\n"
            "Record it first: nocfo record start get_svd_invoice "
            "--url https://www.svd.se/minsida",
            err=True,
        )
        sys.exit(1)

    workflow = Workflow.from_yaml(yaml_path)
    click.echo(f"Replaying SvD invoice download ({workflow.total_steps} steps)...")

    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url)
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        page = context.pages[0] if context.pages else context.new_page()

        engine = ReplayEngine(workflow, page, speed=speed, strict=True)
        result = engine.run()

        click.echo(f"\nDone: {result.passed}/{result.total_steps} steps passed")
        if result.failed:
            for sr in result.step_results:
                if not sr.success:
                    click.echo(f"  Step {sr.step} ({sr.action}): {sr.error}")
            sys.exit(1)

    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
    finally:
        try:
            pw.stop()
        except Exception:
            pass


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
