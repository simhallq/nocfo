"""Report download via Fortnox web UI."""

import structlog
from playwright.async_api import Page

from nocfo.web_agent.agent import WebAgent
from nocfo.web_agent.prompts import REPORT_DOWNLOAD_PROMPT

logger = structlog.get_logger()


async def run_report_download(
    page: Page,
    report_type: str,
    period: str,
) -> dict:
    """Download a financial report via the Fortnox web UI.

    report_type: "Balansrapport" or "Resultatrapport"
    period: e.g. "2024-01" or "2024-01 - 2024-12"
    """
    prompt = REPORT_DOWNLOAD_PROMPT.format(report_type=report_type, period=period)

    agent = WebAgent(page=page, system_prompt=prompt)
    result = await agent.run()

    logger.info(
        "report_download_complete",
        report_type=report_type,
        period=period,
        status=result["status"],
    )
    return result
