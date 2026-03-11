"""Atomic browser actions for the web agent."""

import base64
from dataclasses import dataclass

import structlog
from playwright.async_api import Page

logger = structlog.get_logger()


@dataclass
class ActionResult:
    """Result of a browser action."""

    success: bool
    message: str = ""
    data: str = ""


async def screenshot(page: Page) -> bytes:
    """Take a screenshot and return as bytes."""
    return await page.screenshot(type="png", full_page=False)


async def screenshot_base64(page: Page) -> str:
    """Take a screenshot and return as base64-encoded string."""
    img_bytes = await screenshot(page)
    return base64.b64encode(img_bytes).decode()


async def click(page: Page, selector: str) -> ActionResult:
    """Click an element by CSS selector."""
    try:
        await page.click(selector, timeout=10000)
        await page.wait_for_load_state("networkidle", timeout=10000)
        return ActionResult(success=True, message=f"Clicked: {selector}")
    except Exception as e:
        return ActionResult(success=False, message=f"Click failed on {selector}: {e}")


async def fill(page: Page, selector: str, value: str) -> ActionResult:
    """Fill a text input field."""
    try:
        await page.fill(selector, value, timeout=10000)
        return ActionResult(success=True, message=f"Filled {selector} with value")
    except Exception as e:
        return ActionResult(success=False, message=f"Fill failed on {selector}: {e}")


async def select_option(page: Page, selector: str, value: str) -> ActionResult:
    """Select an option from a dropdown."""
    try:
        await page.select_option(selector, value, timeout=10000)
        return ActionResult(success=True, message=f"Selected {value} in {selector}")
    except Exception as e:
        return ActionResult(success=False, message=f"Select failed on {selector}: {e}")


async def navigate(page: Page, url: str) -> ActionResult:
    """Navigate to a URL."""
    try:
        await page.goto(url, wait_until="networkidle", timeout=30000)
        return ActionResult(success=True, message=f"Navigated to {url}")
    except Exception as e:
        return ActionResult(success=False, message=f"Navigation failed to {url}: {e}")


async def extract_text(page: Page, selector: str = "body") -> ActionResult:
    """Extract text content from an element."""
    try:
        text = await page.text_content(selector, timeout=10000)
        return ActionResult(success=True, data=text or "")
    except Exception as e:
        return ActionResult(success=False, message=f"Text extraction failed: {e}")


async def extract_table(page: Page, selector: str) -> ActionResult:
    """Extract table data as a list of row strings."""
    try:
        rows = await page.query_selector_all(f"{selector} tr")
        table_data = []
        for row in rows:
            cells = await row.query_selector_all("td, th")
            cell_texts = []
            for cell in cells:
                text = await cell.text_content()
                cell_texts.append((text or "").strip())
            table_data.append(" | ".join(cell_texts))

        return ActionResult(success=True, data="\n".join(table_data))
    except Exception as e:
        return ActionResult(success=False, message=f"Table extraction failed: {e}")


async def scroll(page: Page, direction: str = "down", amount: int = 500) -> ActionResult:
    """Scroll the page."""
    try:
        delta = amount if direction == "down" else -amount
        await page.mouse.wheel(0, delta)
        await page.wait_for_timeout(500)
        return ActionResult(success=True, message=f"Scrolled {direction} by {amount}px")
    except Exception as e:
        return ActionResult(success=False, message=f"Scroll failed: {e}")


async def wait_for_selector(page: Page, selector: str, timeout: int = 10000) -> ActionResult:
    """Wait for an element to appear."""
    try:
        await page.wait_for_selector(selector, timeout=timeout)
        return ActionResult(success=True, message=f"Element found: {selector}")
    except Exception as e:
        return ActionResult(success=False, message=f"Wait timeout for {selector}: {e}")
