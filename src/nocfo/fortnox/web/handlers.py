"""Fortnox route handlers — registered onto BrowserAPIHandler via @register_route."""

import asyncio
import base64
import tempfile
import threading
from pathlib import Path

import structlog

from nocfo.browser.handler import BrowserAPIHandler, register_route
from nocfo.browser.operations_state import (
    add_qr_url,
    mark_browser_work_started,
    new_operation,
    update_operation,
)
from nocfo.browser.tokens import generate_token

logger = structlog.get_logger()


# --- Auth routes ---


@register_route("POST", "/auth/start")
def handle_auth_start(handler: BrowserAPIHandler) -> None:
    """POST /auth/start — Create auth operation with long-lived token.

    No browser work happens here. The BankID flow is triggered lazily
    when the user opens the live_url and the SSE connection is established.

    If a valid session already exists for the customer, returns
    "already_authenticated" unless force=true is passed.
    """
    body = handler._read_body()
    customer_id = body.get("customer_id")
    if not customer_id:
        handler._send_json({"error": "customer_id required"}, status=400)
        return

    # Short-circuit if session is already valid (skip BankID)
    force = body.get("force", False)
    if not force:
        from nocfo.fortnox.web.session import has_valid_session
        if has_valid_session(customer_id, sessions_dir=handler.sessions_dir):
            logger.info("auth_session_valid", customer_id=customer_id)
            handler._send_json({
                "status": "already_authenticated",
                "customer_id": customer_id,
                "message": "Valid session exists. Use force=true to re-authenticate.",
            })
            return

    op_id = new_operation("auth", customer_id=customer_id, initial_status="awaiting_user")

    # Long-lived token (24h) — user can open link hours/days later
    token = generate_token(op_id, context={"action": "login"}, ttl=86400)
    live_url = f"{handler.funnel_base}/auth/live?token={token}"
    add_qr_url(op_id, live_url)

    logger.info("auth_operation_created", operation_id=op_id, live_url=live_url)

    handler._send_json({
        "operation_id": op_id,
        "status": "awaiting_user",
        "live_url": live_url,
        "poll_url": f"/operation/{op_id}",
        "message": "Send live_url to customer. BankID starts when they open it.",
    }, status=202)


def trigger_bankid_flow(op_id: str, pw_worker, sessions_dir: str, is_mobile: bool = False) -> None:
    """Start the BankID browser flow for an operation.

    Uses mark_browser_work_started() for atomic dedup — safe to call
    from concurrent SSE connections.
    """
    if not mark_browser_work_started(op_id):
        return  # already started by another SSE connection

    from nocfo.browser.operations_state import get_operation_internal

    op = get_operation_internal(op_id)
    customer_id = op.get("customer_id") if op else None

    def run_auth():
        def auth_work(browser):
            from nocfo.fortnox.web.auth import bankid_login_with_qr_capture
            from nocfo.fortnox.web.session import save_session

            # Always use a fresh context for auth — prevents old session
            # cookies from causing Fortnox to auto-login without BankID
            ctx = browser.new_context()
            page = ctx.new_page()

            try:
                success = bankid_login_with_qr_capture(page, op_id, is_mobile=is_mobile)
                if not success:
                    # BankID may have completed just after the poll loop ended.
                    # Wait briefly and check one more time before giving up.
                    import time
                    time.sleep(5)
                    from nocfo.fortnox.web.auth import _is_logged_in, TENANT_SELECT_URL
                    if _is_logged_in(page):
                        logger.info("bankid_late_login_detected")
                        try:
                            page.goto(TENANT_SELECT_URL, wait_until="domcontentloaded", timeout=15000)
                        except Exception:
                            pass
                        success = True
                if success:
                    if customer_id:
                        save_session(page, customer_id, sessions_dir=sessions_dir)
                    update_operation(op_id, status="complete", result={"authenticated": True})
            except Exception as e:
                update_operation(op_id, status="failed", error=str(e))
            finally:
                page.close()
                ctx.close()

        try:
            pw_worker.submit(auth_work)
        except Exception as e:
            logger.error("bankid_flow_error", operation_id=op_id, error=str(e))
            update_operation(op_id, status="failed", error=str(e))

    threading.Thread(target=run_auth, daemon=True).start()
    logger.info("bankid_flow_triggered", operation_id=op_id)


@register_route("GET", "/auth/status")
def handle_auth_status(handler: BrowserAPIHandler) -> None:
    """GET /auth/status — Check if Fortnox session is active."""
    from nocfo.fortnox.web.session import is_authenticated

    result = handler._with_page(
        lambda page: {"authenticated": is_authenticated(page)}
    )
    handler._send_json(result)


@register_route("POST", "/auth/login")
def handle_auth_login(handler: BrowserAPIHandler) -> None:
    """POST /auth/login — Start BankID login flow (legacy blocking)."""
    from nocfo.fortnox.web.auth import bankid_login

    result = handler._with_page(bankid_login)
    handler._send_json(result)


# --- Operation routes ---


