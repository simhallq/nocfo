"""Fortnox route handlers — registered onto BrowserAPIHandler via @register_route."""

import base64
import threading

from nocfo.browser.handler import BrowserAPIHandler, register_route
from nocfo.browser.operations_state import new_operation, update_operation


# --- Auth routes ---


@register_route("POST", "/auth/start")
def handle_auth_start(handler: BrowserAPIHandler) -> None:
    """POST /auth/start — Initiate BankID auth for a customer."""
    body = handler._read_body()
    customer_id = body.get("customer_id")
    if not customer_id:
        handler._send_json({"error": "customer_id required"}, status=400)
        return

    op_id = new_operation("auth", customer_id=customer_id)

    def run_auth():
        def auth_work(browser):
            from nocfo.fortnox.web.auth import bankid_login_with_qr_capture
            from nocfo.fortnox.web.session import save_session

            ctx = browser.contexts[0] if browser.contexts else browser.new_context()
            page = ctx.new_page()
            try:
                if bankid_login_with_qr_capture(page, op_id, handler.funnel_base):
                    save_session(page, customer_id, sessions_dir=handler.sessions_dir)
                    update_operation(op_id, status="complete", result={"authenticated": True})
            except Exception as e:
                update_operation(op_id, status="failed", error=str(e))
            finally:
                page.close()

        handler.pw_worker.submit(auth_work)

    threading.Thread(target=run_auth, daemon=True).start()

    handler._send_json({
        "operation_id": op_id,
        "status": "pending",
        "poll_url": f"/operation/{op_id}",
        "message": "Auth started. Poll operation for qr_url, then send to customer.",
    }, status=202)


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
    account = body.get("account")
    matches = body.get("matches", [])

    if not account:
        handler._send_json({"error": "account is required"}, status=400)
        return

    result = handler._with_page(
        lambda page: run_reconciliation(page, account=account, matches=matches)
    )
    handler._send_json(result)


@register_route("POST", "/period/close")
def handle_period_close(handler: BrowserAPIHandler) -> None:
    """POST /period/close — Lock a period."""
    from nocfo.fortnox.web.operations.period_closing import close_period

    body = handler._read_body()
    period = body.get("period")

    if not period:
        handler._send_json({"error": "period is required"}, status=400)
        return

    result = handler._with_page(lambda page: close_period(page, period=period))
    handler._send_json(result)


@register_route("POST", "/reports/discover")
def handle_reports_discover(handler: BrowserAPIHandler) -> None:
    """POST /reports/discover — Discover Fortnox internal report API endpoints."""
    from nocfo.fortnox.web.operations.reports import discover_report_api

    result = handler._with_page(discover_report_api)
    handler._send_json(result)


@register_route("POST", "/reports/download")
def handle_reports_download(handler: BrowserAPIHandler) -> None:
    """POST /reports/download — Download a financial report."""
    from nocfo.fortnox.web.operations.reports import download_report

    body = handler._read_body()
    report_type = body.get("type")
    period = body.get("period")

    if not report_type or not period:
        handler._send_json({"error": "type and period are required"}, status=400)
        return

    result = handler._with_page(
        lambda page: download_report(page, report_type=report_type, period=period)
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

    result = handler._with_page(list_rules)
    handler._send_json(result)


@register_route("POST", "/rules/sync")
def handle_rules_sync(handler: BrowserAPIHandler) -> None:
    """POST /rules/sync — Sync rules to Fortnox."""
    from nocfo.fortnox.web.operations.rules import sync_rules

    body = handler._read_body()
    rules = body.get("rules", [])

    result = handler._with_page(lambda page: sync_rules(page, rules=rules))
    handler._send_json(result)
