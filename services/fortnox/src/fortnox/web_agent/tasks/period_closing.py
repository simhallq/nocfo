"""Period closing via Fortnox web UI."""

from datetime import date

import structlog
from playwright.async_api import Page

from fortnox.web_agent.agent import WebAgent
from fortnox.web_agent.prompts import PERIOD_CLOSING_PROMPT

logger = structlog.get_logger()


async def run_period_closing(page: Page, period_end: date) -> dict:
    """Execute period closing via the Fortnox web UI."""
    prompt = PERIOD_CLOSING_PROMPT.format(period_end=period_end.isoformat())

    agent = WebAgent(page=page, system_prompt=prompt)
    result = await agent.run()

    logger.info(
        "period_closing_task_complete",
        period_end=period_end.isoformat(),
        status=result["status"],
        iterations=result["iterations"],
    )
    return result