@register_route("POST", "/reconciliation/run")
def handle_reconciliation_run(handler: BrowserAPIHandler) -> None:
    """POST /reconciliation/run — Execute bank reconciliation."""
    from nocfo.fortnox.web.operations.reconciliation import run_reconciliation

    body = handler._read_body()
    customer_id = body.get("customer_id")
    account = body.get("account")
    matches = body.get("matches", [])

    if not customer_id:
        handler._send_json({"error": "customer_id is required"}, status=400)
        return
    if not account:
        handler._send_json({"error": "account is required"}, status=400)
        return

    result = handler._with_customer_page(
        customer_id,
        lambda page: run_reconciliation(page, account=account, matches=matches),
    )
    handler._send_json(result)


@register_route("POST", "/period/close")
def handle_period_close(handler: BrowserAPIHandler) -> None:
    """POST /period/close — Lock a period."""
    from nocfo.fortnox.web.operations.period_closing import close_period

    body = handler._read_body()
    customer_id = body.get("customer_id")
    period = body.get("period")

    if not customer_id:
        handler._send_json({"error": "customer_id is required"}, status=400)
        return
    if not period:
        handler._send_json({"error": "period is required"}, status=400)
        return

    result = handler._with_customer_page(
        customer_id, lambda page: close_period(page, period=period)
    )
    handler._send_json(result)


@register_route("POST", "/reports/discover")
def handle_reports_discover(handler: BrowserAPIHandler) -> None:
    """POST /reports/discover — Discover Fortnox internal report API endpoints."""
    from nocfo.fortnox.web.operations.reports import discover_report_api

    body = handler._read_body()
    customer_id = body.get("customer_id")

    if not customer_id:
        handler._send_json({"error": "customer_id is required"}, status=400)
        return

    result = handler._with_customer_page(customer_id, discover_report_api)
    handler._send_json(result)


@register_route("POST", "/reports/download")
def handle_reports_download(handler: BrowserAPIHandler) -> None:
    """POST /reports/download — Download a financial report."""
    from nocfo.fortnox.web.operations.reports import download_report

    body = handler._read_body()
    customer_id = body.get("customer_id")
    report_type = body.get("type")
    period = body.get("period")

    if not customer_id:
        handler._send_json({"error": "customer_id is required"}, status=400)
        return
    if not report_type or not period:
        handler._send_json({"error": "type and period are required"}, status=400)
        return

    result = handler._with_customer_page(
        customer_id,
        lambda page: download_report(page, report_type=report_type, period=period),
    )

    # If the result contains file data, send as file download
    if isinstance(result, dict) and result.get("file_data"):
        file_bytes = base64.b64decode(result["file_data"])
        handler._send_file(
            file_bytes,
            content_type=result.get("content_type", "application/pdf"),
            filename=result.get("filename", f"report_{report_type}_{period}.pdf"),
        )
    else:
        handler._send_json(result)


@register_route("POST", "/rules/list")
def handle_rules_list(handler: BrowserAPIHandler) -> None:
    """POST /rules/list — List current Regelverk."""
    from nocfo.fortnox.web.operations.rules import list_rules

    body = handler._read_body()
    customer_id = body.get("customer_id")

    if not customer_id:
        handler._send_json({"error": "customer_id is required"}, status=400)
        return

    result = handler._with_customer_page(customer_id, list_rules)
    handler._send_json(result)


@register_route("POST", "/rules/sync")
def handle_rules_sync(handler: BrowserAPIHandler) -> None:
    """POST /rules/sync — Sync rules to Fortnox."""
    from nocfo.fortnox.web.operations.rules import sync_rules

    body = handler._read_body()
    customer_id = body.get("customer_id")
    rules = body.get("rules", [])

    if not customer_id:
        handler._send_json({"error": "customer_id is required"}, status=400)
        return

    result = handler._with_customer_page(
        customer_id, lambda page: sync_rules(page, rules=rules)
    )
    handler._send_json(result)


# --- Receipt routes ---


@register_route("POST", "/receipts/analyze")
def handle_receipts_analyze(handler: BrowserAPIHandler) -> None:
    """POST /receipts/analyze — Analyze a receipt PDF and return proposed voucher entries.

    Dry-run only — no Fortnox write occurs. Returns the full analysis plus a
    proposed_voucher dict and a human-readable preview for user confirmation.

    Body: {
        "customer_id": str,
        "file_path": str,       # absolute path on the server, OR
        "file_content": str,    # base64-encoded file bytes
        "filename": str         # required when using file_content (default: "receipt.pdf")
    }
    """
    from nocfo.bookkeeping.invoice_to_voucher import create_voucher_from_invoice
    from nocfo.config import get_settings
    from nocfo.fortnox.api.client import FortnoxClient

    body = handler._read_body()
    customer_id = body.get("customer_id")
    if not customer_id:
        handler._send_json({"error": "customer_id required"}, status=400)
        return

    file_path_str = body.get("file_path")
    file_content_b64 = body.get("file_content")
    if not file_path_str and not file_content_b64:
        handler._send_json({"error": "file_path or file_content required"}, status=400)
        return

    settings = get_settings()
    if not settings.anthropic_api_key:
        handler._send_json({"error": "ANTHROPIC_API_KEY not configured"}, status=500)
        return

    tmp_path: Path | None = None
    try:
        if file_content_b64:
            pdf_bytes = base64.b64decode(file_content_b64)
            filename = body.get("filename", "receipt.pdf")
            suffix = Path(filename).suffix or ".pdf"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(pdf_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            pdf_path = tmp_path
        else:
            pdf_path = Path(file_path_str)

        async def _analyze():
            async with FortnoxClient() as client:
                await client._token_manager.initialize()
                return await create_voucher_from_invoice(
                    pdf_path,
                    client,
                    settings.anthropic_api_key,
                    customer_id=customer_id,
                    dry_run=True,
                )

        analysis, _ = asyncio.run(_analyze())
        voucher = analysis.to_voucher()

        handler._send_json({
            "supplier_name": analysis.supplier_name,
            "invoice_number": analysis.invoice_number,
            "invoice_date": str(analysis.invoice_date),
            "payment_date": str(analysis.payment_date),
            "description": analysis.description,
            "total_net": str(analysis.total_net),
            "total_vat": str(analysis.total_vat),
            "total_gross": str(analysis.total_gross),
            "vat_rate": analysis.vat_rate,
            "confidence": analysis.confidence,
            "notes": analysis.notes,
            "items": analysis.items,
            "preview": analysis.preview(),
            "proposed_voucher": {
                "description": voucher.description,
                "voucher_series": voucher.voucher_series,
                "transaction_date": str(voucher.transaction_date),
                "rows": [
                    {
                        "account": r.account,
                        "debit": str(r.debit),
                        "credit": str(r.credit),
                        "transaction_information": r.transaction_information,
                    }
                    for r in voucher.rows
                ],
            },
        })
    except Exception as e:
        logger.error("receipt_analysis_failed", error=str(e))
        handler._send_json({"error": str(e)}, status=500)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()


@register_route("POST", "/receipts/book")
def handle_receipts_book(handler: BrowserAPIHandler) -> None:
    """POST /receipts/book — Create an approved voucher in Fortnox and attach the PDF.

    Pass the proposed_voucher from /receipts/analyze as the voucher field. Pydantic
    validates balance (debits == credits) before any Fortnox write.

    Body: {
        "customer_id": str,
        "file_path": str,       # absolute path on the server, OR
        "file_content": str,    # base64-encoded file bytes
        "filename": str,        # required when using file_content
        "voucher": {
            "description": str,
            "voucher_series": str,
            "transaction_date": str,  # ISO date
            "rows": [{"account": int, "debit": str, "credit": str, "transaction_information": str}]
        }
    }
    """
    from nocfo.fortnox.api.client import FortnoxClient
    from nocfo.fortnox.api.file_connections import FileConnectionService
    from nocfo.fortnox.api.inbox import InboxService
    from nocfo.fortnox.api.models import Voucher
    from nocfo.fortnox.api.vouchers import VoucherService

    body = handler._read_body()
    customer_id = body.get("customer_id")
    if not customer_id:
        handler._send_json({"error": "customer_id required"}, status=400)
        return

    voucher_data = body.get("voucher")
    if not voucher_data:
        handler._send_json({"error": "voucher required"}, status=400)
        return

    file_path_str = body.get("file_path")
    file_content_b64 = body.get("file_content")
    if not file_path_str and not file_content_b64:
        handler._send_json({"error": "file_path or file_content required"}, status=400)
        return

    try:
        voucher = Voucher.model_validate(voucher_data)
    except Exception as e:
        handler._send_json({"error": f"invalid voucher: {e}"}, status=400)
        return

    tmp_path: Path | None = None
    try:
        if file_content_b64:
            pdf_bytes = base64.b64decode(file_content_b64)
            filename = body.get("filename", "receipt.pdf")
            suffix = Path(filename).suffix or ".pdf"
            tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            tmp.write(pdf_bytes)
            tmp.close()
            tmp_path = Path(tmp.name)
            pdf_path = tmp_path
        else:
            pdf_path = Path(file_path_str)

        async def _book():
            async with FortnoxClient() as client:
                await client._token_manager.initialize()
                created = await VoucherService(client).create(voucher)
                file_id = await InboxService(client).upload(pdf_path)
                await FileConnectionService(client).connect_to_voucher(
                    file_id, created.voucher_series, created.voucher_number
                )
                return created

        created = asyncio.run(_book())
        handler._send_json({
            "voucher_series": created.voucher_series,
            "voucher_number": created.voucher_number,
            "status": "created",
        })
    except Exception as e:
        logger.error("receipt_booking_failed", error=str(e))
        handler._send_json({"error": str(e)}, status=500)
    finally:
        if tmp_path and tmp_path.exists():
            tmp_path.unlink()
